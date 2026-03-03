"""Async data ingestion from Indian government data sources.

Fetches and normalizes water quality, groundwater, weather, and general
datasets from the following authoritative Indian sources:

  - CPCB (Central Pollution Control Board) -- Real-time water quality monitoring
    https://cpcb.nic.in
  - India-WRIS (Water Resources Information System) -- Groundwater level data
    https://indiawris.gov.in
  - IMD (India Meteorological Department) -- Weather observations and forecasts
    https://mausam.imd.gov.in
  - data.gov.in -- Open Government Data Platform India
    https://data.gov.in

All requests are fully async via httpx with:
  - Per-source TTL caching to respect rate limits
  - Automatic fallback to cached data when offline
  - Data normalization into a unified schema
  - Response format parsing: JSON, CSV, XML
  - Rate limiting to be a respectful API consumer
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from edge.config import settings

logger = structlog.get_logger("jalnetra.data_ingestion")


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------

@dataclass(slots=True)
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
        result = float(value)
        # Filter out NaN and Inf
        if result != result or result == float("inf") or result == float("-inf"):
            return default
        return result
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# API source configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _SourceConfig:
    """Configuration for a single data source."""

    name: str
    base_url: str
    default_ttl_sec: float = 1800.0  # 30 minutes
    rate_limit_interval_sec: float = 10.0  # min seconds between requests
    timeout_sec: float = 30.0


_CPCB_CONFIG = _SourceConfig(
    name="CPCB",
    base_url="https://app.cpcbccr.com/caaqms",
    default_ttl_sec=3600.0,  # 1 hour
    rate_limit_interval_sec=15.0,
    timeout_sec=45.0,
)

_INDIA_WRIS_CONFIG = _SourceConfig(
    name="India-WRIS",
    base_url="https://indiawris.gov.in/wris",
    default_ttl_sec=21600.0,  # 6 hours -- groundwater changes slowly
    rate_limit_interval_sec=10.0,
    timeout_sec=45.0,
)

_IMD_CONFIG = _SourceConfig(
    name="IMD",
    base_url="https://mausam.imd.gov.in/backend",
    default_ttl_sec=1800.0,  # 30 minutes
    rate_limit_interval_sec=10.0,
    timeout_sec=30.0,
)

_DATA_GOV_IN_CONFIG = _SourceConfig(
    name="data.gov.in",
    base_url="https://api.data.gov.in/resource",
    default_ttl_sec=43200.0,  # 12 hours -- mostly static datasets
    rate_limit_interval_sec=5.0,
    timeout_sec=30.0,
)


# ---------------------------------------------------------------------------
# Async Data Ingestion Service
# ---------------------------------------------------------------------------

class AsyncDataIngestion:
    """Fetches and normalizes external data from Indian government APIs.

    Provides a unified interface for fetching water quality, groundwater,
    weather, and general datasets with built-in caching, offline fallback,
    and rate limiting.

    Usage::

        ingestion = AsyncDataIngestion(data_gov_api_key="your-key")
        await ingestion.start()

        water = await ingestion.fetch_cpcb_data(state="Maharashtra")
        gw = await ingestion.fetch_india_wris_data(state="Maharashtra")
        weather = await ingestion.fetch_imd_weather(state="Maharashtra")
        datasets = await ingestion.fetch_data_gov_in(resource_id="abc123")

        await ingestion.stop()
    """

    HTTP_TIMEOUT_SEC: float = 45.0
    HTTP_MAX_RETRIES: int = 3
    RETRY_BASE_SEC: float = 2.0

    def __init__(
        self,
        *,
        data_gov_api_key: str = "",
        cpcb_base_url: str | None = None,
        wris_base_url: str | None = None,
        imd_base_url: str | None = None,
        data_gov_base_url: str | None = None,
        user_agent: str = "JalNetra-EdgeGateway/1.0 (water-quality-monitoring)",
    ) -> None:
        self._data_gov_key = data_gov_api_key
        self._user_agent = user_agent

        # Allow per-instance URL overrides
        self._cpcb_url = cpcb_base_url or _CPCB_CONFIG.base_url
        self._wris_url = wris_base_url or _INDIA_WRIS_CONFIG.base_url
        self._imd_url = imd_base_url or _IMD_CONFIG.base_url
        self._data_gov_url = data_gov_base_url or _DATA_GOV_IN_CONFIG.base_url

        # Response cache keyed by request hash
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = asyncio.Lock()

        # Rate limit tracking: source_name -> last_request_time
        self._last_request_at: dict[str, float] = {}

        # Runtime
        self._http_client: httpx.AsyncClient | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the httpx client."""
        if self._running:
            return
        self._running = True
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.HTTP_TIMEOUT_SEC),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )
        await logger.ainfo("Data ingestion service started")

    async def stop(self) -> None:
        """Close HTTP client."""
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        await logger.ainfo(
            "Data ingestion service stopped",
            cache_entries=len(self._cache),
        )

    # ------------------------------------------------------------------
    # CPCB -- Water Quality from real-time monitoring
    # ------------------------------------------------------------------

    async def fetch_cpcb_data(
        self,
        *,
        state: str | None = None,
        station_id: str | None = None,
    ) -> list[WaterQualityRecord]:
        """Fetch real-time water quality data from CPCB monitoring stations.

        CPCB (https://cpcb.nic.in) operates ~1,800 monitoring stations across
        India under the National Water Quality Monitoring Programme (NWMP),
        providing pH, DO, BOD, COD, TDS, conductivity, temperature, and
        coliform readings.

        Args:
            state: Filter by state name (e.g., "Delhi", "Rajasthan").
            station_id: Specific CPCB station identifier.

        Returns:
            List of normalized water quality records.
        """
        cache_key = self._make_cache_key(
            f"{self._cpcb_url}/station_list_all",
            {"state": state or "all", "station_id": station_id or "all"},
        )
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Rate limit
        await self._rate_limit(_CPCB_CONFIG)

        url = f"{self._cpcb_url}/station_list_all"
        params: dict[str, str] = {}
        if state:
            params["state"] = state

        data = await self._fetch_json(url, params=params)
        if not data:
            return await self._get_cached(cache_key, ignore_ttl=True) or []

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
                await logger.adebug(
                    "Skipping malformed CPCB station record",
                    station=station,
                )

        await self._set_cache(cache_key, records, _CPCB_CONFIG.default_ttl_sec, "CPCB")
        await logger.ainfo(
            "Fetched CPCB water quality data",
            records=len(records),
            state=state,
        )
        return records

    # ------------------------------------------------------------------
    # India-WRIS -- Groundwater levels
    # ------------------------------------------------------------------

    async def fetch_india_wris_data(
        self,
        *,
        state: str | None = None,
        district: str | None = None,
    ) -> list[GroundwaterRecord]:
        """Fetch groundwater level data from India-WRIS.

        India-WRIS (https://indiawris.gov.in) aggregates data from CGWB
        (Central Ground Water Board) and state groundwater departments,
        covering ~25,000 observation wells. Provides water level (metres
        below ground level), well depth, well type, and location.

        Args:
            state: State name filter.
            district: District name filter.

        Returns:
            List of normalized groundwater records.
        """
        cache_key = self._make_cache_key(
            f"{self._wris_url}/api/groundwater/wells",
            {"state": state or "all", "district": district or "all"},
        )
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        await self._rate_limit(_INDIA_WRIS_CONFIG)

        url = f"{self._wris_url}/api/groundwater/wells"
        params: dict[str, str] = {}
        if state:
            params["state"] = state
        if district:
            params["district"] = district

        data = await self._fetch_json(url, params=params)
        if not data:
            return await self._get_cached(cache_key, ignore_ttl=True) or []

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
                await logger.adebug(
                    "Skipping malformed WRIS well record", well=well
                )

        await self._set_cache(
            cache_key, records, _INDIA_WRIS_CONFIG.default_ttl_sec, "India-WRIS"
        )
        await logger.ainfo(
            "Fetched India-WRIS groundwater data",
            records=len(records),
            state=state,
            district=district,
        )
        return records

    # ------------------------------------------------------------------
    # IMD -- Weather
    # ------------------------------------------------------------------

    async def fetch_imd_weather(
        self,
        *,
        state: str | None = None,
        station_id: str | None = None,
        forecast: bool = False,
    ) -> list[WeatherRecord]:
        """Fetch weather data from India Meteorological Department.

        IMD (https://mausam.imd.gov.in) provides temperature, rainfall,
        humidity, wind, and pressure at district-level granularity from
        ~600 surface stations. Set ``forecast=True`` for 7-day forecast
        data instead of current observations.

        Args:
            state: Filter by state name.
            station_id: Specific IMD station identifier.
            forecast: If True, fetch forecast data instead of current.

        Returns:
            List of normalized weather records.
        """
        endpoint = "forecast" if forecast else "current_weather"
        cache_key = self._make_cache_key(
            f"{self._imd_url}/api/{endpoint}",
            {"state": state or "all", "station_id": station_id or "all"},
        )
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        await self._rate_limit(_IMD_CONFIG)

        url = f"{self._imd_url}/api/{endpoint}"
        params: dict[str, str] = {}
        if state:
            params["state"] = state
        if station_id:
            params["station_id"] = station_id

        data = await self._fetch_json(url, params=params)
        if not data:
            return await self._get_cached(cache_key, ignore_ttl=True) or []

        records: list[WeatherRecord] = []
        observations = (
            data if isinstance(data, list)
            else data.get("observations", data.get("data", []))
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
                    temperature_c=_safe_float(obs.get("temperature", obs.get("temp"))),
                    temperature_max_c=_safe_float(obs.get("temp_max", obs.get("max_temp"))),
                    temperature_min_c=_safe_float(obs.get("temp_min", obs.get("min_temp"))),
                    rainfall_mm=_safe_float(obs.get("rainfall", obs.get("rain_mm"))),
                    humidity_pct=_safe_float(
                        obs.get("humidity", obs.get("relative_humidity"))
                    ),
                    wind_speed_kmh=_safe_float(
                        obs.get("wind_speed", obs.get("wind_speed_kmh"))
                    ),
                    wind_direction=str(obs.get("wind_direction", obs.get("wind_dir", ""))),
                    pressure_hpa=_safe_float(obs.get("pressure", obs.get("slp"))),
                    source="IMD",
                )
                records.append(record)
            except Exception:
                await logger.adebug("Skipping malformed IMD record", obs=obs)

        await self._set_cache(
            cache_key, records, _IMD_CONFIG.default_ttl_sec, "IMD"
        )
        await logger.ainfo(
            "Fetched IMD weather data",
            records=len(records),
            endpoint=endpoint,
            state=state,
        )
        return records

    # ------------------------------------------------------------------
    # data.gov.in -- Open Government Data
    # ------------------------------------------------------------------

    async def fetch_data_gov_in(
        self,
        *,
        resource_id: str,
        filters: dict[str, str] | None = None,
        limit: int = 100,
        offset: int = 0,
        response_format: str = "json",
    ) -> list[dict[str, Any]]:
        """Fetch datasets from the data.gov.in Open Data API.

        data.gov.in hosts 600,000+ datasets across ministries. Relevant
        resources for JalNetra include water quality reports, groundwater
        assessments, rainfall records, and Jal Jeevan Mission progress data.

        Args:
            resource_id: The dataset resource UUID from data.gov.in.
            filters: Optional field=value filters.
            limit: Max records to fetch (API max is typically 1000).
            offset: Pagination offset.
            response_format: One of "json", "csv", "xml".

        Returns:
            List of dataset records as dictionaries.
        """
        cache_key = self._make_cache_key(
            f"{self._data_gov_url}/{resource_id}",
            {
                "format": response_format,
                "filters": str(filters or ""),
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        await self._rate_limit(_DATA_GOV_IN_CONFIG)

        url = f"{self._data_gov_url}/{resource_id}"
        params: dict[str, str] = {
            "api-key": self._data_gov_key,
            "format": response_format,
            "limit": str(min(limit, 1000)),
            "offset": str(offset),
        }
        if filters:
            for key, value in filters.items():
                params[f"filters[{key}]"] = value

        records: list[dict[str, Any]]

        if response_format == "json":
            data = await self._fetch_json(url, params=params)
            if not data:
                return await self._get_cached(cache_key, ignore_ttl=True) or []
            records = data.get("records", data) if isinstance(data, dict) else data

        elif response_format == "csv":
            text = await self._fetch_text(url, params=params)
            if not text:
                return await self._get_cached(cache_key, ignore_ttl=True) or []
            records = _parse_csv(text)

        elif response_format == "xml":
            text = await self._fetch_text(url, params=params)
            if not text:
                return await self._get_cached(cache_key, ignore_ttl=True) or []
            records = _parse_xml_to_dicts(text, row_tag="record")

        else:
            await logger.aerror("Unsupported response format", format=response_format)
            return []

        if not isinstance(records, list):
            records = [records] if records else []

        await self._set_cache(
            cache_key, records, _DATA_GOV_IN_CONFIG.default_ttl_sec, "data.gov.in"
        )
        await logger.ainfo(
            "Fetched data.gov.in dataset",
            records=len(records),
            resource_id=resource_id,
            format=response_format,
        )
        return records

    # ------------------------------------------------------------------
    # Convenience: fetch all sources for a region
    # ------------------------------------------------------------------

    async def fetch_all_for_region(
        self,
        *,
        state: str,
        district: str | None = None,
    ) -> dict[str, Any]:
        """Concurrently fetch water quality, groundwater, and weather for a region.

        Returns a dict with keys ``water_quality``, ``groundwater``,
        ``weather``, and ``weather_forecast``.
        """
        tasks = {
            "water_quality": self.fetch_cpcb_data(state=state),
            "groundwater": self.fetch_india_wris_data(
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
                await logger.aerror(
                    "Failed to fetch data source",
                    source=key,
                    state=state,
                    error=str(result),
                )
                results[key] = []
            else:
                results[key] = result

        return results

    # ------------------------------------------------------------------
    # Cache management (async-safe)
    # ------------------------------------------------------------------

    async def _get_cached(
        self, key: str, *, ignore_ttl: bool = False
    ) -> Any | None:
        """Get from cache. Returns None if not found or expired."""
        async with self._cache_lock:
            entry = self._cache.get(key)
        if entry is None:
            return None
        if not ignore_ttl and entry.is_expired:
            return None
        if ignore_ttl and entry.is_expired:
            await logger.ainfo(
                "Using stale cache (offline fallback)",
                source=entry.source,
                age_sec=round(entry.age_sec, 1),
                ttl_sec=entry.ttl_sec,
            )
        return entry.data

    async def _set_cache(
        self, key: str, data: Any, ttl_sec: float, source: str
    ) -> None:
        """Store data in cache with TTL."""
        async with self._cache_lock:
            self._cache[key] = CacheEntry(
                data=data,
                fetched_at=time.time(),
                ttl_sec=ttl_sec,
                source=source,
            )

    async def clear_cache(self, source: str | None = None) -> int:
        """Clear cached entries, optionally filtered by source.

        Returns the number of entries cleared.
        """
        async with self._cache_lock:
            if source is None:
                count = len(self._cache)
                self._cache.clear()
                return count
            keys_to_remove = [
                k for k, v in self._cache.items() if v.source == source
            ]
            for key in keys_to_remove:
                del self._cache[key]
            return len(keys_to_remove)

    @property
    def cache_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
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

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self, source_config: _SourceConfig) -> None:
        """Ensure minimum interval between requests to a source."""
        now = time.time()
        last = self._last_request_at.get(source_config.name, 0.0)
        elapsed = now - last

        if elapsed < source_config.rate_limit_interval_sec:
            wait = source_config.rate_limit_interval_sec - elapsed
            await asyncio.sleep(wait)

        self._last_request_at[source_config.name] = time.time()

    # ------------------------------------------------------------------
    # HTTP helpers with retry
    # ------------------------------------------------------------------

    async def _fetch_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        """Fetch JSON from a URL with retry and error handling."""
        resp = await self._http_get_with_retry(url, params=params)
        if resp is None:
            return None
        try:
            return resp.json()
        except Exception:
            await logger.awarning("Failed to parse JSON response", url=url)
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
            await logger.aerror("HTTP client not initialized -- call start() first")
            return None

        last_exc: Exception | None = None
        for attempt in range(1, self.HTTP_MAX_RETRIES + 1):
            try:
                resp = await self._http_client.get(url, params=params)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                if attempt < self.HTTP_MAX_RETRIES:
                    wait = min(self.RETRY_BASE_SEC * (2 ** (attempt - 1)), 60.0)
                    await logger.awarning(
                        "HTTP GET failed, retrying",
                        url=url,
                        attempt=attempt,
                        max_retries=self.HTTP_MAX_RETRIES,
                        wait_sec=wait,
                        error=str(exc),
                    )
                    await asyncio.sleep(wait)

        await logger.aerror(
            "HTTP GET failed after all retries",
            url=url,
            retries=self.HTTP_MAX_RETRIES,
            error=str(last_exc),
        )
        return None

    # ------------------------------------------------------------------
    # Cache key generation
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cache_key(url: str, params: dict[str, str]) -> str:
        """Generate a deterministic cache key from URL + params."""
        raw = f"{url}|{sorted(params.items())}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

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
