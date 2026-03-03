import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  BarChart,
  Bar,
  ScatterChart,
  Scatter,
  Cell,
} from "recharts";
import type { AnomalyRecord, ModelMetrics } from "../types";

// ============================================================
// Demo prediction data
// ============================================================

function generateForecastWithConfidence(days: number) {
  const data = [];
  const now = Date.now();
  let level = 7.2;
  for (let i = -7; i < days; i++) {
    const date = new Date(now + i * 86400_000);
    const isPast = i < 0;
    const noise = (Math.random() - 0.48) * 0.25;
    level += noise;
    level = Math.max(2, Math.min(12, level));

    const confidence = isPast ? 0 : Math.min(1.8, 0.3 + (i * 0.05));

    data.push({
      date: date.toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
      actual: isPast ? +level.toFixed(2) : undefined,
      predicted: !isPast ? +level.toFixed(2) : undefined,
      upper: !isPast ? +(level + confidence).toFixed(2) : undefined,
      lower: !isPast ? +(level - confidence).toFixed(2) : undefined,
      isPast,
    });
  }
  return data;
}

const forecastData = generateForecastWithConfidence(30);

// Irrigation calendar (next 14 days)
const irrigationCalendar = Array.from({ length: 14 }, (_, i) => {
  const date = new Date(Date.now() + i * 86400_000);
  const shouldIrrigate = Math.random() > 0.35;
  return {
    date: date.toLocaleDateString("en-IN", { weekday: "short", day: "numeric" }),
    fullDate: date.toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
    volume: shouldIrrigate ? Math.round(200 + Math.random() * 350) : 0,
    recommended: shouldIrrigate,
    confidence: +(0.75 + Math.random() * 0.2).toFixed(2),
  };
});

// Anomaly history
const DEMO_ANOMALIES: AnomalyRecord[] = [
  {
    id: "a1", node_id: "node-01", node_name: "Rampur Well #1", timestamp: new Date(Date.now() - 86400_000 * 3).toISOString(),
    parameter: "flow_rate", actual_value: 18.5, expected_value: 12.2, deviation: 3.2, severity: "warning",
    description: "Unusual spike in flow rate detected, possible pipe pressure change",
  },
  {
    id: "a2", node_id: "node-04", node_name: "Lohta Reservoir", timestamp: new Date(Date.now() - 86400_000 * 5).toISOString(),
    parameter: "tds", actual_value: 820, expected_value: 350, deviation: 4.8, severity: "danger",
    description: "Significant TDS increase detected. Potential contamination event.",
  },
  {
    id: "a3", node_id: "node-02", node_name: "Khajuri Pump Station", timestamp: new Date(Date.now() - 86400_000 * 7).toISOString(),
    parameter: "ph", actual_value: 5.8, expected_value: 7.1, deviation: 2.9, severity: "danger",
    description: "pH dropped below safe range. Investigated and found acidic runoff.",
  },
  {
    id: "a4", node_id: "node-03", node_name: "Sultanpur Borewell", timestamp: new Date(Date.now() - 86400_000 * 10).toISOString(),
    parameter: "turbidity", actual_value: 8.4, expected_value: 1.2, deviation: 5.1, severity: "critical",
    description: "Extreme turbidity spike after heavy rainfall. Resolved after 6 hours.",
  },
  {
    id: "a5", node_id: "node-01", node_name: "Rampur Well #1", timestamp: new Date(Date.now() - 86400_000 * 14).toISOString(),
    parameter: "water_level", actual_value: 3.1, expected_value: 6.5, deviation: 3.8, severity: "danger",
    description: "Unexpected water level drop. Seasonal drawdown accelerated.",
  },
];

const anomalyScatterData = DEMO_ANOMALIES.map((a) => ({
  name: a.parameter,
  deviation: a.deviation,
  severity: a.severity,
  label: `${a.node_name}: ${a.parameter}`,
  date: new Date(a.timestamp).toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
}));

// Model performance metrics
const DEMO_METRICS: ModelMetrics[] = [
  { model_name: "Water Level LSTM", version: "3.2.1", mae: 0.18, rmse: 0.24, r2_score: 0.94, mape: 3.2, last_trained: "2025-12-28", training_samples: 45_200 },
  { model_name: "TDS Predictor", version: "2.8.0", mae: 12.4, rmse: 18.7, r2_score: 0.91, mape: 5.1, last_trained: "2025-12-25", training_samples: 38_100 },
  { model_name: "Anomaly Detector", version: "4.1.0", mae: 0.08, rmse: 0.12, r2_score: 0.97, mape: 1.8, last_trained: "2025-12-30", training_samples: 128_500 },
  { model_name: "Irrigation Optimizer", version: "1.5.2", mae: 22.1, rmse: 31.4, r2_score: 0.88, mape: 7.3, last_trained: "2025-12-20", training_samples: 21_800 },
];

const SEVERITY_SCATTER_COLORS: Record<string, string> = {
  warning: "#fbbf24",
  danger: "#f87171",
  critical: "#c084fc",
  info: "#22d3ee",
};

// ============================================================
// Predictions Component
// ============================================================

