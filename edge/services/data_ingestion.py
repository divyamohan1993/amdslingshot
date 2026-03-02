"""
JalNetra -- Async Data Ingestion Service

Fetches and normalizes real-world water, weather, and groundwater data
from Indian government APIs for fusion with local sensor readings:

  - CPCB (Central Pollution Control Board) -- real-time water quality
  - India-WRIS (Water Resources Information System) -- groundwater levels
  - IMD (India Meteorological Department) -- weather: temp, rainfall, humidity
  - data.gov.in -- open government datasets (CSV, JSON, XML)

All requests are fully async via httpx with:
  - Per-source TTL caching to respect rate limits
  - Automatic fallback to cached data when offline
  - Data normalization into a unified schema
  - Response format parsing: JSON, CSV, XML
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import httpx

logger = logging.getLogger("jalnetra.data_ingestion")


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """TTL-based cache entry for API responses."""

    data: Any
    fetched_at: float
    ttl_sec: float
    source: str

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl_sec

    @property
    def age_sec(self) -> float:
        return time.time() - self.fetched_at


# ---------------------------------------------------------------------------
# Normalized data records
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WaterQualityRecord:
    """Normalized water quality record from any source."""

    station_id: str
    station_name: str
    state: str
    latitude: float | None = None
    longitude: float | None = None
    timestamp: str = ""
    ph: float | None = None
    dissolved_oxygen_mg_l: float | None = None
    bod_mg_l: float | None = None
    cod_mg_l: float | None = None
    tds_ppm: float | None = None
    conductivity_umhos: float | None = None
    turbidity_ntu: float | None = None
    total_coliform: float | None = None
    fecal_coliform: float | None = None
    temperature_c: float | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True, slots=True)
class GroundwaterRecord:
    """Normalized groundwater level record."""

    well_id: str
    well_name: str
    state: str
    district: str
    latitude: float | None = None
    longitude: float | None = None
    timestamp: str = ""
    water_level_mbgl: float | None = None  # meters below ground level
    well_depth_m: float | None = None
    well_type: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True, slots=True)
class WeatherRecord:
    """Normalized weather observation record."""

    station_id: str
    station_name: str
    state: str
    latitude: float | None = None
    longitude: float | None = None
    timestamp: str = ""
    temperature_c: float | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    rainfall_mm: float | None = None
    humidity_pct: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction: str = ""
    pressure_hpa: float | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


# ---------------------------------------------------------------------------
# Response format helpers
# ---------------------------------------------------------------------------

def _parse_csv(text: str) -> list[dict[str, str]]:
    """Parse CSV text into a list of dicts."""
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _parse_xml_to_dicts(
    text: str, row_tag: str, field_tags: list[str] | None = None
) -> list[dict[str, str]]:
    """Parse XML text, extracting rows by *row_tag*."""
    root = ET.fromstring(text)
    rows: list[dict[str, str]] = []
    for elem in root.iter(row_tag):
        row: dict[str, str] = {}
        for child in elem:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if field_tags is None or tag in field_tags:
                row[tag] = (child.text or "").strip()
        if row:
            rows.append(row)
    return rows


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Convert a value to float, returning *default* on failure."""
    if value is None or value == "" or value == "NA" or value == "-":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Async Data Ingestion Service
# ---------------------------------------------------------------------------

