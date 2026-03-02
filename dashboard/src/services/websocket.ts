import type { WebSocketMessage } from "../types";

// ============================================================
// WebSocket Client with Auto-Reconnect
// ============================================================

export type ConnectionState = "connecting" | "connected" | "disconnecting" | "disconnected";

export type MessageHandler = (message: WebSocketMessage) => void;
export type StateChangeHandler = (state: ConnectionState) => void;

interface WebSocketClientOptions {
  /** WebSocket URL (defaults to ws://host/ws/readings) */
  url?: string;
  /** Max reconnection attempts before giving up (0 = infinite) */
  maxRetries?: number;
  /** Initial backoff delay in ms */
  initialBackoffMs?: number;
  /** Maximum backoff delay in ms */
  maxBackoffMs?: number;
  /** Heartbeat interval in ms (sends ping to keep alive) */
  heartbeatIntervalMs?: number;
}

const DEFAULT_OPTIONS: Required<WebSocketClientOptions> = {
  url: "",
  maxRetries: 0,
  initialBackoffMs: 1000,
  maxBackoffMs: 30_000,
  heartbeatIntervalMs: 30_000,
};

export class JalNetraWebSocket {
  private ws: WebSocket | null = null;
  private options: Required<WebSocketClientOptions>;
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private _state: ConnectionState = "disconnected";
  private messageHandlers = new Set<MessageHandler>();
  private stateHandlers = new Set<StateChangeHandler>();
  private intentionalClose = false;

  constructor(options?: WebSocketClientOptions) {
    this.options = { ...DEFAULT_OPTIONS, ...options };

    // Auto-detect WebSocket URL from current host
    if (!this.options.url) {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      this.options.url = `${protocol}//${window.location.host}/ws/readings`;
    }
  }

  // ----------------------------------------------------------
  // Public API
  // ----------------------------------------------------------

  get state(): ConnectionState {
    return this._state;
  }

  connect(): void {
    if (this.ws && (this._state === "connected" || this._state === "connecting")) {
      return;
    }

    this.intentionalClose = false;
    this.setState("connecting");

    try {
      this.ws = new WebSocket(this.options.url);
      this.ws.onopen = this.handleOpen;
      this.ws.onmessage = this.handleMessage;
      this.ws.onclose = this.handleClose;
      this.ws.onerror = this.handleError;
    } catch (err) {
      console.error("[JalNetra WS] Connection error:", err);
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.setState("disconnecting");
    this.clearTimers();

    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }

    this.setState("disconnected");
  }

  /** Send a JSON message to the server */
  send(data: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn("[JalNetra WS] Cannot send - not connected");
    }
  }

  /** Subscribe to incoming messages */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => {
      this.messageHandlers.delete(handler);
    };
  }

  /** Subscribe to connection state changes */
  onStateChange(handler: StateChangeHandler): () => void {
    this.stateHandlers.add(handler);
    return () => {
      this.stateHandlers.delete(handler);
    };
  }

  // ----------------------------------------------------------
  // Internal Handlers
  // ----------------------------------------------------------

  private handleOpen = (): void => {
    console.log("[JalNetra WS] Connected");
    this.retryCount = 0;
    this.setState("connected");
    this.startHeartbeat();
  };

  private handleMessage = (event: MessageEvent): void => {
    try {
      const message: WebSocketMessage = JSON.parse(event.data);
      this.messageHandlers.forEach((handler) => handler(message));
    } catch (err) {
      console.warn("[JalNetra WS] Failed to parse message:", err);
    }
  };

  private handleClose = (event: CloseEvent): void => {
    console.log(`[JalNetra WS] Closed: ${event.code} ${event.reason}`);
    this.clearTimers();
    this.ws = null;

    if (!this.intentionalClose) {
      this.setState("disconnected");
      this.scheduleReconnect();
    }
  };

  private handleError = (event: Event): void => {
    console.error("[JalNetra WS] Error:", event);
    // onclose will fire after onerror, so reconnect logic is handled there
  };

  // ----------------------------------------------------------
  // Reconnection with Exponential Backoff
  // ----------------------------------------------------------

  private scheduleReconnect(): void {
    if (this.options.maxRetries > 0 && this.retryCount >= this.options.maxRetries) {
      console.warn("[JalNetra WS] Max retries reached, giving up");
      return;
    }

    const backoff = Math.min(
      this.options.initialBackoffMs * Math.pow(2, this.retryCount),
      this.options.maxBackoffMs,
    );
    // Add jitter (0-25% of backoff)
    const jitter = backoff * Math.random() * 0.25;
    const delay = backoff + jitter;

    console.log(
      `[JalNetra WS] Reconnecting in ${Math.round(delay)}ms (attempt ${this.retryCount + 1})`,
    );

    this.retryTimer = setTimeout(() => {
      this.retryCount++;
      this.connect();
    }, delay);
  }

  // ----------------------------------------------------------
  // Heartbeat / Keep-alive
  // ----------------------------------------------------------

  private startHeartbeat(): void {
    this.clearHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: "heartbeat", timestamp: new Date().toISOString() });
    }, this.options.heartbeatIntervalMs);
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearHeartbeat();
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  // ----------------------------------------------------------
  // State Management
  // ----------------------------------------------------------

  private setState(state: ConnectionState): void {
    if (this._state === state) return;
    this._state = state;
    this.stateHandlers.forEach((handler) => handler(state));
  }
}

// Singleton instance
let instance: JalNetraWebSocket | null = null;

export function getWebSocketClient(options?: WebSocketClientOptions): JalNetraWebSocket {
  if (!instance) {
    instance = new JalNetraWebSocket(options);
  }
  return instance;
}
