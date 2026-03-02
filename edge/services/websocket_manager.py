"""WebSocket connection manager for real-time sensor data streaming.

Manages multiple concurrent WebSocket connections with per-client
subscription filtering, heartbeats, and graceful cleanup.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("jalnetra.websocket")


class ClientConnection:
    """Tracks a single WebSocket client and its subscriptions."""

    __slots__ = ("ws", "subscribed_nodes", "connected_at", "last_ping")

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.subscribed_nodes: set[str] = set()
        self.connected_at = datetime.now(timezone.utc)
        self.last_ping = self.connected_at

    @property
    def accepts_all(self) -> bool:
        return len(self.subscribed_nodes) == 0

    def accepts_node(self, node_id: str) -> bool:
        return self.accepts_all or node_id in self.subscribed_nodes


class AsyncWebSocketManager:
    """Manage WebSocket connections and broadcast messages."""

    def __init__(self) -> None:
        self._clients: dict[int, ClientConnection] = {}
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket client."""
        await ws.accept()
        client = ClientConnection(ws)
        async with self._lock:
            self._clients[id(ws)] = client
        logger.info("WebSocket client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket client."""
        async with self._lock:
            self._clients.pop(id(ws), None)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._clients))

    async def subscribe(self, ws: WebSocket, node_ids: list[str]) -> None:
        """Subscribe a client to specific node updates."""
        async with self._lock:
            client = self._clients.get(id(ws))
            if client:
                client.subscribed_nodes = set(node_ids)
                await self._send(ws, {
                    "type": "subscribed",
                    "node_ids": list(client.subscribed_nodes),
                })

    async def unsubscribe(self, ws: WebSocket) -> None:
        """Clear all subscriptions for a client."""
        async with self._lock:
            client = self._clients.get(id(ws))
            if client:
                client.subscribed_nodes.clear()
                await self._send(ws, {"type": "unsubscribed"})

    async def broadcast_reading(self, node_id: str, data: dict[str, Any]) -> None:
        """Send a new reading to all clients subscribed to this node.

        Time complexity: O(n) where n is the number of connected clients.
        """
        message = {
            "type": "reading",
            "node_id": node_id,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._broadcast(message, node_id=node_id)

    async def broadcast_alert(
        self,
        node_id: str,
        severity: str,
        message: str,
        alert_id: int | None = None,
    ) -> None:
        """Send an alert to all connected clients (alerts bypass node filter)."""
        msg = {
            "type": "alert",
            "node_id": node_id,
            "severity": severity,
            "message": message,
            "alert_id": alert_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._broadcast(msg, node_id=None)  # Alerts go to everyone

    async def broadcast_system_status(self, status: dict[str, Any]) -> None:
        """Send system status to all clients."""
        msg = {"type": "system_status", **status, "timestamp": datetime.now(timezone.utc).isoformat()}
        await self._broadcast(msg, node_id=None)

    async def send_heartbeat(self) -> None:
        """Send heartbeat to all connected clients."""
        msg = {
            "type": "heartbeat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "clients": self.client_count,
        }
        await self._broadcast(msg, node_id=None)

    async def _broadcast(self, message: dict[str, Any], node_id: str | None) -> None:
        """Internal broadcast with filtering. O(n) clients."""
        stale: list[int] = []
        frame = json.dumps(message)

        async with self._lock:
            clients = list(self._clients.items())

        for ws_id, client in clients:
            if node_id is not None and not client.accepts_node(node_id):
                continue
            try:
                await client.ws.send_text(frame)
            except Exception:
                stale.append(ws_id)

        if stale:
            async with self._lock:
                for ws_id in stale:
                    self._clients.pop(ws_id, None)

    async def _send(self, ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            await ws.send_json(data)
        except Exception:
            pass

    async def close_all(self) -> None:
        """Close all connections gracefully."""
        async with self._lock:
            for client in self._clients.values():
                try:
                    await client.ws.close(code=1001)
                except Exception:
                    pass
            self._clients.clear()
