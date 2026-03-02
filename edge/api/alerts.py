"""JalNetra Edge Gateway — Alert management API endpoints.

Routes:
    GET  /api/v1/alerts                    — List alerts (filterable by severity, node, ack status)
    GET  /api/v1/alerts/stats              — Aggregated alert statistics
    POST /api/v1/alerts/{alert_id}/acknowledge — Acknowledge an alert
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.alerts")

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AlertResponse(BaseModel):
    id: int
    node_id: str
    alert_type: str
    severity: str
    message: str
    confidence: float | None = None
    reading_id: int | None = None
    acknowledged: int = 0
    acknowledged_at: str | None = None
    acknowledged_by: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    limit: int
    offset: int


class AlertStatsResponse(BaseModel):
    total: int = 0
    critical: int = 0
    warning: int = 0
    info: int = 0
    acknowledged: int = 0
    unacknowledged: int = 0


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str = Field(
        default="operator",
        min_length=1,
        description="User or system that acknowledged the alert",
    )


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    node_id: str | None = Query(None, description="Filter by sensor node"),
    severity: str | None = Query(
        None,
        description="Filter by severity (info, warning, critical)",
        pattern="^(info|warning|critical)$",
    ),
    acknowledged: bool | None = Query(None, description="Filter by acknowledgement status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    database: Database = Depends(_get_db),
) -> AlertListResponse:
    """List alerts with optional filtering by severity, node, and acknowledgement status."""
    items = await database.list_alerts(
        node_id=node_id,
        severity=severity,
        acknowledged=acknowledged,
        limit=limit,
        offset=offset,
    )
    # Get total count for pagination metadata
    all_items = await database.list_alerts(
        node_id=node_id,
        severity=severity,
        acknowledged=acknowledged,
        limit=100_000,
        offset=0,
    )
    return AlertListResponse(
        items=items,
        total=len(all_items),
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=AlertStatsResponse)
async def get_alert_stats(
    node_id: str | None = Query(None, description="Filter stats by node"),
    since: str | None = Query(None, description="Start timestamp (ISO-8601)"),
    database: Database = Depends(_get_db),
) -> AlertStatsResponse:
    """Get aggregated alert statistics across all nodes or for a specific node."""
    raw = await database.get_alert_stats(node_id=node_id, since=since)
    return AlertStatsResponse(
        total=raw.get("total", 0) or 0,
        critical=raw.get("critical", 0) or 0,
        warning=raw.get("warning", 0) or 0,
        info=raw.get("info", 0) or 0,
        acknowledged=raw.get("acknowledged", 0) or 0,
        unacknowledged=raw.get("unacknowledged", 0) or 0,
    )


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertResponse,
)
async def acknowledge_alert(
    alert_id: int,
    body: AcknowledgeRequest | None = None,
    database: Database = Depends(_get_db),
) -> dict[str, Any]:
    """Acknowledge an alert by its ID.

    Once acknowledged the alert will no longer appear in unacknowledged
    filters and will not trigger repeat notifications.
    """
    existing = await database.get_alert(alert_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found",
        )
    if existing.get("acknowledged"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} already acknowledged",
        )
    ack_by = body.acknowledged_by if body else "operator"
    result = await database.acknowledge_alert(alert_id, acknowledged_by=ack_by)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to acknowledge alert",
        )
    return result