export default function Predictions() {
  const { t } = useTranslation();
  const [selectedModel, setSelectedModel] = useState(0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-100">{t("predictions.title")}</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Machine learning forecasts and anomaly detection results
        </p>
      </div>

      {/* 30-Day Water Level Forecast */}
      <div className="panel">
        <div className="panel-header">
          <h2 className="text-sm font-semibold text-slate-200">
            {t("predictions.waterLevelForecast")}
          </h2>
          <span className="text-xs text-slate-500">30-day forecast with 95% confidence band</span>
        </div>
        <div className="panel-body">
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={forecastData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="date"
                stroke="#475569"
                fontSize={10}
                tickLine={false}
                interval={4}
              />
              <YAxis
                stroke="#475569"
                fontSize={10}
                tickLine={false}
                domain={["auto", "auto"]}
                label={{ value: "meters", angle: -90, position: "insideLeft", style: { fill: "#475569", fontSize: 10 } }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "11px" }} />

              {/* Confidence band */}
              <Area
                type="monotone"
                dataKey="upper"
                stroke="none"
                fill="#a855f7"
                fillOpacity={0.1}
                name="Upper Bound"
              />
              <Area
                type="monotone"
                dataKey="lower"
                stroke="none"
                fill="#a855f7"
                fillOpacity={0.1}
                name="Lower Bound"
              />

              {/* Actual data */}
              <Line
                type="monotone"
                dataKey="actual"
                stroke="#22d3ee"
                strokeWidth={2}
                dot={false}
                name="Actual"
                connectNulls={false}
              />

              {/* Predicted data */}
              <Line
                type="monotone"
                dataKey="predicted"
                stroke="#a855f7"
                strokeWidth={2}
                strokeDasharray="6 3"
                dot={false}
                name="Predicted"
                connectNulls={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Irrigation Calendar + Anomaly Scatter */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Irrigation recommendation calendar */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">
              {t("predictions.irrigationCalendar")}
            </h3>
            <span className="text-xs text-slate-500">Next 14 days</span>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={irrigationCalendar}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" stroke="#475569" fontSize={9} tickLine={false} />
                <YAxis
                  stroke="#475569"
                  fontSize={10}
                  tickLine={false}
                  label={{ value: "Liters", angle: -90, position: "insideLeft", style: { fill: "#475569", fontSize: 10 } }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(value: number) => [`${value} L`, "Volume"]}
                />
                <Bar dataKey="volume" radius={[4, 4, 0, 0]}>
                  {irrigationCalendar.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={entry.recommended ? "#22d3ee" : "#1e293b"}
                      opacity={entry.recommended ? 0.8 : 0.3}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>

            {/* Confidence summary */}
            <div className="mt-3 text-xs text-slate-500 text-center">
              Avg. confidence:{" "}
              <span className="text-water-400 font-semibold">
                {(irrigationCalendar.reduce((s, c) => s + c.confidence, 0) / irrigationCalendar.length * 100).toFixed(0)}%
              </span>
              {" | "}
              Irrigation days:{" "}
              <span className="text-slate-300 font-semibold">
                {irrigationCalendar.filter((c) => c.recommended).length}
              </span>
              {" of 14"}
            </div>
          </div>
        </div>

        {/* Anomaly history scatter */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">
              {t("predictions.anomalyHistory")}
            </h3>
            <span className="text-xs text-slate-500">Last 30 days</span>
          </div>
          <div className="panel-body">
            {/* Anomaly list */}
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {DEMO_ANOMALIES.map((anomaly) => (
                <div
                  key={anomaly.id}
                  className="flex items-start gap-3 p-2.5 rounded-lg bg-slate-800/40 border border-slate-800"
                >
                  <div
                    className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                      anomaly.severity === "critical" ? "bg-critical-400" :
                      anomaly.severity === "danger" ? "bg-danger-400" :
                      "bg-warn-400"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-semibold text-slate-200">{anomaly.node_name}</span>
                      <span className="text-slate-600">|</span>
                      <span className="text-slate-400 font-mono">{anomaly.parameter}</span>
                      <span className="text-slate-600 ml-auto">
                        {new Date(anomaly.timestamp).toLocaleDateString("en-IN", { month: "short", day: "numeric" })}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-1">{anomaly.description}</p>
                    <div className="flex gap-3 mt-1 text-[10px] text-slate-600">
                      <span>Actual: <span className="text-slate-400">{anomaly.actual_value}</span></span>
                      <span>Expected: <span className="text-slate-400">{anomaly.expected_value}</span></span>
                      <span>Deviation: <span className="text-warn-400">{anomaly.deviation.toFixed(1)}σ</span></span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Model Performance Metrics */}
      <div className="panel">
        <div className="panel-header">
          <h3 className="text-sm font-semibold text-slate-200">
            {t("predictions.modelPerformance")}
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">Model</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">Version</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">R² Score</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">MAE</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">RMSE</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">MAPE %</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">Training Samples</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">Last Trained</th>
              </tr>
            </thead>
            <tbody>
              {DEMO_METRICS.map((m, idx) => (
                <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3 text-slate-200 font-medium">{m.model_name}</td>
                  <td className="px-4 py-3 text-slate-400 font-mono text-xs">{m.version}</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`font-semibold tabular-nums ${m.r2_score >= 0.95 ? "text-safe-400" : m.r2_score >= 0.9 ? "text-water-400" : "text-warn-400"}`}>
                      {m.r2_score.toFixed(2)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-300">{m.mae.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-300">{m.rmse.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-300">{m.mape.toFixed(1)}%</td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-400">{m.training_samples.toLocaleString()}</td>
                  <td className="px-4 py-3 text-right text-slate-500 text-xs">{m.last_trained}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
