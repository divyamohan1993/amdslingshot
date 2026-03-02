import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { useAppStore } from "../stores/appStore";
import StatusBadge from "../components/StatusBadge";
import type { Alert, AlertSeverity, AlertState } from "../types";

// ============================================================
// Extended demo alerts for the Alerts page
// ============================================================

const EXTENDED_ALERTS: Alert[] = [
  {
    id: "alert-01", node_id: "node-04", node_name: "Lohta Reservoir", type: "high_tds",
    severity: "danger", state: "active", title: "High TDS Level Detected",
    message: "TDS reading at 780 ppm exceeds the 500 ppm warning threshold at Lohta Reservoir. Immediate investigation recommended.",
    value: 780, threshold: 500, parameter: "tds",
    created_at: new Date(Date.now() - 1800_000).toISOString(),
  },
  {
    id: "alert-02", node_id: "node-05", node_name: "Chaukaghat Tank", type: "node_offline",
    severity: "critical", state: "active", title: "Sensor Node Offline",
    message: "Node has not reported in over 24 hours. Battery critically low at 12%. Immediate field visit required.",
    value: 12, threshold: 20, parameter: "battery",
    created_at: new Date(Date.now() - 86400_000).toISOString(),
  },
  {
    id: "alert-03", node_id: "node-02", node_name: "Khajuri Pump Station", type: "low_ph",
    severity: "warning", state: "active", title: "Low pH Warning",
    message: "pH reading at 6.3 is below the recommended 6.5 minimum. Monitor for further decline.",
    value: 6.3, threshold: 6.5, parameter: "ph",
    created_at: new Date(Date.now() - 3600_000).toISOString(),
  },
  {
    id: "alert-04", node_id: "node-01", node_name: "Rampur Well #1", type: "anomaly_detected",
    severity: "info", state: "acknowledged", title: "Anomaly Detected in Flow Rate",
    message: "Unusual flow rate pattern detected. ML model flagged as potential pipe leak.",
    value: 18.5, threshold: 15, parameter: "flow_rate",
    created_at: new Date(Date.now() - 7200_000).toISOString(),
    acknowledged_at: new Date(Date.now() - 5400_000).toISOString(),
    acknowledged_by: "Operator Singh",
  },
  {
    id: "alert-05", node_id: "node-03", node_name: "Sultanpur Borewell", type: "high_turbidity",
    severity: "warning", state: "resolved", title: "Elevated Turbidity",
    message: "Turbidity spike to 6.2 NTU, likely due to recent rainfall. Resolved after settling.",
    value: 6.2, threshold: 5, parameter: "turbidity",
    created_at: new Date(Date.now() - 172800_000).toISOString(),
    resolved_at: new Date(Date.now() - 86400_000).toISOString(),
  },
  {
    id: "alert-06", node_id: "node-04", node_name: "Lohta Reservoir", type: "low_water_level",
    severity: "danger", state: "active", title: "Low Water Level Alert",
    message: "Water level at 2.1m is critically low. Reservoir may need emergency replenishment.",
    value: 2.1, threshold: 3.0, parameter: "water_level",
    created_at: new Date(Date.now() - 14400_000).toISOString(),
  },
  {
    id: "alert-07", node_id: "node-02", node_name: "Khajuri Pump Station", type: "low_battery",
    severity: "warning", state: "acknowledged", title: "Low Battery Warning",
    message: "Battery at 62%. Schedule replacement within the next 2 weeks.",
    value: 62, threshold: 70, parameter: "battery",
    created_at: new Date(Date.now() - 259200_000).toISOString(),
    acknowledged_at: new Date(Date.now() - 172800_000).toISOString(),
    acknowledged_by: "Tech Team",
  },
];

// Alert timeline data (last 7 days)
const timelineData = [
  { day: "Mon", critical: 1, danger: 2, warning: 3, info: 1 },
  { day: "Tue", critical: 0, danger: 1, warning: 4, info: 2 },
  { day: "Wed", critical: 2, danger: 3, warning: 2, info: 0 },
  { day: "Thu", critical: 0, danger: 1, warning: 1, info: 3 },
  { day: "Fri", critical: 1, danger: 2, warning: 3, info: 1 },
  { day: "Sat", critical: 0, danger: 0, warning: 2, info: 1 },
  { day: "Sun", critical: 1, danger: 1, warning: 2, info: 0 },
];

