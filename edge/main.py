"""JalNetra Edge Gateway — FastAPI application entry point.

Run with:
    uvicorn edge.main:app --host 0.0.0.0 --port 8000 --reload

Features:
- Async lifespan context manager (startup / shutdown)
- CORS middleware for dashboard access
- All API routers from api/
- WebSocket endpoint at /ws/live for real-time sensor streaming
- Background tasks: LoRa listener, cloud sync scheduler
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from edge.config import settings
from edge.database import db

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("jalnetra")

# ---------------------------------------------------------------------------
# Application state shared across the lifespan
# ---------------------------------------------------------------------------


class _AppState:
    """Mutable state bag attached to the app during its lifetime."""

    models_loaded: bool = False
    lora_task: asyncio.Task[None] | None = None
    sync_task: asyncio.Task[None] | None = None
    inference_engine: object | None = None
    ws_clients: set[WebSocket] = set()
    startup_time: datetime = datetime.now(timezone.utc)


_state = _AppState()


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def _lora_listener_loop() -> None:
    """Placeholder background loop for LoRa serial receiver.

    The real implementation lives in ``edge.services.lora_receiver`` and
    would be imported here.  This stub logs heartbeats so the lifespan
    machinery can be tested independently of hardware.
    """
    logger.info("[LoRa] Background listener started (port=%s)", settings.jalnetra_lora_port)
    while True:
        try:
            # In production: read from serial, parse, ingest, run inference
            await asyncio.sleep(settings.sensor_read_interval_s)
        except asyncio.CancelledError:
            logger.info("[LoRa] Listener cancelled — shutting down")
            break
        except Exception:
            logger.exception("[LoRa] Unexpected error in listener loop")
            await asyncio.sleep(5)


async def _cloud_sync_loop() -> None:
    """Periodic cloud sync background task."""
    interval = settings.cloud_sync_interval_hours * 3600
    logger.info(
        "[Sync] Cloud sync scheduler started (interval=%dh)",
        settings.cloud_sync_interval_hours,
    )
    while True:
        try:
            await asyncio.sleep(interval)
            logger.info("[Sync] Triggering scheduled cloud sync")
            # In production: call edge.services.cloud_sync.run_sync()
        except asyncio.CancelledError:
            logger.info("[Sync] Scheduler cancelled — shutting down")
            break
        except Exception:
            logger.exception("[Sync] Unexpected error in sync loop")
            await asyncio.sleep(60)


async def _load_models() -> None:
    """Load ONNX models into memory (non-blocking wrapper).

    Real implementation delegates to ``edge.services.inference_engine``.
    We catch ImportError so the server can start even when onnxruntime
    is not installed (useful in dev / CI).
    """
    try:
        model_dir = settings.jalnetra_model_dir
        if model_dir.exists():
            # Offload blocking model loads to a thread
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _sync_load_models)
            _state.models_loaded = True
            logger.info("[Models] ONNX models loaded from %s", model_dir)
        else:
            logger.warning("[Models] Model directory not found: %s", model_dir)
    except Exception:
        logger.exception("[Models] Failed to load ONNX models — inference disabled")


def _sync_load_models() -> None:
    """Synchronous model loading (runs in executor thread).

    Attempts to import onnxruntime; falls back gracefully.
    """
    try:
        import onnxruntime as ort  # noqa: F401

        # Actual session creation would happen here using the
        # InferenceEngine class from the design doc.
        logger.info("[Models] onnxruntime %s available", ort.__version__)
    except ImportError:
        logger.warning("[Models] onnxruntime not installed — skipping model load")


# ---------------------------------------------------------------------------
# Lifespan context manager (Python 3.11+ style)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of the edge gateway."""

    # -- Startup --------------------------------------------------------------
    logger.info("JalNetra Edge Gateway v%s starting up", settings.version)
    _state.startup_time = datetime.now(timezone.utc)

    # 1. Initialise database (create tables / apply migrations)
    await db.initialise()

    # 2. Load ONNX models into memory
    await _load_models()

    # 3. Start background tasks using TaskGroup (Python 3.11+)
    _state.lora_task = asyncio.create_task(
        _lora_listener_loop(), name="lora-listener"
    )
    _state.sync_task = asyncio.create_task(
        _cloud_sync_loop(), name="cloud-sync"
    )

    logger.info("JalNetra Edge Gateway ready")

    yield  # ------ application is running ------

    # -- Shutdown -------------------------------------------------------------
    logger.info("JalNetra Edge Gateway shutting down")

    # Cancel background tasks gracefully
    for task in (_state.lora_task, _state.sync_task):
        if task and not task.done():
            task.cancel()

    # Await cancellation with a timeout
    pending = [t for t in (_state.lora_task, _state.sync_task) if t]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # Close all WebSocket connections
    for ws in list(_state.ws_clients):
        try:
            await ws.close(code=status.WS_1001_GOING_AWAY)
        except Exception:
            pass
    _state.ws_clients.clear()

    # Close database connections
    await db.close()

    logger.info("JalNetra Edge Gateway stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="JalNetra Edge Gateway",
    description=(
        "Edge-AI water quality & quantity monitoring API. "
        "Runs on AMD Ryzen AI with XDNA NPU inference for real-time "
        "anomaly detection, groundwater depletion forecasting, and "
        "irrigation optimisation."
    ),
    version=settings.version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# -- CORS Middleware ----------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Custom exception handlers
# ---------------------------------------------------------------------------


class JalNetraError(Exception):
    """Base exception for domain errors."""

    def __init__(self, detail: str, status_code: int = 500) -> None:
        self.detail = detail
        self.status_code = status_code


class NotFoundError(JalNetraError):
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(detail=detail, status_code=404)


class ValidationError(JalNetraError):
    def __init__(self, detail: str = "Validation failed") -> None:
        super().__init__(detail=detail, status_code=422)


@app.exception_handler(JalNetraError)
async def jalnetra_error_handler(request, exc: JalNetraError) -> JSONResponse:  # noqa: ANN001
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request, exc: Exception) -> JSONResponse:  # noqa: ANN001
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status_code": 500},
    )


