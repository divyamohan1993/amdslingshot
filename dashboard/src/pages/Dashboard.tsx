import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppStore } from "../stores/appStore";
import SensorCard from "../components/SensorCard";
import WaterQualityGauge from "../components/WaterQualityGauge";
import MapView from "../components/MapView";
import StatusBadge from "../components/StatusBadge";
import TrendChart, { type TrendChartDataPoint } from "../components/TrendChart";
import type { SensorNode, SensorReading, Alert, WaterStatus } from "../types";

// ============================================================
// Demo data for rendering when API is unavailable
// ============================================================

const DEMO_NODES: SensorNode[] = [
  {
    id: "node-01", name: "Rampur Well #1", village: "Rampur", district: "Varanasi", state: "UP",
    location: { lat: 25.32, lng: 82.99 }, status: "online", battery_level: 87, signal_strength: -62,
    firmware_version: "2.1.0", installed_at: "2025-06-15T00:00:00Z", last_seen: new Date().toISOString(),
    water_status: "safe", tags: ["primary"],
  },
  {
    id: "node-02", name: "Khajuri Pump Station", village: "Khajuri", district: "Varanasi", state: "UP",
    location: { lat: 25.28, lng: 83.01 }, status: "online", battery_level: 62, signal_strength: -74,
    firmware_version: "2.1.0", installed_at: "2025-07-01T00:00:00Z", last_seen: new Date().toISOString(),
    water_status: "warning", tags: ["pump"],
  },
  {
    id: "node-03", name: "Sultanpur Borewell", village: "Sultanpur", district: "Varanasi", state: "UP",
    location: { lat: 25.35, lng: 82.95 }, status: "online", battery_level: 93, signal_strength: -55,
    firmware_version: "2.0.8", installed_at: "2025-05-20T00:00:00Z", last_seen: new Date().toISOString(),
    water_status: "safe", tags: ["borewell"],
  },
  {
    id: "node-04", name: "Lohta Reservoir", village: "Lohta", district: "Varanasi", state: "UP",
    location: { lat: 25.38, lng: 83.05 }, status: "online", battery_level: 41, signal_strength: -81,
    firmware_version: "2.1.0", installed_at: "2025-08-10T00:00:00Z", last_seen: new Date().toISOString(),
    water_status: "danger", tags: ["reservoir"],
  },
  {
    id: "node-05", name: "Chaukaghat Tank", village: "Chaukaghat", district: "Varanasi", state: "UP",
    location: { lat: 25.30, lng: 82.97 }, status: "offline", battery_level: 12, signal_strength: -90,
    firmware_version: "2.0.5", installed_at: "2025-04-01T00:00:00Z", last_seen: "2025-12-28T10:00:00Z",
    water_status: "critical", tags: ["tank"],
  },
];

function makeDemoReading(nodeId: string, status: WaterStatus): SensorReading {
  const base = {
    safe: { tds: 180, ph: 7.2, turbidity: 0.8, flow_rate: 12.5, water_level: 8.3, temperature: 24, dissolved_oxygen: 7.1, water_quality_score: 92 },
    warning: { tds: 420, ph: 6.3, turbidity: 3.8, flow_rate: 8.1, water_level: 5.2, temperature: 27, dissolved_oxygen: 5.2, water_quality_score: 64 },
    danger: { tds: 780, ph: 5.5, turbidity: 8.2, flow_rate: 3.2, water_level: 2.1, temperature: 31, dissolved_oxygen: 3.1, water_quality_score: 35 },
    critical: { tds: 1200, ph: 4.1, turbidity: 15.6, flow_rate: 0.4, water_level: 0.8, temperature: 34, dissolved_oxygen: 1.5, water_quality_score: 12 },
  }[status];

  return {
    id: `reading-${nodeId}`,
    node_id: nodeId,
    timestamp: new Date().toISOString(),
    ...base,
    status,
    is_anomaly: status === "critical",
  };
}

const DEMO_READINGS: SensorReading[] = DEMO_NODES.map((n) => makeDemoReading(n.id, n.water_status));

const DEMO_ALERTS: Alert[] = [
  {
    id: "alert-01", node_id: "node-04", node_name: "Lohta Reservoir", type: "high_tds",
    severity: "danger", state: "active", title: "High TDS Level Detected",
    message: "TDS reading at 780 ppm exceeds the 500 ppm warning threshold",
    value: 780, threshold: 500, parameter: "tds",
    created_at: new Date(Date.now() - 1800_000).toISOString(),
  },
  {
    id: "alert-02", node_id: "node-05", node_name: "Chaukaghat Tank", type: "node_offline",
    severity: "critical", state: "active", title: "Sensor Node Offline",
    message: "Node has not reported in over 24 hours. Battery critically low at 12%.",
    value: 12, threshold: 20, parameter: "battery",
    created_at: new Date(Date.now() - 86400_000).toISOString(),
  },
  {
    id: "alert-03", node_id: "node-02", node_name: "Khajuri Pump Station", type: "low_ph",
    severity: "warning", state: "active", title: "Low pH Warning",
    message: "pH reading at 6.3 is below the recommended 6.5 minimum",
    value: 6.3, threshold: 6.5, parameter: "ph",
    created_at: new Date(Date.now() - 3600_000).toISOString(),
  },
];

