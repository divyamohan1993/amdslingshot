"""JalNetra Edge Gateway — Sensor readings API endpoints.

Routes:
    GET  /api/v1/readings           — List readings with pagination + filtering
    GET  /api/v1/readings/latest    — Latest reading from every node
    GET  /api/v1/readings/{id}      — Single reading by ID
    POST /api/v1/readings           — Ingest a new reading (triggers inference)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from edge.config import BIS_THRESHOLDS, AlertSeverity, settings
from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.readings")

router = APIRouter(prefix="/api/v1/readings", tags=["readings"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ReadingCreate(BaseModel):
    """Payload for ingesting a new sensor reading."""

    node_id: str = Field(..., min_length=1, description="Sensor node identifier")
    tds: float | None = Field(None, ge=0, description="Total dissolved solids (ppm)")
    ph: float | None = Field(None, ge=0, le=14, description="pH value")
    turbidity: float | None = Field(None, ge=0, description="Turbidity (NTU)")
    flow_rate: float | None = Field(None, ge=0, description="Flow rate (L/min)")
    water_level: float | None = Field(None, description="Water level (metres)")
    battery_voltage: float | None = Field(None, ge=0, description="Battery voltage (V)")
    timestamp: str | None = Field(
        None,
        description="ISO-8601 timestamp; defaults to server UTC now",
    )


class ReadingResponse(BaseModel):
    """Serialised sensor reading."""

    id: int
    node_id: str
    tds: float | None = None
    ph: float | None = None
    turbidity: float | None = None
    flow_rate: float | None = None
    water_level: float | None = None
    battery_voltage: float | None = None
    timestamp: str
    synced: int = 0
    created_at: str

    model_config = {"from_attributes": True}


class ReadingListResponse(BaseModel):
    """Paginated list of readings."""

    items: list[ReadingResponse]
    total: int
    limit: int
    offset: int


class ReadingIngestResponse(BaseModel):
    """Response after ingesting a reading (includes optional inference)."""

    reading: ReadingResponse
    inference: dict[str, Any] | None = None
    alerts_triggered: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


# ---------------------------------------------------------------------------
# Threshold evaluation helpers
# ---------------------------------------------------------------------------


def _evaluate_thresholds(reading: dict[str, Any]) -> list[dict[str, Any]]:
    """Check a reading against BIS IS 10500:2012 thresholds.

    Returns a list of alert dicts (may be empty if everything is safe).
    """
    alerts: list[dict[str, Any]] = []
    th = BIS_THRESHOLDS

    # TDS
    tds = reading.get("tds")
    if tds is not None:
        if th.tds.critical_max is not None and tds > th.tds.critical_max:
            alerts.append({
                "alert_type": "tds_critical",
                "severity": AlertSeverity.CRITICAL,
                "message": f"TDS critically high: {tds} ppm (limit {th.tds.critical_max} {th.tds.unit})",
            })
        elif th.tds.alert_max is not None and tds > th.tds.alert_max:
            alerts.append({
                "alert_type": "tds_warning",
                "severity": AlertSeverity.WARNING,
                "message": f"TDS above acceptable limit: {tds} ppm (limit {th.tds.acceptable_max} {th.tds.unit})",
            })

    # pH
    ph = reading.get("ph")
    if ph is not None:
        if (th.ph.critical_min is not None and ph < th.ph.critical_min) or (
            th.ph.critical_max is not None and ph > th.ph.critical_max
        ):
            alerts.append({
                "alert_type": "ph_critical",
                "severity": AlertSeverity.CRITICAL,
                "message": f"pH critically out of range: {ph} (safe range {th.ph.acceptable_min}-{th.ph.acceptable_max})",
            })
        elif (th.ph.alert_min is not None and ph < th.ph.alert_min) or (
            th.ph.alert_max is not None and ph > th.ph.alert_max
        ):
            alerts.append({
                "alert_type": "ph_warning",
                "severity": AlertSeverity.WARNING,
                "message": f"pH out of acceptable range: {ph} (safe range {th.ph.acceptable_min}-{th.ph.acceptable_max})",
            })

    # Turbidity
    turb = reading.get("turbidity")
    if turb is not None:
        if th.turbidity.critical_max is not None and turb > th.turbidity.critical_max:
            alerts.append({
                "alert_type": "turbidity_critical",
                "severity": AlertSeverity.CRITICAL,
                "message": f"Turbidity critically high: {turb} NTU (limit {th.turbidity.critical_max} {th.turbidity.unit})",
            })
        elif th.turbidity.alert_max is not None and turb > th.turbidity.alert_max:
            alerts.append({
                "alert_type": "turbidity_warning",
                "severity": AlertSeverity.WARNING,
                "message": f"Turbidity above acceptable limit: {turb} NTU (limit {th.turbidity.acceptable_max} {th.turbidity.unit})",
            })

    # Water level (depletion risk)
    level = reading.get("water_level")
    if level is not None and level < settings.groundwater_critical_level_m:
        alerts.append({
            "alert_type": "water_level_critical",
            "severity": AlertSeverity.CRITICAL,
            "message": (
                f"Water level critically low: {level} m "
                f"(threshold {settings.groundwater_critical_level_m} m)"
            ),
        })

    return alerts


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ReadingListResponse)
async def list_readings(
    node_id: str | None = Query(None, description="Filter by sensor node"),
    since: str | None = Query(None, description="Start timestamp (ISO-8601)"),
    until: str | None = Query(None, description="End timestamp (ISO-8601)"),
    limit: int = Query(100, ge=1, le=1000, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    database: Database = Depends(_get_db),
) -> ReadingListResponse:
    """List sensor readings with pagination and optional filters."""
    items = await database.list_readings(
        node_id=node_id, since=since, until=until, limit=limit, offset=offset,
    )
    total = await database.count_readings(node_id=node_id, since=since)
    return ReadingListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/latest", response_model=list[ReadingResponse])
async def get_latest_readings(
    database: Database = Depends(_get_db),
) -> list[dict[str, Any]]:
    """Get the most recent reading from every active sensor node."""
    return await database.get_latest_readings()


@router.get("/{reading_id}", response_model=ReadingResponse)
async def get_reading(
    reading_id: int,
    database: Database = Depends(_get_db),
) -> dict[str, Any]:
    """Retrieve a single reading by its ID."""
    reading = await database.get_reading(reading_id)
    if reading is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reading {reading_id} not found",
        )
    return reading


@router.post(
    "",
    response_model=ReadingIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_reading(
    payload: ReadingCreate,
    database: Database = Depends(_get_db),
) -> ReadingIngestResponse:
    """Ingest a new sensor reading.

    After storage the reading is evaluated against BIS IS 10500:2012
    thresholds.  If any parameter breaches a threshold, alerts are
    created automatically.  In production, ONNX inference (anomaly
    detection) would also run here.
    """
    # Verify node exists
    node = await database.get_node(payload.node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sensor node '{payload.node_id}' not registered",
        )

    # Store the reading
    reading = await database.insert_reading(
        node_id=payload.node_id,
        tds=payload.tds,
        ph=payload.ph,
        turbidity=payload.turbidity,
        flow_rate=payload.flow_rate,
        water_level=payload.water_level,
        battery_voltage=payload.battery_voltage,
        timestamp=payload.timestamp,
    )

    # -- Threshold-based alert evaluation --
    triggered_alerts: list[dict[str, Any]] = []
    threshold_alerts = _evaluate_thresholds(reading)
    for alert_info in threshold_alerts:
        stored_alert = await database.insert_alert(
            node_id=payload.node_id,
            alert_type=alert_info["alert_type"],
            severity=alert_info["severity"],
            message=alert_info["message"],
            reading_id=reading["id"],
        )
        triggered_alerts.append(stored_alert)

    # -- ML inference placeholder --
    inference_result: dict[str, Any] | None = None
    # In production:
    #   from edge.main import _state
    #   if _state.models_loaded:
    #       features = build_feature_vector(reading)
    #       inference_result = engine.detect_anomaly(features)

    # -- Broadcast to WebSocket clients --
    try:
        from edge.main import broadcast_reading, broadcast_alert

        await broadcast_reading(payload.node_id, reading)
        for alert in triggered_alerts:
            await broadcast_alert(
                payload.node_id,
                alert.get("severity", "info"),
                alert.get("message", ""),
            )
    except Exception:
        logger.debug("WebSocket broadcast skipped (not running in app context)")

    return ReadingIngestResponse(
        reading=reading,
        inference=inference_result,
        alerts_triggered=triggered_alerts,
    )