const SEVERITY_COLORS: Record<AlertSeverity, string> = {
  critical: "#c084fc",
  danger: "#f87171",
  warning: "#fbbf24",
  info: "#22d3ee",
};

const STATE_FILTERS: { label: string; value: AlertState | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Active", value: "active" },
  { label: "Acknowledged", value: "acknowledged" },
  { label: "Resolved", value: "resolved" },
];

const SEVERITY_FILTERS: { label: string; value: AlertSeverity | "all" }[] = [
  { label: "All", value: "all" },
  { label: "Critical", value: "critical" },
  { label: "Danger", value: "danger" },
  { label: "Warning", value: "warning" },
  { label: "Info", value: "info" },
];

// ============================================================
// Alerts Component
// ============================================================

export default function Alerts() {
  const { t } = useTranslation();
  const storeAlerts = useAppStore((s) => s.alerts);

  const [stateFilter, setStateFilter] = useState<AlertState | "all">("all");
  const [severityFilter, setSeverityFilter] = useState<AlertSeverity | "all">("all");

  const allAlerts = storeAlerts.length > 2 ? storeAlerts : EXTENDED_ALERTS;

  // Filter alerts
  const filteredAlerts = useMemo(() => {
    return allAlerts.filter((a) => {
      if (stateFilter !== "all" && a.state !== stateFilter) return false;
      if (severityFilter !== "all" && a.severity !== severityFilter) return false;
      return true;
    });
  }, [allAlerts, stateFilter, severityFilter]);

  // Stats for pie chart
  const severityCounts = useMemo(() => {
    const counts = { critical: 0, danger: 0, warning: 0, info: 0 };
    allAlerts.forEach((a) => {
      if (a.state === "active" && a.severity in counts) {
        counts[a.severity as keyof typeof counts]++;
      }
    });
    return Object.entries(counts).map(([name, value]) => ({ name, value }));
  }, [allAlerts]);

  const handleAcknowledge = (alertId: string) => {
    useAppStore.getState().updateAlert(alertId, {
      state: "acknowledged",
      acknowledged_at: new Date().toISOString(),
      acknowledged_by: "Current User",
    });
  };

  const handleDismiss = (alertId: string) => {
    useAppStore.getState().updateAlert(alertId, {
      state: "resolved",
      resolved_at: new Date().toISOString(),
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{t("alerts.title")}</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {allAlerts.filter((a) => a.state === "active").length} active alerts across all nodes
          </p>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card text-center">
          <div className="text-3xl font-bold text-danger-400">
            {allAlerts.filter((a) => a.state === "active").length}
          </div>
          <div className="text-xs text-slate-500 mt-1">{t("alerts.active")}</div>
        </div>
        <div className="card text-center">
          <div className="text-3xl font-bold text-critical-400">
            {allAlerts.filter((a) => a.severity === "critical" && a.state === "active").length}
          </div>
          <div className="text-xs text-slate-500 mt-1">Critical</div>
        </div>
        <div className="card text-center">
          <div className="text-3xl font-bold text-warn-400">
            {allAlerts.filter((a) => a.state === "acknowledged").length}
          </div>
          <div className="text-xs text-slate-500 mt-1">{t("alerts.acknowledged")}</div>
        </div>
        <div className="card text-center">
          <div className="text-3xl font-bold text-safe-400">
            {allAlerts.filter((a) => a.state === "resolved").length}
          </div>
          <div className="text-xs text-slate-500 mt-1">{t("alerts.resolved")}</div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Alert timeline */}
        <div className="panel xl:col-span-2">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">Alert Timeline (7 Days)</h3>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={timelineData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="day" stroke="#475569" fontSize={11} />
                <YAxis stroke="#475569" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
                <Bar dataKey="critical" stackId="a" fill={SEVERITY_COLORS.critical} radius={[0, 0, 0, 0]} />
                <Bar dataKey="danger" stackId="a" fill={SEVERITY_COLORS.danger} />
                <Bar dataKey="warning" stackId="a" fill={SEVERITY_COLORS.warning} />
                <Bar dataKey="info" stackId="a" fill={SEVERITY_COLORS.info} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Severity pie chart */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">By Severity (Active)</h3>
          </div>
          <div className="panel-body flex items-center justify-center">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={severityCounts}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {severityCounts.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={SEVERITY_COLORS[entry.name as AlertSeverity] ?? "#64748b"}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-medium">State:</span>
          <div className="flex bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
            {STATE_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setStateFilter(f.value)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  stateFilter === f.value
                    ? "bg-water-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-medium">Severity:</span>
          <div className="flex bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
            {SEVERITY_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setSeverityFilter(f.value)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  severityFilter === f.value
                    ? "bg-water-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <span className="text-xs text-slate-600 ml-auto">
          {filteredAlerts.length} alert{filteredAlerts.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Alert list */}
      <div className="space-y-3">
        {filteredAlerts.map((alert) => (
          <AlertCard
            key={alert.id}
            alert={alert}
            onAcknowledge={handleAcknowledge}
            onDismiss={handleDismiss}
          />
        ))}

        {filteredAlerts.length === 0 && (
          <div className="panel">
            <div className="panel-body text-center py-12">
              <div className="text-slate-500 text-sm">{t("alerts.noAlerts")}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Alert Card Sub-component
// ============================================================

function AlertCard({
  alert,
  onAcknowledge,
  onDismiss,
}: {
  alert: Alert;
  onAcknowledge: (id: string) => void;
  onDismiss: (id: string) => void;
}) {
  const { t } = useTranslation();

  const severityBg: Record<AlertSeverity, string> = {
    critical: "border-l-critical-500 bg-critical-900/10",
    danger: "border-l-danger-500 bg-danger-900/10",
    warning: "border-l-warn-500 bg-warn-900/10",
    info: "border-l-water-500 bg-water-900/10",
  };

  return (
    <div className={`panel border-l-4 ${severityBg[alert.severity]}`}>
      <div className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            {/* Top row: badges */}
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <StatusBadge status={alert.severity} size="sm" />
              <span className={`badge text-[10px] ${
                alert.state === "active" ? "bg-danger-500/15 text-danger-400 border border-danger-500/20" :
                alert.state === "acknowledged" ? "bg-warn-500/15 text-warn-400 border border-warn-500/20" :
                "bg-safe-500/15 text-safe-400 border border-safe-500/20"
              }`}>
                {alert.state.toUpperCase()}
              </span>
              <span className="text-xs text-slate-600">
                {alert.node_name}
              </span>
              <span className="text-xs text-slate-700">|</span>
              <span className="text-xs text-slate-600 font-mono">
                {alert.parameter}
              </span>
            </div>

            {/* Title + message */}
            <h4 className="text-sm font-semibold text-slate-200 mb-1">
              {alert.title}
            </h4>
            <p className="text-xs text-slate-400 leading-relaxed">
              {alert.message}
            </p>

            {/* Value info */}
            <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
              <span>
                Value: <span className="text-slate-300 font-mono">{alert.value}</span>
              </span>
              <span>
                Threshold: <span className="text-slate-300 font-mono">{alert.threshold}</span>
              </span>
              <span>
                {new Date(alert.created_at).toLocaleString("en-IN")}
              </span>
            </div>

            {/* Acknowledged / Resolved info */}
            {alert.acknowledged_at && (
              <div className="text-[10px] text-slate-600 mt-1">
                Acknowledged by {alert.acknowledged_by} at{" "}
                {new Date(alert.acknowledged_at).toLocaleString("en-IN")}
              </div>
            )}
            {alert.resolved_at && (
              <div className="text-[10px] text-slate-600 mt-1">
                Resolved at {new Date(alert.resolved_at).toLocaleString("en-IN")}
              </div>
            )}
          </div>

          {/* Actions */}
          {alert.state === "active" && (
            <div className="flex flex-col gap-2 flex-shrink-0">
              <button
                onClick={() => onAcknowledge(alert.id)}
                className="btn-secondary text-xs px-3 py-1.5"
              >
                {t("alerts.acknowledge")}
              </button>
              <button
                onClick={() => onDismiss(alert.id)}
                className="text-xs text-slate-500 hover:text-slate-300 px-3 py-1.5 transition-colors"
              >
                {t("alerts.dismiss")}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
