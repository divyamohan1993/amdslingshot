"""WebSocket connection manager for real-time data streaming.

Manages multiple concurrent WebSocket connections for the JalNetra edge
gateway, enabling real-time push of sensor readings, alerts, and system
status updates to connected dashboard clients.

Features:
  - Per-client filtering by node_id (subscribe to specific sensor nodes)
  - Per-client severity filtering for alerts
  - JSON message protocol with typed message envelopes
  - Automatic heartbeat / keepalive pings with stale connection pruning
  - Thread-safe connection registry with asyncio.Lock
  - Graceful shutdown with close_all

Message Protocol (JSON)
~~~~~~~~~~~~~~~~~~~~~~~
Every message is a JSON object with a mandatory ``type`` field.

**Server -> Client messages:**
  - ``reading``       : New sensor reading for a subscribed node
  - ``alert``         : Alert notification (bypasses node filter by default)
  - ``prediction``    : Depletion / irrigation prediction update
  - ``system_status`` : System health snapshot
  - ``heartbeat``     : Periodic keepalive ping
  - ``subscribed``    : Confirmation of subscription change
  - ``unsubscribed``  : Confirmation that subscriptions were cleared
  - ``pong``          : Response to client ping
  - ``error``         : Error notification

**Client -> Server messages:**
  - ``subscribe``     : ``{"type": "subscribe", "node_ids": [...], "min_severity": "warning"}``
  - ``unsubscribe``   : ``{"type": "unsubscribe"}``
  - ``ping``          : ``{"type": "ping"}``
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

logger = structlog.get_logger("jalnetra.websocket")


# ---------------------------------------------------------------------------
# Severity ordering for subscription filtering
# ---------------------------------------------------------------------------

class _Severity(IntEnum):
    """Numeric severity levels used for alert filtering."""

    INFO = 0
    WARNING = 1
    CRITICAL = 2
    EMERGENCY = 3

    @classmethod
    def from_str(cls, s: str) -> _Severity:
        return cls[s.upper()] if s.upper() in cls.__members__ else cls.INFO


# ---------------------------------------------------------------------------
# Client connection wrapper
# ---------------------------------------------------------------------------

@dataclass
class ClientConnection:
    """Tracks a single WebSocket client, its subscriptions, and health."""

    ws: WebSocket
    subscribed_nodes: set[str] = field(default_factory=set)
    min_severity: _Severity = _Severity.INFO
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages_sent: int = 0
    messages_dropped: int = 0

    @property
    def accepts_all_nodes(self) -> bool:
        """True if the client receives data from all nodes."""
        return len(self.subscribed_nodes) == 0

    def accepts_node(self, node_id: str) -> bool:
        """Check whether this client is subscribed to *node_id*."""
        return self.accepts_all_nodes or node_id in self.subscribed_nodes

    def accepts_severity(self, severity: str) -> bool:
        """Check whether the alert severity meets the client's minimum."""
        return _Severity.from_str(severity) >= self.min_severity

    def touch(self) -> None:
        """Update last-activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# AsyncWebSocketManager
# ---------------------------------------------------------------------------

class AsyncWebSocketManager:
    """Manages WebSocket connections for real-time data streaming.

    Thread-safe via asyncio.Lock for the connection registry. Automatically
    removes stale connections when sends fail or heartbeat timeout elapses.

    Usage::

        ws_manager = AsyncWebSocketManager()
        await ws_manager.start()

        # In FastAPI WebSocket endpoint:
        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await ws_manager.connect(websocket)
            try:
                while True:
                    raw = await websocket.receive_text()
                    await ws_manager.handle_client_message(websocket, raw)
            except WebSocketDisconnect:
                await ws_manager.disconnect(websocket)

        # From any async context:
        await ws_manager.broadcast_reading("JN-DL-001", reading_dict)
        await ws_manager.broadcast_alert("JN-DL-001", "critical", "TDS too high")

        # On shutdown:
        await ws_manager.stop()
    """

    HEARTBEAT_INTERVAL_SEC: float = 30.0
    STALE_TIMEOUT_SEC: float = 120.0  # disconnect if no activity for 2 min

    def __init__(self, *, heartbeat_interval: float | None = None) -> None:
        self._clients: dict[int, ClientConnection] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_interval = heartbeat_interval or self.HEARTBEAT_INTERVAL_SEC
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

        # Aggregate stats
        self._total_connections: int = 0
        self._total_messages_broadcast: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the heartbeat background task."""
        if self._running:
            return
        self._running = True
        task = asyncio.create_task(
            self._heartbeat_loop(), name="ws-heartbeat"
        )
        self._tasks.append(task)
        await logger.ainfo(
            "WebSocket manager started",
            heartbeat_interval_sec=self._heartbeat_interval,
        )

    async def stop(self) -> None:
        """Stop heartbeat and close all connections."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.close_all()
        await logger.ainfo(
            "WebSocket manager stopped",
            total_connections=self._total_connections,
            total_messages=self._total_messages_broadcast,
        )

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """Number of currently connected clients."""
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket client.

        Args:
            ws: The FastAPI WebSocket connection to accept.
        """
        await ws.accept()
        client = ClientConnection(ws=ws)
        async with self._lock:
            self._clients[id(ws)] = client
            self._total_connections += 1

        # Send welcome message
        await self._send(ws, {
            "type": "system_status",
            "message": "Connected to JalNetra real-time feed",
            "timestamp": _utcnow_iso(),
            "client_count": len(self._clients),
        })

        await logger.ainfo(
            "WebSocket client connected",
            client_id=id(ws),
            total_clients=len(self._clients),
        )

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket client from the registry.

        Args:
            ws: The WebSocket connection to remove.
        """
        async with self._lock:
            client = self._clients.pop(id(ws), None)

        if client:
            now = datetime.now(timezone.utc)
            uptime = (now - client.connected_at).total_seconds()
            await logger.ainfo(
                "WebSocket client disconnected",
                client_id=id(ws),
                uptime_sec=round(uptime, 1),
                messages_sent=client.messages_sent,
                total_clients=len(self._clients),
            )

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        ws: WebSocket,
        node_ids: list[str],
        min_severity: str | None = None,
    ) -> None:
        """Update a client's node and severity subscriptions.

        Args:
            ws: The WebSocket connection.
            node_ids: List of node_ids to subscribe to. Empty = all nodes.
            min_severity: Minimum alert severity to receive (info/warning/critical).
        """
        async with self._lock:
            client = self._clients.get(id(ws))
            if not client:
                return
            client.subscribed_nodes = set(node_ids) if node_ids else set()
            if min_severity:
                client.min_severity = _Severity.from_str(min_severity)
            client.touch()

        await self._send(ws, {
            "type": "subscribed",
            "node_ids": node_ids or [],
            "min_severity": client.min_severity.name if client else "INFO",
            "timestamp": _utcnow_iso(),
        })

        await logger.adebug(
            "Client subscribed",
            client_id=id(ws),
            node_ids=node_ids,
            min_severity=min_severity,
        )

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Clear all subscriptions for a client (receive everything).

        Args:
            ws: The WebSocket connection.
        """
        async with self._lock:
            client = self._clients.get(id(ws))
            if client:
                client.subscribed_nodes.clear()
                client.min_severity = _Severity.INFO
                client.touch()

        await self._send(ws, {
            "type": "unsubscribed",
            "timestamp": _utcnow_iso(),
        })

    # ------------------------------------------------------------------
    # Client message handling
    # ------------------------------------------------------------------

    async def handle_client_message(self, ws: WebSocket, raw: str) -> None:
        """Parse and dispatch an incoming client message.

        Supported message types:
          - subscribe: {"type": "subscribe", "node_ids": [...], "min_severity": "warning"}
          - unsubscribe: {"type": "unsubscribe"}
          - ping: {"type": "ping"}

        Args:
            ws: The WebSocket connection.
            raw: Raw JSON string received from the client.
        """
        # Track activity
        async with self._lock:
            client = self._clients.get(id(ws))
            if client:
                client.touch()

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(ws, {"type": "error", "message": "Invalid JSON"})
            return

        msg_type = msg.get("type", "")

        if msg_type == "subscribe":
            await self.subscribe(
                ws,
                node_ids=msg.get("node_ids", []),
                min_severity=msg.get("min_severity"),
            )
        elif msg_type == "unsubscribe":
            await self.unsubscribe(ws)
        elif msg_type == "ping":
            await self._send(ws, {"type": "pong", "timestamp": _utcnow_iso()})
        else:
            await self._send(ws, {
                "type": "error",
                "message": f"Unknown message type: {msg_type}",
            })

    # ------------------------------------------------------------------
    # Broadcast: readings
    # ------------------------------------------------------------------

    async def broadcast_reading(
        self, node_id: str, data: dict[str, Any]
    ) -> int:
        """Send a new sensor reading to all clients subscribed to this node.

        The message is only sent to clients that have subscribed to the
        specific node_id, or clients with no subscription filter.

        Args:
            node_id: The sensor node that produced the reading.
            data: The reading data dict.

        Returns:
            Number of clients the message was sent to.
        """
        message = {
            "type": "reading",
            "node_id": node_id,
            "data": data,
            "timestamp": _utcnow_iso(),
        }
        return await self._broadcast(message, node_id=node_id, severity=None)

    # ------------------------------------------------------------------
    # Broadcast: alerts
    # ------------------------------------------------------------------

    async def broadcast_alert(
        self,
        node_id: str,
        severity: str,
        message: str,
        alert_id: int | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Send an alert to clients whose severity filter permits it.

        Alerts bypass the node_id filter -- every client receives alerts
        as long as their severity threshold is met, because alerts are
        safety-critical.

        Args:
            node_id: The sensor node that triggered the alert.
            severity: Alert severity (info, warning, critical).
            message: Human-readable alert message.
            alert_id: Optional database alert ID.
            details: Optional additional alert details.

        Returns:
            Number of clients the alert was sent to.
        """
        msg = {
            "type": "alert",
            "node_id": node_id,
            "severity": severity,
            "message": message,
            "alert_id": alert_id,
            "details": details or {},
            "timestamp": _utcnow_iso(),
        }
        # node_id=None so that node filter is bypassed;
        # severity is checked instead.
        return await self._broadcast(msg, node_id=None, severity=severity)

    # ------------------------------------------------------------------
    # Broadcast: predictions
    # ------------------------------------------------------------------

    async def broadcast_prediction(
        self,
        node_id: str,
        prediction_type: str,
        data: dict[str, Any],
    ) -> int:
        """Send a prediction update to subscribed clients.

        Args:
            node_id: Sensor node the prediction is for.
            prediction_type: Type of prediction (depletion, irrigation).
            data: Prediction data dict.

        Returns:
            Number of clients the message was sent to.
        """
        message = {
            "type": "prediction",
            "node_id": node_id,
            "prediction_type": prediction_type,
            "data": data,
            "timestamp": _utcnow_iso(),
        }
        return await self._broadcast(message, node_id=node_id, severity=None)

    # ------------------------------------------------------------------
    # Broadcast: system status
    # ------------------------------------------------------------------

    async def broadcast_system_status(
        self, status: dict[str, Any]
    ) -> int:
        """Send system status update to all connected clients.

        Args:
            status: System status dict (uptime, node count, etc.).

        Returns:
            Number of clients the message was sent to.
        """
        msg = {
            "type": "system_status",
            **status,
            "timestamp": _utcnow_iso(),
        }
        return await self._broadcast(msg, node_id=None, severity=None)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self) -> int:
        """Send a heartbeat message to all connected clients.

        Returns:
            Number of clients reached.
        """
        msg = {
            "type": "heartbeat",
            "timestamp": _utcnow_iso(),
            "clients": self.client_count,
        }
        return await self._broadcast(msg, node_id=None, severity=None)

    # ------------------------------------------------------------------
    # Internal broadcast engine
    # ------------------------------------------------------------------

    async def _broadcast(
        self,
        message: dict[str, Any],
        *,
        node_id: str | None,
        severity: str | None,
    ) -> int:
        """Internal broadcast with per-client filtering.

        Time complexity: O(n) where n = number of connected clients.

        - If *node_id* is set, only clients subscribed to that node receive it.
        - If *severity* is set, only clients whose min_severity threshold is met.
        - If both are None, message goes to everyone.

        Returns:
            Number of clients successfully reached.
        """
        frame = json.dumps(message, default=str)
        stale: list[int] = []
        sent_count = 0

        # Snapshot client list under lock
        async with self._lock:
            clients = list(self._clients.items())

        for ws_id, client in clients:
            # Node-id filter
            if node_id is not None and not client.accepts_node(node_id):
                continue
            # Severity filter (for alerts)
            if severity is not None and not client.accepts_severity(severity):
                continue

            try:
                await client.ws.send_text(frame)
                client.messages_sent += 1
                sent_count += 1
            except Exception:
                stale.append(ws_id)
                client.messages_dropped += 1

        # Remove stale connections
        if stale:
            async with self._lock:
                for ws_id in stale:
                    removed = self._clients.pop(ws_id, None)
                    if removed:
                        await logger.adebug(
                            "Removed stale WebSocket client",
                            client_id=ws_id,
                            messages_sent=removed.messages_sent,
                            messages_dropped=removed.messages_dropped,
                        )

        self._total_messages_broadcast += 1
        return sent_count

    # ------------------------------------------------------------------
    # Send helper
    # ------------------------------------------------------------------

    async def _send(self, ws: WebSocket, data: dict[str, Any]) -> None:
        """Send a JSON message to a single client, swallowing errors."""
        try:
            await ws.send_json(data)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Heartbeat loop with stale connection pruning
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Periodically send heartbeats and prune stale connections."""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)

                # Prune stale connections (no activity for STALE_TIMEOUT_SEC)
                now = datetime.now(timezone.utc)
                stale_ids: list[int] = []

                async with self._lock:
                    for ws_id, client in self._clients.items():
                        age = (now - client.last_activity).total_seconds()
                        if age > self.STALE_TIMEOUT_SEC:
                            stale_ids.append(ws_id)

                for ws_id in stale_ids:
                    async with self._lock:
                        client = self._clients.pop(ws_id, None)
                    if client:
                        try:
                            await client.ws.close(
                                code=1001, reason="Stale connection"
                            )
                        except Exception:
                            pass
                        await logger.ainfo(
                            "Closed stale WebSocket connection",
                            client_id=ws_id,
                            inactive_sec=self.STALE_TIMEOUT_SEC,
                        )

                # Send heartbeat to all remaining clients
                await self.send_heartbeat()

            except asyncio.CancelledError:
                break
            except Exception:
                await logger.aexception("Heartbeat loop error")
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    async def close_all(self) -> None:
        """Close all WebSocket connections gracefully."""
        async with self._lock:
            for client in self._clients.values():
                try:
                    await client.ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
            count = len(self._clients)
            self._clients.clear()

        if count:
            await logger.ainfo(
                "Closed all WebSocket connections",
                connections_closed=count,
            )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        """Return WebSocket manager statistics."""
        now = datetime.now(timezone.utc)
        return {
            "running": self._running,
            "client_count": len(self._clients),
            "total_connections": self._total_connections,
            "total_messages_broadcast": self._total_messages_broadcast,
            "heartbeat_interval_sec": self._heartbeat_interval,
            "stale_timeout_sec": self.STALE_TIMEOUT_SEC,
            "clients": [
                {
                    "client_id": id(c.ws),
                    "subscribed_nodes": list(c.subscribed_nodes) or ["*"],
                    "min_severity": c.min_severity.name,
                    "connected_at": c.connected_at.isoformat(),
                    "last_activity": c.last_activity.isoformat(),
                    "age_sec": round((now - c.connected_at).total_seconds()),
                    "messages_sent": c.messages_sent,
                    "messages_dropped": c.messages_dropped,
                }
                for c in self._clients.values()
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
