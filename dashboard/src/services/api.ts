import axios, { type AxiosError, type AxiosInstance } from "axios";
import type {
  SensorNode,
  SensorReading,
  SensorReadingHistory,
  Alert,
  AlertState,
  Prediction,
  AnomalyRecord,
  ModelMetrics,
  IrrigationSchedule,
  SystemHealth,
  ComplianceReport,
  PaginatedResponse,
  TimeRange,
} from "../types";

// ============================================================
// Axios Instance
// ============================================================

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor - attach auth token if available
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("jalnetra_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// Response interceptor - standardized error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail ?? error.message;

    if (status === 401) {
      localStorage.removeItem("jalnetra_token");
      // Could redirect to login if auth is implemented
    }

    if (status === 503) {
      console.warn("[JalNetra API] Service unavailable:", detail);
    }

    console.error(`[JalNetra API] ${status ?? "NETWORK"}: ${detail}`);
    return Promise.reject(error);
  },
);

// ============================================================
// Sensor Nodes
// ============================================================

export async function getNodes(): Promise<SensorNode[]> {
  const { data } = await api.get<SensorNode[]>("/nodes");
  return data;
}

export async function getNode(nodeId: string): Promise<SensorNode> {
  const { data } = await api.get<SensorNode>(`/nodes/${nodeId}`);
  return data;
}

// ============================================================
// Sensor Readings
// ============================================================

export async function getLatestReadings(): Promise<SensorReading[]> {
  const { data } = await api.get<SensorReading[]>("/readings/latest");
  return data;
}

export async function getNodeReadings(
  nodeId: string,
  timeRange: TimeRange = "24h",
): Promise<SensorReadingHistory> {
  const { data } = await api.get<SensorReadingHistory>(
    `/readings/${nodeId}`,
    { params: { range: timeRange } },
  );
  return data;
}

export async function getReadingsHistory(
  timeRange: TimeRange = "7d",
  parameter?: string,
): Promise<SensorReadingHistory> {
  const { data } = await api.get<SensorReadingHistory>("/readings/history", {
    params: { range: timeRange, parameter },
  });
  return data;
}

// ============================================================
// Alerts
// ============================================================

export async function getAlerts(params?: {
  state?: AlertState;
  severity?: string;
  node_id?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<Alert>> {
  const { data } = await api.get<PaginatedResponse<Alert>>("/alerts", {
    params,
  });
  return data;
}

export async function getActiveAlerts(): Promise<Alert[]> {
  const { data } = await api.get<Alert[]>("/alerts/active");
  return data;
}

export async function acknowledgeAlert(alertId: string): Promise<Alert> {
  const { data } = await api.put<Alert>(`/alerts/${alertId}/acknowledge`);
  return data;
}

export async function resolveAlert(alertId: string): Promise<Alert> {
  const { data } = await api.put<Alert>(`/alerts/${alertId}/resolve`);
  return data;
}

// ============================================================
// Predictions
// ============================================================

export async function getPredictions(
  nodeId: string,
  parameter: string = "water_level",
  days: number = 30,
): Promise<Prediction[]> {
  const { data } = await api.get<Prediction[]>("/predictions", {
    params: { node_id: nodeId, parameter, days },
  });
  return data;
}

export async function getAnomalies(params?: {
  node_id?: string;
  page?: number;
  per_page?: number;
}): Promise<PaginatedResponse<AnomalyRecord>> {
  const { data } = await api.get<PaginatedResponse<AnomalyRecord>>(
    "/predictions/anomalies",
    { params },
  );
  return data;
}

export async function getModelMetrics(): Promise<ModelMetrics[]> {
  const { data } = await api.get<ModelMetrics[]>("/predictions/model-metrics");
  return data;
}

// ============================================================
// Irrigation
// ============================================================

export async function getIrrigationSchedule(
  nodeId: string,
  days: number = 7,
): Promise<IrrigationSchedule[]> {
  const { data } = await api.get<IrrigationSchedule[]>(
    `/irrigation/schedule/${nodeId}`,
    { params: { days } },
  );
  return data;
}

// ============================================================
// System Health
// ============================================================

export async function getSystemHealth(): Promise<SystemHealth> {
  const { data } = await api.get<SystemHealth>("/system/health");
  return data;
}

// ============================================================
// Reports / JJM Compliance
// ============================================================

export async function getComplianceReports(): Promise<ComplianceReport[]> {
  const { data } = await api.get<ComplianceReport[]>("/reports/compliance");
  return data;
}

export async function generateComplianceReport(params: {
  period_start: string;
  period_end: string;
  node_ids?: string[];
}): Promise<ComplianceReport> {
  const { data } = await api.post<ComplianceReport>(
    "/reports/compliance/generate",
    params,
  );
  return data;
}

export async function exportReport(
  reportId: string,
  format: "pdf" | "csv" | "xlsx" = "pdf",
): Promise<Blob> {
  const { data } = await api.get(`/reports/${reportId}/export`, {
    params: { format },
    responseType: "blob",
  });
  return data;
}

// ============================================================
// Export default instance for direct use
// ============================================================

export default api;
