// ============================================================
// JalNetra Type Definitions
// ============================================================

/** Geographic coordinates */
export interface LatLng {
  lat: number;
  lng: number;
}

/** Water quality status tiers */
export type WaterStatus = "safe" | "warning" | "danger" | "critical";

/** Alert severity levels */
export type AlertSeverity = "info" | "warning" | "danger" | "critical";

/** Alert state lifecycle */
export type AlertState = "active" | "acknowledged" | "resolved";

/** Sensor node operational status */
export type NodeStatus = "online" | "offline" | "maintenance" | "error";

// ============================================================
// Core Sensor Types
// ============================================================

export interface SensorNode {
  id: string;
  name: string;
  location: LatLng;
  village: string;
  district: string;
  state: string;
  status: NodeStatus;
  battery_level: number; // 0-100%
  signal_strength: number; // dBm, e.g. -70
  firmware_version: string;
  installed_at: string; // ISO date
  last_seen: string; // ISO date
  water_status: WaterStatus;
  tags: string[];
}

export interface SensorReading {
  id: string;
  node_id: string;
  timestamp: string; // ISO date
  tds: number; // ppm
  ph: number; // 0-14
  turbidity: number; // NTU
  flow_rate: number; // L/min
  water_level: number; // meters
  temperature: number; // Celsius
  dissolved_oxygen: number; // mg/L
  water_quality_score: number; // 0-100 computed
  status: WaterStatus;
  is_anomaly: boolean;
}

export interface SensorReadingHistory {
  node_id: string;
  readings: SensorReading[];
  start_time: string;
  end_time: string;
}

// ============================================================
// Alerts
// ============================================================

export interface Alert {
  id: string;
  node_id: string;
  node_name: string;
  type: string; // e.g. "high_tds", "low_ph", "anomaly_detected"
  severity: AlertSeverity;
  state: AlertState;
  title: string;
  message: string;
  value: number;
  threshold: number;
  parameter: string; // which sensor parameter triggered
  created_at: string;
  acknowledged_at?: string;
  resolved_at?: string;
  acknowledged_by?: string;
}

// ============================================================
// Predictions / ML
// ============================================================

export interface Prediction {
  id: string;
  node_id: string;
  parameter: string;
  forecast_date: string;
  predicted_value: number;
  confidence_lower: number;
  confidence_upper: number;
  confidence_level: number; // 0-1
  model_version: string;
  created_at: string;
}

export interface AnomalyRecord {
  id: string;
  node_id: string;
  node_name: string;
  timestamp: string;
  parameter: string;
  actual_value: number;
  expected_value: number;
  deviation: number;
  severity: AlertSeverity;
  description: string;
}

export interface ModelMetrics {
  model_name: string;
  version: string;
  mae: number;
  rmse: number;
  r2_score: number;
  mape: number;
  last_trained: string;
  training_samples: number;
}

// ============================================================
// Irrigation
// ============================================================

export interface IrrigationSchedule {
  id: string;
  node_id: string;
  date: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  recommended_volume_liters: number;
  crop_type: string;
  status: "scheduled" | "completed" | "skipped" | "in_progress";
  water_saved_percent: number;
}

// ============================================================
// WebSocket Messages
// ============================================================

export type WebSocketMessageType =
  | "reading"
  | "alert"
  | "node_status"
  | "prediction"
  | "system_health"
  | "heartbeat";

export interface WebSocketMessage {
  type: WebSocketMessageType;
  timestamp: string;
  payload: unknown;
}

export interface ReadingMessage extends WebSocketMessage {
  type: "reading";
  payload: SensorReading;
}

export interface AlertMessage extends WebSocketMessage {
  type: "alert";
  payload: Alert;
}

export interface NodeStatusMessage extends WebSocketMessage {
  type: "node_status";
  payload: {
    node_id: string;
    status: NodeStatus;
    battery_level: number;
    signal_strength: number;
  };
}

// ============================================================
// System Health
// ============================================================

export interface SystemHealth {
  status: "healthy" | "degraded" | "down";
  total_nodes: number;
  online_nodes: number;
  offline_nodes: number;
  active_alerts: number;
  critical_alerts: number;
  avg_water_quality: number;
  data_freshness_seconds: number;
  api_latency_ms: number;
  uptime_hours: number;
  last_updated: string;
}

// ============================================================
// Water Quality Thresholds (BIS / JJM Standards)
// ============================================================

export interface WaterQualityThresholds {
  tds: { safe: number; warning: number; danger: number }; // ppm
  ph: { min_safe: number; max_safe: number; min_danger: number; max_danger: number };
  turbidity: { safe: number; warning: number; danger: number }; // NTU
  dissolved_oxygen: { safe: number; warning: number; danger: number }; // mg/L
  temperature: { min_safe: number; max_safe: number };
}

export const DEFAULT_THRESHOLDS: WaterQualityThresholds = {
  tds: { safe: 300, warning: 500, danger: 2000 },
  ph: { min_safe: 6.5, max_safe: 8.5, min_danger: 4.0, max_danger: 11.0 },
  turbidity: { safe: 1, warning: 5, danger: 10 },
  dissolved_oxygen: { safe: 6, warning: 4, danger: 2 },
  temperature: { min_safe: 10, max_safe: 35 },
};

// ============================================================
// Report Types
// ============================================================

export interface ComplianceReport {
  id: string;
  title: string;
  period_start: string;
  period_end: string;
  generated_at: string;
  total_readings: number;
  compliant_readings: number;
  compliance_percentage: number;
  violations: ComplianceViolation[];
  summary: string;
}

export interface ComplianceViolation {
  parameter: string;
  count: number;
  max_value: number;
  threshold: number;
  node_ids: string[];
}

// ============================================================
// API Response Wrappers
// ============================================================

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface ApiError {
  detail: string;
  status_code: number;
}

// ============================================================
// Time Range for queries
// ============================================================

export type TimeRange = "1h" | "6h" | "24h" | "7d" | "30d" | "90d";
