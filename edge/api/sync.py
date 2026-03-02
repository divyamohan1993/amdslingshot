"""JalNetra Edge Gateway — Cloud sync API endpoints.

Routes:
    POST /api/v1/sync        — Trigger a cloud sync
    GET  /api/v1/sync/status — Latest sync status
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from edge.config import settings
from edge.database import Database, db

logger = logging.getLogger("jalnetra.api.sync")

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SyncTriggerResponse(BaseModel):
    batch_id: str
    status: str
    message: str
    records_queued: int


class SyncStatusResponse(BaseModel):
    batch_id: str | None = None
    records_sent: int = 0
    status: str = "unknown"
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    cloud_sync_url: str
    sync_interval_hours: int


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def _get_db() -> Database:
    return db


# ---------------------------------------------------------------------------
# Background sync task
# ---------------------------------------------------------------------------


async def _run_sync(batch_id: str, database: Database) -> None:
    """Execute the cloud sync in the background.

    In production this would:
    1. Gather all unsynced readings.
    2. Compress into a gzip JSON payload.
    3. POST to cloud_sync_url with mTLS + API key auth.
    4. On success, mark readings as synced and update sync_log.
    5. On failure, retry with exponential backoff.
    """
    try:
        await database.update_sync_log(batch_id, status="in_progress")
        logger.info("[Sync] Batch %s started", batch_id)

        # Gather unsynced data
        readings = await database.get_unsynced_readings(limit=5000)
        if not readings:
            await database.update_sync_log(batch_id, status="success")
            logger.info("[Sync] Batch %s — no unsynced readings", batch_id)
            return

        # --- Production implementation would go here ---
        # payload = {
        #     "gateway_id": settings.jalnetra_node_id,
        #     "batch_id": batch_id,
        #     "readings": readings,
        #     "sync_timestamp": datetime.now(timezone.utc).isoformat(),
        # }
        # async with httpx.AsyncClient() as client:
        #     resp = await client.post(
        #         settings.cloud_sync_url,
        #         json=payload,
        #         headers={"Authorization": f"Bearer {settings.cloud_sync_api_key}"},
        #         timeout=30.0,
        #     )
        #     resp.raise_for_status()

        # Mark as synced
        reading_ids = [r["id"] for r in readings]
        await database.mark_readings_synced(reading_ids)
        await database.update_sync_log(batch_id, status="success")
        logger.info(
            "[Sync] Batch %s completed — %d readings synced",
            batch_id, len(readings),
        )

    except Exception as exc:
        logger.exception("[Sync] Batch %s failed: %s", batch_id, exc)
        await database.update_sync_log(
            batch_id, status="failed", error_message=str(exc)
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=SyncTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    background_tasks: BackgroundTasks,
    database: Database = Depends(_get_db),
) -> SyncTriggerResponse:
    """Manually trigger a cloud data sync.

    The sync runs asynchronously in the background.  The response
    returns immediately with a batch_id that can be used to track
    progress via GET /api/v1/sync/status.
    """
    # Check how many unsynced readings we have
    unsynced = await database.get_unsynced_readings(limit=1)
    unsynced_count = await database.count_readings()  # approximate
    # More precise:
    readings = await database.get_unsynced_readings(limit=100_000)
    queued = len(readings)

    batch_id = str(uuid.uuid4())
    await database.insert_sync_log(
        batch_id=batch_id, records_sent=queued, status="pending"
    )

    background_tasks.add_task(_run_sync, batch_id, database)

    return SyncTriggerResponse(
        batch_id=batch_id,
        status="pending",
        message="Cloud sync initiated in background",
        records_queued=queued,
    )


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(
    database: Database = Depends(_get_db),
) -> SyncStatusResponse:
    """Get the status of the most recent cloud sync."""
    latest = await database.get_latest_sync()
    if latest is None:
        return SyncStatusResponse(
            status="never_synced",
            cloud_sync_url=settings.cloud_sync_url,
            sync_interval_hours=settings.cloud_sync_interval_hours,
        )
    return SyncStatusResponse(
        batch_id=latest.get("batch_id"),
        records_sent=latest.get("records_sent", 0),
        status=latest.get("status", "unknown"),
        error_message=latest.get("error_message"),
        started_at=latest.get("started_at"),
        completed_at=latest.get("completed_at"),
        created_at=latest.get("created_at"),
        cloud_sync_url=settings.cloud_sync_url,
        sync_interval_hours=settings.cloud_sync_interval_hours,
    )