function generateTrendData(baseValue: number, variance: number, days: number): TrendChartDataPoint[] {
  const points: TrendChartDataPoint[] = [];
  const now = Date.now();
  for (let i = days; i >= 0; i--) {
    const ts = new Date(now - i * 86400_000).toISOString();
    const noise = (Math.random() - 0.5) * variance;
    points.push({ timestamp: ts, value: +(baseValue + noise).toFixed(2) });
  }
  return points;
}

// ============================================================
// Dashboard Component
// ============================================================

export default function Dashboard() {
  const { t } = useTranslation();
  const storeNodes = useAppStore((s) => s.nodes);
  const storeReadings = useAppStore((s) => s.latestReadings);
  const storeAlerts = useAppStore((s) => s.alerts);
  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const setSelectedNode = useAppStore((s) => s.setSelectedNode);

  // Use store data if available, otherwise demo data
  const nodes = storeNodes.length > 0 ? storeNodes : DEMO_NODES;
  const readingsMap = storeReadings.size > 0
    ? storeReadings
    : new Map(DEMO_READINGS.map((r) => [r.node_id, r]));
  const alerts = storeAlerts.length > 0 ? storeAlerts : DEMO_ALERTS;
  const readings = Array.from(readingsMap.values());

  // Populate store with demo data on first render if empty
  useEffect(() => {
    if (storeNodes.length === 0) {
      useAppStore.getState().setNodes(DEMO_NODES);
      useAppStore.getState().setLatestReadings(DEMO_READINGS);
      useAppStore.getState().setAlerts(DEMO_ALERTS);
    }
  }, [storeNodes.length]);

  // Aggregate stats
  const onlineNodes = nodes.filter((n) => n.status === "online").length;
  const avgQuality = readings.length > 0
    ? readings.reduce((sum, r) => sum + r.water_quality_score, 0) / readings.length
    : 0;
  const overallStatus: WaterStatus =
    avgQuality >= 80 ? "safe" : avgQuality >= 50 ? "warning" : avgQuality >= 25 ? "danger" : "critical";

  // Latest reading for selected node or first node
  const selectedReading = readingsMap.get(selectedNodeId ?? nodes[0]?.id ?? "");

  // Sparkline data (simulated 7-day)
  const tdsSparkline = generateTrendData(selectedReading?.tds ?? 200, 60, 7).map((p) => p.value);
  const phSparkline = generateTrendData(selectedReading?.ph ?? 7.0, 0.4, 7).map((p) => p.value);
  const turbSparkline = generateTrendData(selectedReading?.turbidity ?? 2, 1.5, 7).map((p) => p.value);
  const flowSparkline = generateTrendData(selectedReading?.flow_rate ?? 10, 3, 7).map((p) => p.value);
  const levelSparkline = generateTrendData(selectedReading?.water_level ?? 6, 1, 7).map((p) => p.value);

  // 7-day trend chart data
  const trendData = generateTrendData(avgQuality, 8, 7);

  return (
    <div className="space-y-6">
      {/* Page title */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">
            {t("dashboard.title")}
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Real-time monitoring across {nodes.length} sensor nodes
          </p>
        </div>
        <div className="hidden sm:flex items-center gap-2">
          <span className="text-xs text-slate-500">Last updated:</span>
          <span className="text-xs text-slate-400 font-mono">
            {new Date().toLocaleTimeString("en-IN")}
          </span>
        </div>
      </div>

      {/* Summary stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            {t("dashboard.totalNodes")}
          </div>
          <div className="text-3xl font-bold text-slate-100">{nodes.length}</div>
          <div className="text-xs text-safe-400 mt-1">
            {onlineNodes} {t("status.online")}
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            {t("dashboard.activeAlerts")}
          </div>
          <div className={`text-3xl font-bold ${alerts.length > 0 ? "text-danger-400" : "text-slate-100"}`}>
            {alerts.filter((a) => a.state === "active").length}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {alerts.filter((a) => a.severity === "critical").length} critical
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            Avg Quality Score
          </div>
          <div className={`text-3xl font-bold ${
            overallStatus === "safe" ? "text-safe-400" :
            overallStatus === "warning" ? "text-warn-400" :
            "text-danger-400"
          }`}>
            {avgQuality.toFixed(0)}%
          </div>
          <StatusBadge status={overallStatus} size="sm" />
        </div>
        <div className="card flex items-center justify-center">
          <WaterQualityGauge score={avgQuality} status={overallStatus} size={120} />
        </div>
      </div>

      {/* Map + Alerts side by side */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Map - takes 2/3 */}
        <div className="xl:col-span-2">
          <MapView
            nodes={nodes}
            readings={readingsMap}
            selectedNodeId={selectedNodeId}
            onNodeSelect={setSelectedNode}
            center={[25.32, 83.0]}
            zoom={12}
            height="h-80 lg:h-96"
          />
        </div>

        {/* Active Alerts Panel - takes 1/3 */}
        <div className="panel max-h-96 flex flex-col">
          <div className="panel-header">
            <h2 className="text-sm font-semibold text-slate-200">
              {t("dashboard.activeAlerts")}
            </h2>
            <span className="badge-danger text-[10px]">
              {alerts.filter((a) => a.state === "active").length}
            </span>
          </div>
          <div className="panel-body flex-1 overflow-y-auto space-y-2">
            {alerts
              .filter((a) => a.state === "active")
              .map((alert) => (
                <div
                  key={alert.id}
                  className={`p-3 rounded-lg border ${
                    alert.severity === "critical"
                      ? "bg-critical-900/20 border-critical-700/30"
                      : alert.severity === "danger"
                        ? "bg-danger-900/20 border-danger-700/30"
                        : "bg-warn-900/20 border-warn-700/30"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <StatusBadge status={alert.severity} size="sm" />
                        <span className="text-xs text-slate-500 truncate">
                          {alert.node_name}
                        </span>
                      </div>
                      <p className="text-sm text-slate-200 font-medium truncate">
                        {alert.title}
                      </p>
                      <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">
                        {alert.message}
                      </p>
                    </div>
                  </div>
                  <div className="text-[10px] text-slate-600 mt-2">
                    {new Date(alert.created_at).toLocaleString("en-IN")}
                  </div>
                </div>
              ))}
            {alerts.filter((a) => a.state === "active").length === 0 && (
              <div className="text-center text-sm text-slate-500 py-8">
                {t("alerts.noAlerts")}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Sensor reading cards */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200 mb-4">
          {t("dashboard.waterQuality")}
          {selectedNodeId && (
            <span className="text-sm text-slate-500 ml-2">
              — {nodes.find((n) => n.id === selectedNodeId)?.name ?? selectedNodeId}
            </span>
          )}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          <SensorCard
            label={t("sensors.tds")}
            value={selectedReading?.tds ?? 0}
            unit="ppm"
            status={selectedReading?.tds && selectedReading.tds > 500 ? "warning" : selectedReading?.tds && selectedReading.tds > 2000 ? "danger" : "safe"}
            sparklineData={tdsSparkline}
          />
          <SensorCard
            label={t("sensors.ph")}
            value={selectedReading?.ph ?? 0}
            unit=""
            status={
              selectedReading?.ph && (selectedReading.ph < 6.5 || selectedReading.ph > 8.5)
                ? "warning"
                : "safe"
            }
            sparklineData={phSparkline}
          />
          <SensorCard
            label={t("sensors.turbidity")}
            value={selectedReading?.turbidity ?? 0}
            unit="NTU"
            status={selectedReading?.turbidity && selectedReading.turbidity > 5 ? "warning" : "safe"}
            sparklineData={turbSparkline}
          />
          <SensorCard
            label={t("sensors.flow")}
            value={selectedReading?.flow_rate ?? 0}
            unit="L/min"
            status="safe"
            sparklineData={flowSparkline}
          />
          <SensorCard
            label={t("sensors.level")}
            value={selectedReading?.water_level ?? 0}
            unit="m"
            status={selectedReading?.water_level && selectedReading.water_level < 2 ? "danger" : "safe"}
            sparklineData={levelSparkline}
          />
        </div>
      </div>

      {/* 7-day trend + Readings table */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <TrendChart
          data={trendData}
          title={t("dashboard.trendLast7Days")}
          color="#22d3ee"
          unit="%"
          height={240}
        />

        {/* Readings table */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">
              {t("dashboard.recentReadings")}
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800">
                  <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase">Node</th>
                  <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-500 uppercase">TDS</th>
                  <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-500 uppercase">pH</th>
                  <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-500 uppercase">Turb.</th>
                  <th className="px-4 py-2.5 text-right text-xs font-medium text-slate-500 uppercase">Level</th>
                  <th className="px-4 py-2.5 text-center text-xs font-medium text-slate-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody>
                {readings.map((r) => {
                  const node = nodes.find((n) => n.id === r.node_id);
                  return (
                    <tr
                      key={r.id}
                      className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer transition-colors"
                      onClick={() => setSelectedNode(r.node_id)}
                    >
                      <td className="px-4 py-2.5 text-slate-200 font-medium truncate max-w-[150px]">
                        {node?.name ?? r.node_id}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                        {r.tds.toFixed(0)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                        {r.ph.toFixed(1)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                        {r.turbidity.toFixed(1)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                        {r.water_level.toFixed(1)}m
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        <StatusBadge status={r.status} size="sm" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