class AsyncDataIngestion:
    """Fetches and normalizes external data from Indian government APIs.

    Usage::

        ingestion = AsyncDataIngestion(
            data_gov_api_key="your-key",
        )
        await ingestion.start()

        water_data = await ingestion.fetch_cpcb_water_quality(state="Maharashtra")
        weather = await ingestion.fetch_imd_weather(state="Maharashtra")
        groundwater = await ingestion.fetch_india_wris_groundwater(state="Maharashtra")
        datasets = await ingestion.fetch_data_gov(resource_id="abc123")

        await ingestion.stop()
    """

    # Default TTLs (seconds)
    CACHE_TTL_CPCB: float = 3600.0       # 1 hour
    CACHE_TTL_WRIS: float = 21600.0      # 6 hours
    CACHE_TTL_IMD: float = 1800.0        # 30 minutes
    CACHE_TTL_DATA_GOV: float = 43200.0  # 12 hours

    HTTP_TIMEOUT_SEC: float = 45.0
    HTTP_MAX_RETRIES: int = 3

    def __init__(
        self,
        *,
        data_gov_api_key: str = "",
        cpcb_base_url: str = "https://app.cpcbccr.com/caaqms",
        wris_base_url: str = "https://indiawris.gov.in/wris",
        imd_base_url: str = "https://mausam.imd.gov.in/backend",
        data_gov_base_url: str = "https://api.data.gov.in/resource",
    ) -> None:
        self._data_gov_key = data_gov_api_key
        self._cpcb_url = cpcb_base_url
        self._wris_url = wris_base_url
        self._imd_url = imd_base_url
        self._data_gov_url = data_gov_base_url

        self._cache: dict[str, CacheEntry] = {}
        self._http_client: httpx.AsyncClient | None = None
        self._running = False

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.HTTP_TIMEOUT_SEC),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={"User-Agent": "JalNetra/1.0 (Water Quality Monitor)"},
        )
        logger.info("Data ingestion service started")

    async def stop(self) -> None:
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Data ingestion service stopped")

    # -- CPCB: Real-Time Water Quality --------------------------------------

    async def fetch_cpcb_water_quality(
        self,
        *,
        state: str | None = None,
        station_id: str | None = None,
    ) -> list[WaterQualityRecord]:
        """Fetch real-time water quality data from CPCB monitoring stations.

        CPCB has ~1800 stations across India providing pH, DO, BOD, COD,
        conductivity, temperature, and coliform counts.
        """
        cache_key = f"cpcb:water:{state or 'all'}:{station_id or 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # CPCB CAAQMS API endpoint for water quality
        url = f"{self._cpcb_url}/station_list_all"
        params: dict[str, str] = {}
        if state:
            params["state"] = state

        data = await self._fetch_json(url, params=params)
        if not data:
            return self._get_cached(cache_key, ignore_ttl=True) or []

        records: list[WaterQualityRecord] = []
        stations = data if isinstance(data, list) else data.get("stations", [])

        for station in stations:
            if station_id and station.get("station_id") != station_id:
                continue

            try:
                record = WaterQualityRecord(
                    station_id=str(station.get("station_id", "")),
                    station_name=str(station.get("station_name", "")),
                    state=str(station.get("state", state or "")),
                    latitude=_safe_float(station.get("latitude")),
                    longitude=_safe_float(station.get("longitude")),
                    timestamp=str(station.get("last_update", "")),
                    ph=_safe_float(station.get("ph")),
                    dissolved_oxygen_mg_l=_safe_float(station.get("do")),
                    bod_mg_l=_safe_float(station.get("bod")),
                    cod_mg_l=_safe_float(station.get("cod")),
                    tds_ppm=_safe_float(station.get("tds")),
                    conductivity_umhos=_safe_float(station.get("conductivity")),
                    turbidity_ntu=_safe_float(station.get("turbidity")),
                    total_coliform=_safe_float(station.get("total_coliform")),
                    fecal_coliform=_safe_float(station.get("fecal_coliform")),
                    temperature_c=_safe_float(station.get("temperature")),
                    source="CPCB",
                )
                records.append(record)
            except Exception:
                logger.debug("Skipping malformed CPCB station record: %s", station)

        self._set_cache(cache_key, records, self.CACHE_TTL_CPCB)
        logger.info("Fetched %d CPCB water quality records (state=%s)", len(records), state)
        return records

    # -- India-WRIS: Groundwater Levels ------------------------------------

    async def fetch_india_wris_groundwater(
        self,
        *,
        state: str | None = None,
        district: str | None = None,
    ) -> list[GroundwaterRecord]:
        """Fetch groundwater level data from India-WRIS.

        Provides well monitoring data: water level (meters below ground level),
        well depth, well type, and location.
        """
        cache_key = f"wris:gw:{state or 'all'}:{district or 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self._wris_url}/api/groundwater/wells"
        params: dict[str, str] = {}
        if state:
            params["state"] = state
        if district:
            params["district"] = district

        data = await self._fetch_json(url, params=params)
        if not data:
            return self._get_cached(cache_key, ignore_ttl=True) or []

        records: list[GroundwaterRecord] = []
        wells = data if isinstance(data, list) else data.get("wells", data.get("data", []))

        for well in wells:
            try:
                record = GroundwaterRecord(
                    well_id=str(well.get("well_id", well.get("id", ""))),
                    well_name=str(well.get("well_name", well.get("name", ""))),
                    state=str(well.get("state", state or "")),
                    district=str(well.get("district", district or "")),
                    latitude=_safe_float(well.get("latitude", well.get("lat"))),
                    longitude=_safe_float(well.get("longitude", well.get("lng"))),
                    timestamp=str(well.get("observation_date", well.get("date", ""))),
                    water_level_mbgl=_safe_float(
                        well.get("water_level", well.get("water_level_mbgl"))
                    ),
                    well_depth_m=_safe_float(
                        well.get("well_depth", well.get("depth"))
                    ),
                    well_type=str(well.get("well_type", well.get("type", ""))),
                    source="India-WRIS",
                )
                records.append(record)
            except Exception:
                logger.debug("Skipping malformed WRIS well record: %s", well)

        self._set_cache(cache_key, records, self.CACHE_TTL_WRIS)
        logger.info(
            "Fetched %d India-WRIS groundwater records (state=%s, district=%s)",
            len(records),
            state,
            district,
        )
        return records

    # -- IMD: Weather Data -------------------------------------------------

    async def fetch_imd_weather(
        self,
        *,
        state: str | None = None,
        station_id: str | None = None,
        forecast: bool = False,
    ) -> list[WeatherRecord]:
        """Fetch weather data from India Meteorological Department.

        Provides temperature, rainfall, humidity, wind, and pressure
        at district-level granularity. Set ``forecast=True`` for
        7-day forecast data instead of current observations.
        """
        endpoint = "forecast" if forecast else "current_weather"
        cache_key = f"imd:{endpoint}:{state or 'all'}:{station_id or 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self._imd_url}/api/{endpoint}"
        params: dict[str, str] = {}
        if state:
            params["state"] = state
        if station_id:
            params["station_id"] = station_id

        data = await self._fetch_json(url, params=params)
        if not data:
            return self._get_cached(cache_key, ignore_ttl=True) or []

        records: list[WeatherRecord] = []
        observations = (
            data if isinstance(data, list) else data.get("observations", data.get("data", []))
        )

        for obs in observations:
            try:
                record = WeatherRecord(
                    station_id=str(obs.get("station_id", obs.get("id", ""))),
                    station_name=str(obs.get("station_name", obs.get("name", ""))),
                    state=str(obs.get("state", state or "")),
                    latitude=_safe_float(obs.get("latitude", obs.get("lat"))),
                    longitude=_safe_float(obs.get("longitude", obs.get("lng"))),
                    timestamp=str(obs.get("date", obs.get("timestamp", ""))),
                    temperature_c=_safe_float(
                        obs.get("temperature", obs.get("temp"))
                    ),
                    temperature_max_c=_safe_float(
                        obs.get("temp_max", obs.get("max_temp"))
                    ),
                    temperature_min_c=_safe_float(
                        obs.get("temp_min", obs.get("min_temp"))
                    ),
                    rainfall_mm=_safe_float(
                        obs.get("rainfall", obs.get("rain_mm"))
                    ),
                    humidity_pct=_safe_float(
                        obs.get("humidity", obs.get("relative_humidity"))
                    ),
                    wind_speed_kmh=_safe_float(
                        obs.get("wind_speed", obs.get("wind_speed_kmh"))
                    ),
                    wind_direction=str(obs.get("wind_direction", obs.get("wind_dir", ""))),
                    pressure_hpa=_safe_float(
                        obs.get("pressure", obs.get("slp"))
                    ),
                    source="IMD",
                )
                records.append(record)
            except Exception:
                logger.debug("Skipping malformed IMD record: %s", obs)

        self._set_cache(cache_key, records, self.CACHE_TTL_IMD)
        logger.info(
            "Fetched %d IMD %s records (state=%s)",
            len(records),
            endpoint,
            state,
        )
        return records

    # -- data.gov.in: Open Datasets ----------------------------------------

    async def fetch_data_gov(
        self,
        *,
        resource_id: str,
        filters: dict[str, str] | None = None,
        limit: int = 100,
        offset: int = 0,
        response_format: str = "json",
    ) -> list[dict[str, Any]]:
        """Fetch datasets from data.gov.in Open Data API.

        Args:
            resource_id: The dataset resource ID from data.gov.in
            filters: Optional field=value filters
            limit: Max records to fetch (API max is typically 1000)
            offset: Pagination offset
            response_format: One of "json", "csv", "xml"
        """
        cache_key = (
            f"datagov:{resource_id}:{response_format}:"
            f"{filters or ''}:{limit}:{offset}"
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self._data_gov_url}/{resource_id}"
        params: dict[str, str] = {
            "api-key": self._data_gov_key,
            "format": response_format,
            "limit": str(limit),
            "offset": str(offset),
        }
        if filters:
            for key, value in filters.items():
                params[f"filters[{key}]"] = value

        if response_format == "json":
            data = await self._fetch_json(url, params=params)
            if not data:
                return self._get_cached(cache_key, ignore_ttl=True) or []
            records = data.get("records", data) if isinstance(data, dict) else data

        elif response_format == "csv":
            text = await self._fetch_text(url, params=params)
            if not text:
                return self._get_cached(cache_key, ignore_ttl=True) or []
            records = _parse_csv(text)

        elif response_format == "xml":
            text = await self._fetch_text(url, params=params)
            if not text:
                return self._get_cached(cache_key, ignore_ttl=True) or []
            records = _parse_xml_to_dicts(text, row_tag="record")

        else:
            logger.error("Unsupported response format: %s", response_format)
            return []

        if not isinstance(records, list):
            records = [records] if records else []

        self._set_cache(cache_key, records, self.CACHE_TTL_DATA_GOV)
        logger.info(
            "Fetched %d records from data.gov.in (resource=%s, format=%s)",
            len(records),
            resource_id,
            response_format,
        )
        return records

    # -- Convenience: fetch all sources for a region -----------------------

    async def fetch_all_for_region(
        self,
        *,
        state: str,
        district: str | None = None,
    ) -> dict[str, Any]:
        """Concurrently fetch water quality, groundwater, and weather for a region.

        Returns a dict with keys ``water_quality``, ``groundwater``, ``weather``.
        """
        tasks = {
            "water_quality": self.fetch_cpcb_water_quality(state=state),
            "groundwater": self.fetch_india_wris_groundwater(
                state=state, district=district
            ),
            "weather": self.fetch_imd_weather(state=state),
            "weather_forecast": self.fetch_imd_weather(state=state, forecast=True),
        }

        results: dict[str, Any] = {}
        gathered = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )
        for key, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                logger.error("Failed to fetch %s for %s: %s", key, state, result)
                results[key] = []
            else:
                results[key] = result

        return results

    # -- Cache management ---------------------------------------------------

    def _get_cached(
        self, key: str, *, ignore_ttl: bool = False
    ) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if not ignore_ttl and entry.is_expired:
            return None
        if ignore_ttl and entry.is_expired:
            logger.info(
                "Using stale cache for %s (age: %.0fs, ttl: %.0fs) -- offline fallback",
                key,
                entry.age_sec,
                entry.ttl_sec,
            )
        return entry.data

    def _set_cache(self, key: str, data: Any, ttl_sec: float) -> None:
        self._cache[key] = CacheEntry(
            data=data,
            fetched_at=time.time(),
            ttl_sec=ttl_sec,
            source=key.split(":")[0],
        )

    def clear_cache(self) -> int:
        """Clear all cached data. Returns the number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def cache_stats(self) -> dict[str, Any]:
        now = time.time()
        total = len(self._cache)
        expired = sum(1 for e in self._cache.values() if e.is_expired)
        by_source: dict[str, int] = {}
        for entry in self._cache.values():
            by_source[entry.source] = by_source.get(entry.source, 0) + 1
        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "by_source": by_source,
        }

    # -- HTTP helpers -------------------------------------------------------

    async def _fetch_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        """Fetch JSON from a URL with retry."""
        resp = await self._http_get_with_retry(url, params=params)
        if resp is None:
            return None
        try:
            return resp.json()
        except Exception:
            logger.warning("Failed to parse JSON response from %s", url)
            return None

    async def _fetch_text(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> str | None:
        """Fetch text content from a URL with retry."""
        resp = await self._http_get_with_retry(url, params=params)
        if resp is None:
            return None
        return resp.text

    async def _http_get_with_retry(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        """HTTP GET with exponential backoff retry."""
        if not self._http_client:
            logger.error("HTTP client not initialized -- call start() first")
            return None

        last_exc: Exception | None = None
        for attempt in range(self.HTTP_MAX_RETRIES):
            try:
                resp = await self._http_client.get(url, params=params)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                wait = min(2 ** attempt * 1.5, 60)
                logger.warning(
                    "GET %s attempt %d/%d failed: %s -- retrying in %.1fs",
                    url,
                    attempt + 1,
                    self.HTTP_MAX_RETRIES,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)

        logger.error(
            "GET %s failed after %d retries: %s",
            url,
            self.HTTP_MAX_RETRIES,
            last_exc,
        )
        return None

    # -- Validation helpers -------------------------------------------------

    @staticmethod
    def validate_water_quality(record: WaterQualityRecord) -> list[str]:
        """Validate a water quality record against BIS IS 10500:2012 limits.

        Returns a list of validation warning strings (empty = all OK).
        """
        warnings: list[str] = []

        if record.ph is not None:
            if not (0.0 <= record.ph <= 14.0):
                warnings.append(f"pH out of instrument range: {record.ph}")
            elif not (6.5 <= record.ph <= 8.5):
                warnings.append(f"pH outside BIS acceptable range: {record.ph}")

        if record.tds_ppm is not None:
            if record.tds_ppm < 0:
                warnings.append(f"Negative TDS: {record.tds_ppm}")
            elif record.tds_ppm > 2000:
                warnings.append(f"TDS exceeds BIS permissible limit: {record.tds_ppm}")

        if record.turbidity_ntu is not None:
            if record.turbidity_ntu < 0:
                warnings.append(f"Negative turbidity: {record.turbidity_ntu}")
            elif record.turbidity_ntu > 5:
                warnings.append(f"Turbidity exceeds BIS limit: {record.turbidity_ntu}")

        if record.dissolved_oxygen_mg_l is not None:
            if record.dissolved_oxygen_mg_l < 0:
                warnings.append(f"Negative DO: {record.dissolved_oxygen_mg_l}")
            elif record.dissolved_oxygen_mg_l < 4:
                warnings.append(
                    f"DO below safe level: {record.dissolved_oxygen_mg_l} mg/L"
                )

        if record.total_coliform is not None and record.total_coliform > 0:
            warnings.append(f"Total coliform detected: {record.total_coliform}")

        if record.fecal_coliform is not None and record.fecal_coliform > 0:
            warnings.append(f"Fecal coliform detected: {record.fecal_coliform}")

        return warnings