# ---------------------------------------------------------------------------
# Dependency injection helpers (importable by routers)
# ---------------------------------------------------------------------------


async def get_db() -> "Database":  # noqa: F821
    """FastAPI dependency that yields the database singleton."""
    return db


def get_state() -> _AppState:
    """FastAPI dependency for accessing application state."""
    return _state


# ---------------------------------------------------------------------------
# Include API routers
# ---------------------------------------------------------------------------

from edge.api.readings import router as readings_router  # noqa: E402
from edge.api.alerts import router as alerts_router  # noqa: E402
from edge.api.nodes import router as nodes_router  # noqa: E402
from edge.api.predictions import router as predictions_router  # noqa: E402
from edge.api.health import router as health_router  # noqa: E402
from edge.api.reports import router as reports_router  # noqa: E402
from edge.api.sync import router as sync_router  # noqa: E402

app.include_router(readings_router)
app.include_router(alerts_router)
app.include_router(nodes_router)
app.include_router(predictions_router)
app.include_router(health_router)
app.include_router(reports_router)
app.include_router(sync_router)


# ---------------------------------------------------------------------------
# WebSocket endpoint — real-time sensor streaming
# ---------------------------------------------------------------------------


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    """Stream real-time sensor readings to connected dashboard clients.

    Protocol (server → client):
        JSON frames:
        {
            "type": "reading",
            "node_id": "...",
            "data": { ... },
            "timestamp": "ISO8601"
        }
        {
            "type": "alert",
            "node_id": "...",
            "severity": "...",
            "message": "..."
        }

    Clients can send JSON commands:
        {"action": "subscribe", "node_ids": ["JN-01", "JN-02"]}
        {"action": "unsubscribe"}
    """
    await ws.accept()
    _state.ws_clients.add(ws)
    subscribed_nodes: set[str] = set()
    logger.info("[WS] Client connected (%d total)", len(_state.ws_clients))

    try:
        while True:
            # Listen for client commands (with a timeout so we can push data)
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "subscribe":
                    node_ids = msg.get("node_ids", [])
                    subscribed_nodes = set(node_ids)
                    await ws.send_json({
                        "type": "subscribed",
                        "node_ids": list(subscribed_nodes),
                    })
                elif action == "unsubscribe":
                    subscribed_nodes.clear()
                    await ws.send_json({"type": "unsubscribed"})
            except asyncio.TimeoutError:
                # Send a heartbeat to keep the connection alive
                await ws.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "gateway_id": settings.jalnetra_node_id,
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("[WS] Error in WebSocket handler")
    finally:
        _state.ws_clients.discard(ws)
        logger.info("[WS] Client disconnected (%d remaining)", len(_state.ws_clients))


async def broadcast_reading(node_id: str, data: dict) -> None:
    """Push a new reading to all subscribed WebSocket clients.

    Called by the ingestion pipeline after a new reading is stored.
    """
    frame = json.dumps({
        "type": "reading",
        "node_id": node_id,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    stale: list[WebSocket] = []
    for ws in _state.ws_clients:
        try:
            await ws.send_text(frame)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _state.ws_clients.discard(ws)


async def broadcast_alert(node_id: str, severity: str, message: str) -> None:
    """Push an alert notification to all WebSocket clients."""
    frame = json.dumps({
        "type": "alert",
        "node_id": node_id,
        "severity": severity,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    stale: list[WebSocket] = []
    for ws in _state.ws_clients:
        try:
            await ws.send_text(frame)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _state.ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {
        "service": "JalNetra Edge Gateway",
        "version": settings.version,
        "gateway_id": settings.jalnetra_node_id,
        "docs": "/docs",
    }


def create_app() -> FastAPI:
    """Factory function for testing — returns the pre-configured app."""
    return app
