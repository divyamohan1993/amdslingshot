"""JalNetra Edge Gateway — System health API endpoints.

Routes:
    GET /api/v1/health        — Full system health check
    GET /api/v1/health/models — ML model status
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from edge.config import settings
from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.health")

router = APIRouter(prefix="/api/v1/health", tags=["health"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ComponentHealth(BaseModel):
    name: str
    status: str  # "ok", "degraded", "down"
    message: str = ""
    latency_ms: float | None = None


class SystemHealthResponse(BaseModel):
    status: str  # "ok", "degraded", "down"
    version: str
    gateway_id: str
    uptime_seconds: int
    timestamp: str
    components: list[ComponentHealth]


class ModelInfo(BaseModel):
    name: str
    file: str
    path: str
    exists: bool
    size_mb: float | None = None
    loaded: bool = False


class ModelHealthResponse(BaseModel):
    status: str
    model_dir: str
    models: list[ModelInfo]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


def _get_startup_time() -> datetime:
    try:
        from edge.main import _state
        return _state.startup_time
    except Exception:
        return datetime.now(timezone.utc)


def _get_models_loaded() -> bool:
    try:
        from edge.main import _state
        return _state.models_loaded
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Health-check helpers
# ---------------------------------------------------------------------------


async def _check_database(database: Database) -> ComponentHealth:
    """Verify the database is reachable and responsive."""
    start = time.monotonic()
    try:
        async with database.acquire() as conn:
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()
        elapsed = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="database",
            status="ok",
            message=f"SQLite WAL mode, path={settings.jalnetra_db_path}",
            latency_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="database",
            status="down",
            message=str(exc),
            latency_ms=round(elapsed, 2),
        )


def _check_models() -> ComponentHealth:
    """Check whether ONNX model files are present on disk."""
    model_dir = settings.jalnetra_model_dir
    if not model_dir.exists():
        return ComponentHealth(
            name="ml_models",
            status="down",
            message=f"Model directory not found: {model_dir}",
        )

    expected = [
        settings.anomaly_model_file,
        settings.depletion_model_file,
        settings.irrigation_model_file,
    ]
    found = sum(1 for f in expected if (model_dir / f).exists())
    if found == len(expected):
        loaded = _get_models_loaded()
        return ComponentHealth(
            name="ml_models",
            status="ok" if loaded else "degraded",
            message=f"{found}/{len(expected)} models on disk, loaded={loaded}",
        )
    return ComponentHealth(
        name="ml_models",
        status="degraded",
        message=f"Only {found}/{len(expected)} model files found in {model_dir}",
    )


def _check_lora() -> ComponentHealth:
    """Check LoRa serial port availability."""
    port_path = Path(settings.jalnetra_lora_port)
    if port_path.exists():
        return ComponentHealth(
            name="lora_receiver",
            status="ok",
            message=f"Serial port available: {settings.jalnetra_lora_port}",
        )
    return ComponentHealth(
        name="lora_receiver",
        status="degraded",
        message=f"Serial port not found: {settings.jalnetra_lora_port}",
    )


async def _check_cloud() -> ComponentHealth:
    """Lightweight connectivity check to the cloud sync endpoint."""
    try:
        import httpx  # noqa: F811

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.head(settings.cloud_sync_url)
        elapsed = (time.monotonic() - start) * 1000
        reachable = resp.status_code < 500
        return ComponentHealth(
            name="cloud_sync",
            status="ok" if reachable else "degraded",
            message=f"HTTP {resp.status_code} in {elapsed:.0f}ms",
            latency_ms=round(elapsed, 2),
        )
    except ImportError:
        return ComponentHealth(
            name="cloud_sync",
            status="degraded",
            message="httpx not installed — cannot verify cloud connectivity",
        )
    except Exception as exc:
        return ComponentHealth(
            name="cloud_sync",
            status="down",
            message=f"Unreachable: {exc}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=SystemHealthResponse)
async def system_health(
    database: Database = Depends(_get_db),
) -> SystemHealthResponse:
    """Full system health check covering DB, models, LoRa, and cloud."""
    now = datetime.now(timezone.utc)
    startup = _get_startup_time()
    uptime = int((now - startup).total_seconds())

    # Run independent checks concurrently
    db_check, cloud_check = await asyncio.gather(
        _check_database(database),
        _check_cloud(),
    )
    model_check = _check_models()
    lora_check = _check_lora()

    components = [db_check, model_check, lora_check, cloud_check]

    # Overall status: worst of all components
    statuses = [c.status for c in components]
    if "down" in statuses:
        overall = "down"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return SystemHealthResponse(
        status=overall,
        version=settings.version,
        gateway_id=settings.jalnetra_node_id,
        uptime_seconds=uptime,
        timestamp=now.isoformat(),
        components=components,
    )


@router.get("/models", response_model=ModelHealthResponse)
async def model_health() -> ModelHealthResponse:
    """Detailed ML model status: file existence, size, and load state."""
    model_dir = settings.jalnetra_model_dir
    loaded = _get_models_loaded()

    model_specs = [
        ("anomaly_detector", settings.anomaly_model_file),
        ("depletion_predictor", settings.depletion_model_file),
        ("irrigation_optimizer", settings.irrigation_model_file),
    ]

    models: list[ModelInfo] = []
    for name, filename in model_specs:
        path = model_dir / filename
        exists = path.exists()
        size_mb: float | None = None
        if exists:
            size_mb = round(path.stat().st_size / (1024 * 1024), 2)
        models.append(
            ModelInfo(
                name=name,
                file=filename,
                path=str(path),
                exists=exists,
                size_mb=size_mb,
                loaded=loaded and exists,
            )
        )

    all_ok = all(m.exists for m in models) and loaded
    return ModelHealthResponse(
        status="ok" if all_ok else "degraded",
        model_dir=str(model_dir),
        models=models,
    )
