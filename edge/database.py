"""JalNetra Edge Gateway — Async SQLite database layer.

Provides:
- Full schema creation with BIS-compliant tables
- Async CRUD for sensor_nodes, readings, alerts, irrigation_schedules,
  predictions, subscribers, and sync_log
- Connection pool management via a singleton ``Database`` instance
- Migration support (version-tracked schema upgrades)
- Time-series optimised queries with proper indexing
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Sequence

import aiosqlite

from edge.config import settings

logger = logging.getLogger("jalnetra.database")

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_VERSION: int = 1

_SCHEMA_SQL: str = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Sensor node registry
CREATE TABLE IF NOT EXISTS sensor_nodes (
    id            TEXT PRIMARY KEY,
    village_id    TEXT NOT NULL,
    location_name TEXT NOT NULL,
    latitude      REAL,
    longitude     REAL,
    source_type   TEXT CHECK(source_type IN ('borewell','handpump','canal','reservoir','tap')),
    installed_at  TEXT NOT NULL,
    last_seen_at  TEXT,
    battery_voltage REAL,
    status        TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','maintenance'))
);

-- Sensor readings (time-series core)
CREATE TABLE IF NOT EXISTS readings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         TEXT    NOT NULL REFERENCES sensor_nodes(id) ON DELETE CASCADE,
    tds             REAL,
    ph              REAL,
    turbidity       REAL,
    flow_rate       REAL,
    water_level     REAL,
    battery_voltage REAL,
    timestamp       TEXT    NOT NULL,
    synced          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_readings_node_time
    ON readings(node_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_synced
    ON readings(synced) WHERE synced = 0;
CREATE INDEX IF NOT EXISTS idx_readings_timestamp
    ON readings(timestamp);

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         TEXT    NOT NULL REFERENCES sensor_nodes(id) ON DELETE CASCADE,
    alert_type      TEXT    NOT NULL,
    severity        TEXT    NOT NULL CHECK(severity IN ('info','warning','critical')),
    message         TEXT    NOT NULL,
    confidence      REAL,
    reading_id      INTEGER REFERENCES readings(id),
    acknowledged    INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_alerts_node
    ON alerts(node_id);
CREATE INDEX IF NOT EXISTS idx_alerts_severity
    ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_created
    ON alerts(created_at);

-- Irrigation schedules
CREATE TABLE IF NOT EXISTS irrigation_schedules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id           TEXT    NOT NULL REFERENCES sensor_nodes(id) ON DELETE CASCADE,
    schedule_date     TEXT    NOT NULL,
    recommended_hours REAL,
    crop_type         TEXT,
    water_saved_pct   REAL,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_irrigation_node_date
    ON irrigation_schedules(node_id, schedule_date);

-- Depletion / quality predictions
CREATE TABLE IF NOT EXISTS predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id          TEXT    NOT NULL REFERENCES sensor_nodes(id) ON DELETE CASCADE,
    prediction_type  TEXT    NOT NULL,
    days_to_critical INTEGER,
    trend            TEXT,
    predicted_values TEXT,  -- JSON array
    confidence       REAL,
    created_at       TEXT   NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_predictions_node
    ON predictions(node_id, created_at);

-- Alert subscribers
CREATE TABLE IF NOT EXISTS subscribers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    village_id         TEXT    NOT NULL,
    name               TEXT    NOT NULL,
    phone              TEXT    NOT NULL,
    preferred_language TEXT    NOT NULL DEFAULT 'hi',
    has_whatsapp       INTEGER NOT NULL DEFAULT 0,
    role               TEXT    CHECK(role IN ('farmer','panchayat','technician')),
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_subscribers_village
    ON subscribers(village_id);

-- Cloud sync log
CREATE TABLE IF NOT EXISTS sync_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT    NOT NULL UNIQUE,
    records_sent  INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL CHECK(status IN ('pending','in_progress','success','failed')),
    error_message TEXT,
    started_at    TEXT,
    completed_at  TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_sync_log_status
    ON sync_log(status);
"""

