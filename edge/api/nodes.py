"""JalNetra Edge Gateway — Sensor node management API endpoints.

Routes:
    GET  /api/v1/nodes                   — List all sensor nodes
    GET  /api/v1/nodes/{node_id}         — Node details + latest reading
    POST /api/v1/nodes                   — Register a new sensor node
    PUT  /api/v1/nodes/{node_id}         — Update node configuration
    GET  /api/v1/nodes/{node_id}/health  — Node health status
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from edge.config import SourceType
from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.nodes")

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class NodeCreate(BaseModel):
    """Register a new sensor node."""

    id: str = Field(..., min_length=1, description="Unique node identifier (e.g. JN-DL-001-BW1)")
    village_id: str = Field(..., min_length=1)
    location_name: str = Field(..., min_length=1, description="Human-readable location")
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    source_type: SourceType | None = Field(
        None,
        description="Water source type (borewell, handpump, canal, reservoir, tap)",
    )
    status: str = Field(default="active")


class NodeUpdate(BaseModel):
    """Update fields on an existing sensor node."""

    village_id: str | None = None
    location_name: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    source_type: SourceType | None = None
    status: str | None = Field(None, pattern="^(active|inactive|maintenance)$")


class NodeResponse(BaseModel):
    id: str
    village_id: str
    location_name: str
    latitude: float | None = None
    longitude: float | None = None
    source_type: str | None = None
    installed_at: str
    last_seen_at: str | None = None
    battery_voltage: float | None = None
    status: str

    model_config = {"from_attributes": True}


class NodeDetailResponse(BaseModel):
    """Node details enriched with the latest reading."""

    node: NodeResponse
    latest_reading: dict[str, Any] | None = None
    reading_count: int = 0


class NodeHealthResponse(BaseModel):
    """Health assessment of a single sensor node."""

    node_id: str
    status: str
    battery_voltage: float | None = None
    battery_status: str = "unknown"
    last_seen_at: str | None = None
    seconds_since_last_seen: int | None = None
    connectivity: str = "unknown"
    reading_count_24h: int = 0
    alert_count_24h: int = 0


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[NodeResponse])
async def list_nodes(
    status_filter: str | None = Query(
        None, alias="status", description="Filter by node status"
    ),
    village_id: str | None = Query(None, description="Filter by village"),
    database: Database = Depends(_get_db),
) -> list[dict[str, Any]]:
    """List all registered sensor nodes with optional filtering."""
    return await database.list_nodes(status=status_filter, village_id=village_id)


@router.get("/{node_id}", response_model=NodeDetailResponse)
async def get_node(
    node_id: str,
    database: Database = Depends(_get_db),
) -> NodeDetailResponse:
    """Get a node's details together with its latest reading."""
    node = await database.get_node(node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found",
        )

    # Fetch latest reading for this node
    readings = await database.list_readings(node_id=node_id, limit=1)
    latest = readings[0] if readings else None
    count = await database.count_readings(node_id=node_id)

    return NodeDetailResponse(
        node=node,
        latest_reading=latest,
        reading_count=count,
    )


@router.post("", response_model=NodeResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    payload: NodeCreate,
    database: Database = Depends(_get_db),
) -> dict[str, Any]:
    """Register a new sensor node.

    If a node with the same ID already exists, its record will be
    updated (upsert behaviour).
    """
    result = await database.upsert_node(
        node_id=payload.id,
        village_id=payload.village_id,
        location_name=payload.location_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        source_type=payload.source_type.value if payload.source_type else None,
        status=payload.status,
    )
    return result


@router.put("/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: str,
    payload: NodeUpdate,
    database: Database = Depends(_get_db),
) -> dict[str, Any]:
    """Update an existing sensor node's configuration."""
    existing = await database.get_node(node_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found",
        )

    update_fields = payload.model_dump(exclude_unset=True)
    if "source_type" in update_fields and update_fields["source_type"] is not None:
        update_fields["source_type"] = update_fields["source_type"].value

    result = await database.update_node(node_id, **update_fields)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update node",
        )
    return result


@router.get("/{node_id}/health", response_model=NodeHealthResponse)
async def get_node_health(
    node_id: str,
    database: Database = Depends(_get_db),
) -> NodeHealthResponse:
    """Assess the health status of a sensor node.

    Checks battery level, last-seen recency, and 24h reading/alert counts.
    """
    node = await database.get_node(node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found",
        )

    now = datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Compute seconds since last seen
    seconds_since: int | None = None
    connectivity = "unknown"
    last_seen = node.get("last_seen_at")
    if last_seen:
        try:
            last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            seconds_since = int((now - last_dt).total_seconds())
            if seconds_since < 120:
                connectivity = "online"
            elif seconds_since < 600:
                connectivity = "intermittent"
            else:
                connectivity = "offline"
        except (ValueError, TypeError):
            pass

    # Battery assessment
    batt = node.get("battery_voltage")
    if batt is not None:
        if batt >= 3.6:
            battery_status = "good"
        elif batt >= 3.3:
            battery_status = "low"
        else:
            battery_status = "critical"
    else:
        battery_status = "unknown"

    reading_count = await database.count_readings(node_id=node_id, since=since_24h)

    # Alert count in last 24h
    alerts = await database.list_alerts(node_id=node_id, limit=100_000, offset=0)
    alert_count = sum(
        1 for a in alerts
        if a.get("created_at", "") >= since_24h
    )

    return NodeHealthResponse(
        node_id=node_id,
        status=node.get("status", "unknown"),
        battery_voltage=batt,
        battery_status=battery_status,
        last_seen_at=last_seen,
        seconds_since_last_seen=seconds_since,
        connectivity=connectivity,
        reading_count_24h=reading_count,
        alert_count_24h=alert_count,
    )
