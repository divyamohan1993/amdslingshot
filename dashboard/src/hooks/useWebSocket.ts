import { useEffect, useRef } from "react";
import { getWebSocketClient, type JalNetraWebSocket } from "../services/websocket";
import { useAppStore } from "../stores/appStore";
import type {
  WebSocketMessage,
  ReadingMessage,
  AlertMessage,
  NodeStatusMessage,
  SystemHealth,
} from "../types";

/**
 * Hook that establishes and manages the WebSocket connection.
 * Routes incoming messages to the appropriate store actions.
 *
 * Should be called once at the App level.
 */
export function useWebSocket() {
  const wsRef = useRef<JalNetraWebSocket | null>(null);
  const {
    setLatestReading,
    addAlert,
    updateNodeStatus,
    setSystemHealth,
    setWsConnectionState,
  } = useAppStore.getState();

  useEffect(() => {
    const ws = getWebSocketClient();
    wsRef.current = ws;

    // Route messages to store
    const unsubMessage = ws.onMessage((message: WebSocketMessage) => {
      switch (message.type) {
        case "reading": {
          const readingMsg = message as ReadingMessage;
          useAppStore.getState().setLatestReading(readingMsg.payload);
          break;
        }
        case "alert": {
          const alertMsg = message as AlertMessage;
          useAppStore.getState().addAlert(alertMsg.payload);
          break;
        }
        case "node_status": {
          const statusMsg = message as NodeStatusMessage;
          // Update node status in store - map to water_status if needed
          break;
        }
        case "system_health": {
          const health = message.payload as SystemHealth;
          useAppStore.getState().setSystemHealth(health);
          break;
        }
        case "heartbeat":
          // No-op, just keeping connection alive
          break;
        default:
          console.log("[WS] Unknown message type:", message.type);
      }
    });

    // Track connection state
    const unsubState = ws.onStateChange((state) => {
      useAppStore.getState().setWsConnectionState(state);
    });

    // Connect
    ws.connect();

    return () => {
      unsubMessage();
      unsubState();
      ws.disconnect();
    };
  }, []);

  return wsRef;
}