# ---------------------------------------------------------------------------
# Migrations registry — add new entries as the schema evolves
# ---------------------------------------------------------------------------

_MIGRATIONS: dict[int, str] = {
    # version 2 would go here, e.g.:
    # 2: "ALTER TABLE readings ADD COLUMN dissolved_oxygen REAL;",
}

# ---------------------------------------------------------------------------
# Database singleton
# ---------------------------------------------------------------------------


class Database:
    """Async SQLite wrapper with connection pooling and migration support."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path: str = str(db_path or settings.jalnetra_db_path)
        self._pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._pool_size: int = 5
        self._initialised: bool = False

    # -- Lifecycle ------------------------------------------------------------

    async def _open_connection(self) -> aiosqlite.Connection:
        """Open a single connection with standard PRAGMAs applied."""
        # For in-memory databases use shared-cache URI so all connections
        # see the same database.  File-backed databases work normally.
        if self._db_path == ":memory:":
            uri = "file:jalnetra_mem?mode=memory&cache=shared"
            conn = await aiosqlite.connect(uri, uri=True)
        else:
            conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    async def initialise(self) -> None:
        """Create tables, apply migrations, warm the connection pool."""
        if self._db_path != ":memory:":
            db_dir = Path(self._db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

        # Create the first connection, run schema DDL, then keep it in pool
        init_conn = await self._open_connection()
        await init_conn.executescript(_SCHEMA_SQL)
        await self._apply_migrations(init_conn)
        await init_conn.commit()
        self._pool.append(init_conn)

        # Warm the rest of the pool
        for _ in range(self._pool_size - 1):
            conn = await self._open_connection()
            self._pool.append(conn)

        self._initialised = True
        logger.info("Database initialised at %s", self._db_path)

    async def close(self) -> None:
        """Gracefully close all pooled connections."""
        async with self._pool_lock:
            for conn in self._pool:
                await conn.close()
            self._pool.clear()
        self._initialised = False
        logger.info("Database connections closed")

    # -- Connection helpers ---------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[aiosqlite.Connection]:
        """Borrow a connection from the pool; return it when done."""
        conn: aiosqlite.Connection | None = None
        async with self._pool_lock:
            if self._pool:
                conn = self._pool.pop()
        if conn is None:
            conn = await self._open_connection()
        try:
            yield conn
        finally:
            async with self._pool_lock:
                if len(self._pool) < self._pool_size:
                    self._pool.append(conn)
                else:
                    await conn.close()

    # -- Migrations -----------------------------------------------------------

    async def _apply_migrations(self, conn: aiosqlite.Connection) -> None:
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        current = int(row[0]) if row else 0

        if current < _SCHEMA_VERSION:
            await conn.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )

        for ver in sorted(_MIGRATIONS):
            if ver > current:
                logger.info("Applying migration v%d", ver)
                await conn.executescript(_MIGRATIONS[ver])
                await conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (ver,)
                )
        await conn.commit()

    # -----------------------------------------------------------------------
    # CRUD — Sensor Nodes
    # -----------------------------------------------------------------------

    async def upsert_node(
        self,
        *,
        node_id: str,
        village_id: str,
        location_name: str,
        latitude: float | None = None,
        longitude: float | None = None,
        source_type: str | None = None,
        installed_at: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        now = _utcnow()
        installed = installed_at or now
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sensor_nodes
                    (id, village_id, location_name, latitude, longitude,
                     source_type, installed_at, last_seen_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    village_id    = excluded.village_id,
                    location_name = excluded.location_name,
                    latitude      = excluded.latitude,
                    longitude     = excluded.longitude,
                    source_type   = excluded.source_type,
                    last_seen_at  = excluded.last_seen_at,
                    status        = excluded.status
                """,
                (
                    node_id, village_id, location_name, latitude, longitude,
                    source_type, installed, now, status,
                ),
            )
            await conn.commit()
        return await self.get_node(node_id)  # type: ignore[return-value]

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM sensor_nodes WHERE id = ?", (node_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_nodes(
        self,
        *,
        status: str | None = None,
        village_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if village_id:
            clauses.append("village_id = ?")
            params.append(village_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"SELECT * FROM sensor_nodes {where} ORDER BY id", params
            )
            return [dict(r) for r in await cursor.fetchall()]

    async def update_node(
        self, node_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        allowed = {
            "village_id", "location_name", "latitude", "longitude",
            "source_type", "status", "battery_voltage", "last_seen_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get_node(node_id)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = [*updates.values(), node_id]
        async with self.acquire() as conn:
            await conn.execute(
                f"UPDATE sensor_nodes SET {set_clause} WHERE id = ?", params
            )
            await conn.commit()
        return await self.get_node(node_id)

    # -----------------------------------------------------------------------
    # CRUD — Readings
    # -----------------------------------------------------------------------

    async def insert_reading(
        self,
        *,
        node_id: str,
        tds: float | None = None,
        ph: float | None = None,
        turbidity: float | None = None,
        flow_rate: float | None = None,
        water_level: float | None = None,
        battery_voltage: float | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        ts = timestamp or _utcnow()
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO readings
                    (node_id, tds, ph, turbidity, flow_rate, water_level,
                     battery_voltage, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, tds, ph, turbidity, flow_rate, water_level,
                 battery_voltage, ts),
            )
            await conn.commit()
            reading_id = cursor.lastrowid

            # Touch node last_seen_at + battery
            await conn.execute(
                """
                UPDATE sensor_nodes
                SET last_seen_at = ?, battery_voltage = COALESCE(?, battery_voltage)
                WHERE id = ?
                """,
                (ts, battery_voltage, node_id),
            )
            await conn.commit()

        return await self.get_reading(reading_id)  # type: ignore[return-value]

    async def get_reading(self, reading_id: int) -> dict[str, Any] | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM readings WHERE id = ?", (reading_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_readings(
        self,
        *,
        node_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"""
                SELECT * FROM readings {where}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            return [dict(r) for r in await cursor.fetchall()]

    async def get_latest_readings(self) -> list[dict[str, Any]]:
        """Latest reading per node (time-series optimised)."""
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                SELECT r.* FROM readings r
                INNER JOIN (
                    SELECT node_id, MAX(timestamp) AS max_ts
                    FROM readings
                    GROUP BY node_id
                ) latest ON r.node_id = latest.node_id
                           AND r.timestamp = latest.max_ts
                ORDER BY r.node_id
                """
            )
            return [dict(r) for r in await cursor.fetchall()]

    async def count_readings(
        self,
        *,
        node_id: str | None = None,
        since: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM readings {where}", params
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def get_unsynced_readings(self, limit: int = 1000) -> list[dict[str, Any]]:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM readings WHERE synced = 0 ORDER BY timestamp LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in await cursor.fetchall()]

    async def mark_readings_synced(self, reading_ids: Sequence[int]) -> None:
        if not reading_ids:
            return
        placeholders = ",".join("?" * len(reading_ids))
        async with self.acquire() as conn:
            await conn.execute(
                f"UPDATE readings SET synced = 1 WHERE id IN ({placeholders})",
                list(reading_ids),
            )
            await conn.commit()

    # -----------------------------------------------------------------------
    # CRUD — Alerts
    # -----------------------------------------------------------------------

    async def insert_alert(
        self,
        *,
        node_id: str,
        alert_type: str,
        severity: str,
        message: str,
        confidence: float | None = None,
        reading_id: int | None = None,
    ) -> dict[str, Any]:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO alerts
                    (node_id, alert_type, severity, message, confidence, reading_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (node_id, alert_type, severity, message, confidence, reading_id),
            )
            await conn.commit()
            alert_id = cursor.lastrowid
        return await self.get_alert(alert_id)  # type: ignore[return-value]

    async def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM alerts WHERE id = ?", (alert_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_alerts(
        self,
        *,
        node_id: str | None = None,
        severity: str | None = None,
        acknowledged: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if acknowledged is not None:
            clauses.append("acknowledged = ?")
            params.append(int(acknowledged))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"""
                SELECT * FROM alerts {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            )
            return [dict(r) for r in await cursor.fetchall()]

    async def acknowledge_alert(
        self, alert_id: int, acknowledged_by: str = "system"
    ) -> dict[str, Any] | None:
        now = _utcnow()
        async with self.acquire() as conn:
            await conn.execute(
                """
                UPDATE alerts
                SET acknowledged = 1, acknowledged_at = ?, acknowledged_by = ?
                WHERE id = ?
                """,
                (now, acknowledged_by, alert_id),
            )
            await conn.commit()
        return await self.get_alert(alert_id)

    async def get_alert_stats(
        self,
        *,
        node_id: str | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"""
                SELECT
                    COUNT(*)                                       AS total,
                    SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END) AS critical,
                    SUM(CASE WHEN severity='warning'  THEN 1 ELSE 0 END) AS warning,
                    SUM(CASE WHEN severity='info'     THEN 1 ELSE 0 END) AS info,
                    SUM(CASE WHEN acknowledged=1      THEN 1 ELSE 0 END) AS acknowledged,
                    SUM(CASE WHEN acknowledged=0      THEN 1 ELSE 0 END) AS unacknowledged
                FROM alerts {where}
                """,
                params,
            )
            row = await cursor.fetchone()
            return dict(row) if row else {}

    # -----------------------------------------------------------------------
    # CRUD — Irrigation Schedules
    # -----------------------------------------------------------------------

    async def insert_irrigation_schedule(
        self,
        *,
        node_id: str,
        schedule_date: str,
        recommended_hours: float | None = None,
        crop_type: str | None = None,
        water_saved_pct: float | None = None,
    ) -> dict[str, Any]:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO irrigation_schedules
                    (node_id, schedule_date, recommended_hours, crop_type, water_saved_pct)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id, schedule_date, recommended_hours, crop_type, water_saved_pct),
            )
            await conn.commit()
            row_id = cursor.lastrowid
            cur = await conn.execute(
                "SELECT * FROM irrigation_schedules WHERE id = ?", (row_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else {}

    async def list_irrigation_schedules(
        self,
        *,
        node_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if from_date:
            clauses.append("schedule_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("schedule_date <= ?")
            params.append(to_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"""
                SELECT * FROM irrigation_schedules {where}
                ORDER BY schedule_date DESC
                LIMIT ?
                """,
                params,
            )
            return [dict(r) for r in await cursor.fetchall()]

    # -----------------------------------------------------------------------
    # CRUD — Predictions
    # -----------------------------------------------------------------------

    async def insert_prediction(
        self,
        *,
        node_id: str,
        prediction_type: str,
        days_to_critical: int | None = None,
        trend: str | None = None,
        predicted_values: list[float] | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        values_json = json.dumps(predicted_values) if predicted_values else None
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO predictions
                    (node_id, prediction_type, days_to_critical, trend,
                     predicted_values, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (node_id, prediction_type, days_to_critical, trend,
                 values_json, confidence),
            )
            await conn.commit()
            row_id = cursor.lastrowid
            cur = await conn.execute(
                "SELECT * FROM predictions WHERE id = ?", (row_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else {}

    async def list_predictions(
        self,
        *,
        node_id: str | None = None,
        prediction_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if prediction_type:
            clauses.append("prediction_type = ?")
            params.append(prediction_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"""
                SELECT * FROM predictions {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = [dict(r) for r in await cursor.fetchall()]
            for row in rows:
                if row.get("predicted_values"):
                    try:
                        row["predicted_values"] = json.loads(row["predicted_values"])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return rows

    async def get_latest_prediction(
        self, node_id: str, prediction_type: str = "depletion"
    ) -> dict[str, Any] | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM predictions
                WHERE node_id = ? AND prediction_type = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (node_id, prediction_type),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            result = dict(row)
            if result.get("predicted_values"):
                try:
                    result["predicted_values"] = json.loads(result["predicted_values"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return result

    # -----------------------------------------------------------------------
    # CRUD — Subscribers
    # -----------------------------------------------------------------------

    async def insert_subscriber(
        self,
        *,
        village_id: str,
        name: str,
        phone: str,
        preferred_language: str = "hi",
        has_whatsapp: bool = False,
        role: str = "farmer",
    ) -> dict[str, Any]:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO subscribers
                    (village_id, name, phone, preferred_language, has_whatsapp, role)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (village_id, name, phone, preferred_language, int(has_whatsapp), role),
            )
            await conn.commit()
            row_id = cursor.lastrowid
            cur = await conn.execute(
                "SELECT * FROM subscribers WHERE id = ?", (row_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else {}

    async def get_subscribers(self, village_id: str) -> list[dict[str, Any]]:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM subscribers WHERE village_id = ?", (village_id,)
            )
            return [dict(r) for r in await cursor.fetchall()]

    # -----------------------------------------------------------------------
    # CRUD — Sync Log
    # -----------------------------------------------------------------------

    async def insert_sync_log(
        self, *, batch_id: str, records_sent: int = 0, status: str = "pending"
    ) -> dict[str, Any]:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO sync_log (batch_id, records_sent, status, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (batch_id, records_sent, status, _utcnow()),
            )
            await conn.commit()
            row_id = cursor.lastrowid
            cur = await conn.execute(
                "SELECT * FROM sync_log WHERE id = ?", (row_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else {}

    async def update_sync_log(
        self, batch_id: str, *, status: str, error_message: str | None = None
    ) -> None:
        now = _utcnow()
        async with self.acquire() as conn:
            await conn.execute(
                """
                UPDATE sync_log
                SET status = ?, error_message = ?, completed_at = ?
                WHERE batch_id = ?
                """,
                (status, error_message, now, batch_id),
            )
            await conn.commit()

    async def get_latest_sync(self) -> dict[str, Any] | None:
        async with self.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM sync_log ORDER BY created_at DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # -----------------------------------------------------------------------
    # Time-series aggregation helpers
    # -----------------------------------------------------------------------

    async def get_readings_summary(
        self,
        *,
        node_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate summary (avg, min, max) over a time window."""
        clauses: list[str] = []
        params: list[Any] = []
        if node_id:
            clauses.append("node_id = ?")
            params.append(node_id)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self.acquire() as conn:
            cursor = await conn.execute(
                f"""
                SELECT
                    COUNT(*)           AS reading_count,
                    AVG(tds)           AS avg_tds,
                    MIN(tds)           AS min_tds,
                    MAX(tds)           AS max_tds,
                    AVG(ph)            AS avg_ph,
                    MIN(ph)            AS min_ph,
                    MAX(ph)            AS max_ph,
                    AVG(turbidity)     AS avg_turbidity,
                    MIN(turbidity)     AS min_turbidity,
                    MAX(turbidity)     AS max_turbidity,
                    AVG(flow_rate)     AS avg_flow_rate,
                    AVG(water_level)   AS avg_water_level,
                    MIN(water_level)   AS min_water_level,
                    MAX(water_level)   AS max_water_level,
                    MIN(timestamp)     AS period_start,
                    MAX(timestamp)     AS period_end
                FROM readings {where}
                """,
                params,
            )
            row = await cursor.fetchone()
            return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# Module-level singleton
db = Database()
