"""Async cloud synchronization service.

Batches readings and syncs to GCP Cloud Functions every 6 hours.
Immediate sync for critical alerts.

Architecture:
  - Collects unsynced readings from the local SQLite database
  - Compresses payloads with gzip for bandwidth-efficient rural 4G transmission
  - Uploads via httpx with Bearer token auth to GCP Cloud Functions endpoint
  - Exponential backoff retry (max 5 retries, base 2s, capped at 5 min)
  - Idempotent uploads via batch_id (UUID)
  - Persistent offline queue: unsynced batches survive restarts
  - Immediate sync pathway for CRITICAL/EMERGENCY alerts
  - Background asyncio task with graceful shutdown

Designed for intermittent-connectivity environments where cellular coverage
may be available only a few hours per day in rural India.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

import httpx
import structlog

from edge.config import settings
from edge.database import Database, db

logger = structlog.get_logger("jalnetra.cloud_sync")


# ---------------------------------------------------------------------------
# Sync status enum
# ---------------------------------------------------------------------------

class SyncStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Batch record
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SyncBatch:
    """Represents a single batch of data queued for cloud upload."""

    batch_id: str
    batch_type: str  # "readings", "alert", "status"
    payload: dict[str, Any]
    status: SyncStatus = SyncStatus.PENDING
    created_at: float = field(default_factory=time.time)
    last_attempt_at: float = 0.0
    attempts: int = 0
    error: str = ""
    compressed_size: int = 0
    priority: int = 0  # 0 = normal, 1 = high (critical alerts)

    def to_compressed_bytes(self) -> bytes:
        """Serialize payload to gzip-compressed JSON bytes."""
        raw = json.dumps(self.payload, separators=(",", ":"), default=str)
        compressed = gzip.compress(raw.encode("utf-8"), compresslevel=6)
        self.compressed_size = len(compressed)
        return compressed


# ---------------------------------------------------------------------------
# AsyncCloudSync
# ---------------------------------------------------------------------------

class AsyncCloudSync:
    """Background sync agent that batches and uploads data to GCP Cloud Functions.

    Usage::

        sync = AsyncCloudSync(database=db)
        await sync.start()

        # Readings are batched automatically from the DB
        await sync.batch_and_sync()

        # Critical alerts bypass the schedule
        await sync.sync_critical_alert(alert_dict)

        await sync.stop()
    """

    # -- Tunables --
    MAX_RETRIES: int = 5
    RETRY_BASE_SEC: float = 2.0
    RETRY_MAX_SEC: float = 300.0  # 5-minute cap
    MAX_BATCH_SIZE: int = 500  # readings per batch
    HTTP_TIMEOUT_SEC: float = 60.0

    def __init__(
        self,
        *,
        database: Database | None = None,
        cloud_endpoint: str | None = None,
        api_key: str | None = None,
        device_id: str | None = None,
        sync_interval_hours: int | None = None,
    ) -> None:
        self._db = database or db
        self._endpoint = cloud_endpoint or settings.cloud_sync_url
        self._api_key = api_key or settings.cloud_sync_api_key
        self._device_id = device_id or settings.jalnetra_node_id
        self._sync_interval_sec: float = (
            (sync_interval_hours or settings.cloud_sync_interval_hours) * 3600
        )

        # Offline queue — batches waiting to be sent
        self._offline_queue: list[SyncBatch] = []
        self._queue_lock = asyncio.Lock()

        # Runtime state
        self._http_client: httpx.AsyncClient | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._immediate_event = asyncio.Event()

        # Stats
        self._total_synced: int = 0
        self._total_failed: int = 0
        self._total_bytes_sent: int = 0
        self._last_sync_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise httpx client and spawn background sync loop."""
        if self._running:
            return
        self._running = True

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.HTTP_TIMEOUT_SEC),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

        # Restore any persisted pending batches from sync_log
        await self._restore_offline_queue()

        sync_task = asyncio.create_task(
            self._scheduled_sync_loop(), name="cloud-sync-scheduled"
        )
        upload_task = asyncio.create_task(
            self._upload_loop(), name="cloud-sync-upload"
        )
        self._tasks.extend([sync_task, upload_task])

        await logger.ainfo(
            "Cloud sync started",
            endpoint=self._endpoint,
            device_id=self._device_id,
            interval_h=self._sync_interval_sec / 3600,
            offline_queue_size=len(self._offline_queue),
        )

    async def stop(self) -> None:
        """Flush pending work and shut down gracefully."""
        self._running = False

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        await logger.ainfo(
            "Cloud sync stopped",
            total_synced=self._total_synced,
            total_failed=self._total_failed,
            bytes_sent=self._total_bytes_sent,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def batch_and_sync(self) -> int:
        """Collect unsynced readings from DB, compress, and queue for upload.

        Returns the number of readings queued.
        """
        readings = await self._db.get_unsynced_readings(limit=self.MAX_BATCH_SIZE * 10)
        if not readings:
            await logger.adebug("No unsynced readings to batch")
            return 0

        total_queued = 0
        # Split into MAX_BATCH_SIZE chunks
        for i in range(0, len(readings), self.MAX_BATCH_SIZE):
            chunk = readings[i : i + self.MAX_BATCH_SIZE]
            batch_id = str(uuid.uuid4())

            batch = SyncBatch(
                batch_id=batch_id,
                batch_type="readings",
                payload={
                    "device_id": self._device_id,
                    "village_id": settings.jalnetra_village_id,
                    "batch_id": batch_id,
                    "readings": chunk,
                    "count": len(chunk),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Persist to sync_log for crash recovery
            await self._db.insert_sync_log(
                batch_id=batch_id,
                records_sent=len(chunk),
                status=SyncStatus.PENDING,
            )

            async with self._queue_lock:
                self._offline_queue.append(batch)

            total_queued += len(chunk)
            await logger.ainfo(
                "Batch created",
                batch_id=batch_id,
                readings_count=len(chunk),
            )

        # Signal the upload loop
        self._immediate_event.set()
        return total_queued

    async def sync_critical_alert(self, alert: dict[str, Any]) -> str:
        """Immediately queue and sync a critical/emergency alert.

        Bypasses the normal schedule to push urgent data immediately.

        Returns:
            The batch_id for tracking.
        """
        batch_id = str(uuid.uuid4())

        batch = SyncBatch(
            batch_id=batch_id,
            batch_type="alert",
            payload={
                "device_id": self._device_id,
                "village_id": settings.jalnetra_village_id,
                "batch_id": batch_id,
                "alert": alert,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "priority": "critical",
            },
            priority=1,
        )

        await self._db.insert_sync_log(
            batch_id=batch_id, records_sent=1, status=SyncStatus.PENDING
        )

        async with self._queue_lock:
            # Insert at front for priority processing
            self._offline_queue.insert(0, batch)

        # Wake up the upload loop immediately
        self._immediate_event.set()

        await logger.awarning(
            "Critical alert queued for immediate sync",
            batch_id=batch_id,
            alert_type=alert.get("alert_type", "unknown"),
        )
        return batch_id

    async def force_sync(self) -> int:
        """Force an immediate batch-and-upload cycle.

        Returns the number of batches successfully synced.
        """
        await self.batch_and_sync()
        return await self._process_offline_queue()

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _scheduled_sync_loop(self) -> None:
        """Periodically collect unsynced readings and batch them."""
        while self._running:
            try:
                await asyncio.sleep(self._sync_interval_sec)
                await logger.ainfo("Scheduled sync triggered")
                await self.batch_and_sync()
            except asyncio.CancelledError:
                break
            except Exception:
                await logger.aexception("Scheduled sync loop error")
                await asyncio.sleep(60)

    async def _upload_loop(self) -> None:
        """Upload pending batches, triggered by schedule or immediate signal."""
        while self._running:
            try:
                # Wait for either a signal or a 60-second poll interval
                try:
                    await asyncio.wait_for(
                        self._immediate_event.wait(), timeout=60.0
                    )
                    self._immediate_event.clear()
                except asyncio.TimeoutError:
                    pass

                await self._process_offline_queue()
            except asyncio.CancelledError:
                break
            except Exception:
                await logger.aexception("Upload loop error")
                await asyncio.sleep(30)

    async def _process_offline_queue(self) -> int:
        """Process all batches in the offline queue.

        Returns the number of successfully synced batches.
        """
        synced = 0

        while self._running:
            async with self._queue_lock:
                if not self._offline_queue:
                    break
                # Process highest priority first (priority=1 alerts at front)
                batch = self._offline_queue[0]

            success = await self._upload_batch(batch)

            if success:
                async with self._queue_lock:
                    if batch in self._offline_queue:
                        self._offline_queue.remove(batch)
                synced += 1
            else:
                # If max retries exceeded, remove from queue
                if batch.attempts >= self.MAX_RETRIES:
                    async with self._queue_lock:
                        if batch in self._offline_queue:
                            self._offline_queue.remove(batch)
                    self._total_failed += 1
                    await logger.aerror(
                        "Batch permanently failed after max retries",
                        batch_id=batch.batch_id,
                        attempts=batch.attempts,
                        error=batch.error,
                    )
                else:
                    # Move to end of queue for retry later
                    async with self._queue_lock:
                        if batch in self._offline_queue:
                            self._offline_queue.remove(batch)
                            self._offline_queue.append(batch)
                    break  # Back off before retrying

        return synced

    # ------------------------------------------------------------------
    # HTTP upload with exponential backoff
    # ------------------------------------------------------------------

    async def _upload_batch(self, batch: SyncBatch) -> bool:
        """Upload a single batch with exponential backoff retry.

        Returns True on success, False on failure.
        """
        if not self._http_client:
            batch.error = "HTTP client not initialized"
            return False

        # Exponential backoff check
        if batch.attempts > 0:
            backoff = min(
                self.RETRY_BASE_SEC * (2 ** (batch.attempts - 1)),
                self.RETRY_MAX_SEC,
            )
            elapsed = time.time() - batch.last_attempt_at
            if elapsed < backoff:
                await asyncio.sleep(backoff - elapsed)

        batch.attempts += 1
        batch.last_attempt_at = time.time()
        batch.status = SyncStatus.IN_PROGRESS

        # Update sync_log
        try:
            await self._db.update_sync_log(
                batch.batch_id, status=SyncStatus.IN_PROGRESS
            )
        except Exception:
            pass  # Non-critical: log tracking failure

        # Compress payload
        try:
            compressed = batch.to_compressed_bytes()
        except Exception as exc:
            batch.error = f"Compression failed: {exc}"
            batch.status = SyncStatus.FAILED
            return False

        headers = {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "X-Batch-ID": batch.batch_id,
            "X-Device-ID": self._device_id,
            "X-Batch-Type": batch.batch_type,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            resp = await self._http_client.post(
                self._endpoint,
                content=compressed,
                headers=headers,
            )
            resp.raise_for_status()

            # Success
            batch.status = SyncStatus.SUCCESS
            self._total_synced += 1
            self._total_bytes_sent += batch.compressed_size
            self._last_sync_at = time.time()

            # Mark readings as synced in the main DB
            if batch.batch_type == "readings":
                reading_ids = [
                    r["id"] for r in batch.payload.get("readings", [])
                    if isinstance(r, dict) and "id" in r
                ]
                if reading_ids:
                    await self._db.mark_readings_synced(reading_ids)

            # Update sync_log
            try:
                await self._db.update_sync_log(
                    batch.batch_id, status=SyncStatus.SUCCESS
                )
            except Exception:
                pass

            await logger.ainfo(
                "Batch synced successfully",
                batch_id=batch.batch_id,
                batch_type=batch.batch_type,
                compressed_bytes=batch.compressed_size,
                attempt=batch.attempts,
            )
            return True

        except httpx.HTTPStatusError as exc:
            error_msg = (
                f"HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
            batch.error = error_msg
            batch.status = SyncStatus.FAILED

            await logger.awarning(
                "Batch upload HTTP error",
                batch_id=batch.batch_id,
                attempt=batch.attempts,
                max_retries=self.MAX_RETRIES,
                error=error_msg,
            )

        except (httpx.RequestError, OSError) as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            batch.error = error_msg
            batch.status = SyncStatus.FAILED

            await logger.awarning(
                "Batch upload network error",
                batch_id=batch.batch_id,
                attempt=batch.attempts,
                max_retries=self.MAX_RETRIES,
                error=error_msg,
            )

        # Update sync_log on failure
        try:
            await self._db.update_sync_log(
                batch.batch_id,
                status=SyncStatus.FAILED,
                error_message=batch.error,
            )
        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # Offline queue persistence
    # ------------------------------------------------------------------

    async def _restore_offline_queue(self) -> None:
        """Restore pending/failed batches from sync_log on startup.

        This ensures no data is lost across service restarts.
        """
        try:
            async with self._db.acquire() as conn:
                cursor = await conn.execute(
                    """SELECT batch_id, records_sent, status, error_message
                       FROM sync_log
                       WHERE status IN ('pending', 'in_progress', 'failed')
                       ORDER BY created_at ASC
                       LIMIT 100"""
                )
                rows = await cursor.fetchall()

            for row in rows:
                row_dict = dict(row)
                # Re-fetch unsynced readings for reading batches
                batch = SyncBatch(
                    batch_id=row_dict["batch_id"],
                    batch_type="readings",
                    payload={
                        "device_id": self._device_id,
                        "batch_id": row_dict["batch_id"],
                        "note": "restored_from_offline_queue",
                    },
                    status=SyncStatus.PENDING,
                    error=row_dict.get("error_message") or "",
                )
                self._offline_queue.append(batch)

            if rows:
                await logger.ainfo(
                    "Restored offline queue from sync_log",
                    restored_count=len(rows),
                )
        except Exception:
            await logger.aexception("Failed to restore offline queue")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        """Return current sync statistics."""
        return {
            "running": self._running,
            "device_id": self._device_id,
            "endpoint": self._endpoint,
            "sync_interval_hours": self._sync_interval_sec / 3600,
            "total_synced": self._total_synced,
            "total_failed": self._total_failed,
            "total_bytes_sent": self._total_bytes_sent,
            "last_sync_at": self._last_sync_at,
            "offline_queue_size": len(self._offline_queue),
        }
