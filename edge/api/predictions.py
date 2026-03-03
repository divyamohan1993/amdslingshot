"""JalNetra Edge Gateway — ML prediction API endpoints.

Routes:
    GET /api/v1/predictions              — List depletion forecasts
    GET /api/v1/predictions/{node_id}    — Per-node 30-day forecast
    GET /api/v1/irrigation               — Irrigation schedule
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.predictions")

router = APIRouter(prefix="/api/v1", tags=["predictions"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PredictionResponse(BaseModel):
    id: int
    node_id: str
    prediction_type: str
    days_to_critical: int | None = None
    trend: str | None = None
    predicted_values: list[float] | str | None = None
    confidence: float | None = None
    created_at: str

    model_config = {"from_attributes": True}


class PredictionListResponse(BaseModel):
    items: list[PredictionResponse]
    count: int


class NodeForecastResponse(BaseModel):
    """30-day depletion forecast for a single node."""

    node_id: str
    prediction_type: str = "depletion"
    days_to_critical: int | None = None
    trend: str | None = None
    predicted_values: list[float] | None = None
    confidence: float | None = None
    created_at: str | None = None
    message: str = ""


class IrrigationScheduleResponse(BaseModel):
    id: int
    node_id: str
    schedule_date: str
    recommended_hours: float | None = None
    crop_type: str | None = None
    water_saved_pct: float | None = None
    created_at: str

    model_config = {"from_attributes": True}


class IrrigationListResponse(BaseModel):
    items: list[IrrigationScheduleResponse]
    count: int


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


# ---------------------------------------------------------------------------
# Endpoints — Predictions
# ---------------------------------------------------------------------------


@router.get("/predictions", response_model=PredictionListResponse)
async def list_predictions(
    node_id: str | None = Query(None, description="Filter by sensor node"),
    prediction_type: str | None = Query(
        None, description="Filter by type (depletion, quality)"
    ),
    limit: int = Query(50, ge=1, le=500),
    database: Database = Depends(_get_db),
) -> PredictionListResponse:
    """List stored depletion / quality forecasts."""
    items = await database.list_predictions(
        node_id=node_id,
        prediction_type=prediction_type,
        limit=limit,
    )
    return PredictionListResponse(items=items, count=len(items))


@router.get("/predictions/{node_id}", response_model=NodeForecastResponse)
async def get_node_forecast(
    node_id: str,
    prediction_type: str = Query(
        "depletion",
        description="Prediction type (depletion or quality)",
    ),
    database: Database = Depends(_get_db),
) -> NodeForecastResponse:
    """Get the latest 30-day forecast for a specific node.

    If no prediction exists yet, the endpoint returns a 404 with guidance.
    In production the inference engine runs automatically on new readings.
    """
    # Verify node exists
    node = await database.get_node(node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found",
        )

    prediction = await database.get_latest_prediction(
        node_id, prediction_type=prediction_type
    )
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No {prediction_type} prediction available for node '{node_id}'. "
                "Predictions are generated after sufficient readings are collected."
            ),
        )

    # Build a human-readable message
    days = prediction.get("days_to_critical")
    trend = prediction.get("trend", "unknown")
    if days is not None and days > 0:
        message = (
            f"Groundwater at this source is projected to reach critical level "
            f"in {days} day(s). Current trend: {trend}."
        )
    elif days == -1 or days is None:
        message = f"Source is safe for the forecast period. Trend: {trend}."
    else:
        message = f"Source may already be at critical level. Trend: {trend}."

    return NodeForecastResponse(
        node_id=node_id,
        prediction_type=prediction.get("prediction_type", prediction_type),
        days_to_critical=days,
        trend=trend,
        predicted_values=prediction.get("predicted_values"),
        confidence=prediction.get("confidence"),
        created_at=prediction.get("created_at"),
        message=message,
    )


# ---------------------------------------------------------------------------
# Endpoints — Irrigation Schedules
# ---------------------------------------------------------------------------


@router.get("/irrigation", response_model=IrrigationListResponse)
async def list_irrigation_schedules(
    node_id: str | None = Query(None, description="Filter by node"),
    from_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=500),
    database: Database = Depends(_get_db),
) -> IrrigationListResponse:
    """List AI-generated irrigation schedules.

    Schedules are produced by the irrigation optimiser model based on
    soil moisture, crop type, weather forecast, and water availability.
    """
    items = await database.list_irrigation_schedules(
        node_id=node_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    return IrrigationListResponse(items=items, count=len(items))
