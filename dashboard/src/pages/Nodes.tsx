import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useAppStore } from "../stores/appStore";
import StatusBadge from "../components/StatusBadge";
import SensorCard from "../components/SensorCard";
import type { SensorNode, SensorReading, TimeRange } from "../types";

// ============================================================
// Demo historical data generator
// ============================================================

function generateHistory(baseValue: number, variance: number, hours: number) {
  const data = [];
  const now = Date.now();
  for (let i = hours; i >= 0; i--) {
    const ts = new Date(now - i * 3600_000);
    const noise = (Math.random() - 0.5) * variance;
    data.push({
      time: ts.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
      value: +(baseValue + noise).toFixed(2),
    });
  }
  return data;
}

const TIME_RANGES: { label: string; value: TimeRange }[] = [
  { label: "1H", value: "1h" },
  { label: "6H", value: "6h" },
  { label: "24H", value: "24h" },
  { label: "7D", value: "7d" },
  { label: "30D", value: "30d" },
];

// ============================================================
// Nodes Component
// ============================================================

export default function Nodes() {
  const { t } = useTranslation();
  const nodes = useAppStore((s) => s.nodes);
  const readingsMap = useAppStore((s) => s.latestReadings);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");

  const filteredNodes = useMemo(() => {
    if (statusFilter === "all") return nodes;
    return nodes.filter((n) => n.status === statusFilter);
  }, [nodes, statusFilter]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedReading = selectedNodeId ? readingsMap.get(selectedNodeId) : undefined;

  // Generate demo charts for selected node
  const historyHours = timeRange === "1h" ? 1 : timeRange === "6h" ? 6 : timeRange === "24h" ? 24 : timeRange === "7d" ? 168 : 720;
  const tdsHistory = generateHistory(selectedReading?.tds ?? 200, 40, Math.min(historyHours, 48));
  const phHistory = generateHistory(selectedReading?.ph ?? 7.0, 0.3, Math.min(historyHours, 48));
  const turbHistory = generateHistory(selectedReading?.turbidity ?? 2, 1, Math.min(historyHours, 48));
  const levelHistory = generateHistory(selectedReading?.water_level ?? 6, 0.8, Math.min(historyHours, 48));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{t("nodes.title")}</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {nodes.length} nodes deployed | {nodes.filter((n) => n.status === "online").length} online
          </p>
        </div>

        {/* Status filter */}
        <div className="flex bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          {(["all", "online", "offline"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                statusFilter === f
                  ? "bg-water-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Node list */}
        <div className="xl:col-span-1 space-y-2 max-h-[calc(100vh-200px)] overflow-y-auto pr-1">
          {filteredNodes.map((node) => {
            const reading = readingsMap.get(node.id);
            const isSelected = node.id === selectedNodeId;

            return (
              <div
                key={node.id}
                onClick={() => setSelectedNodeId(node.id)}
                className={`panel cursor-pointer transition-all duration-150 ${
                  isSelected
                    ? "border-water-600/50 bg-water-900/10 shadow-lg shadow-water-900/10"
                    : "hover:border-slate-700"
                }`}
              >
                <div className="p-3">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold text-slate-200 truncate">{node.name}</h3>
                    <StatusBadge status={node.status} size="sm" pulse={node.status === "online"} />
                  </div>

                  <div className="text-xs text-slate-500 mb-2">
                    {node.village}, {node.district}
                  </div>

                  {/* Battery + Signal */}
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-1.5">
                      <svg className="w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 10.5h.375c.621 0 1.125.504 1.125 1.125v2.25c0 .621-.504 1.125-1.125 1.125H21M3.75 18h15A2.25 2.25 0 0021 15.75v-6a2.25 2.25 0 00-2.25-2.25h-15A2.25 2.25 0 001.5 9.75v6A2.25 2.25 0 003.75 18z" />
                      </svg>
                      <div className="w-16 h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            node.battery_level > 50 ? "bg-safe-500" :
                            node.battery_level > 20 ? "bg-warn-500" : "bg-danger-500"
                          }`}
                          style={{ width: `${node.battery_level}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-slate-500 tabular-nums">{node.battery_level}%</span>
                    </div>

                    <div className="flex items-center gap-1 text-[10px] text-slate-500">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
                      </svg>
                      <span className="tabular-nums">{node.signal_strength} dBm</span>
                    </div>
                  </div>

                  {/* Water status */}
                  {reading && (
                    <div className="flex items-center gap-3 mt-2 pt-2 border-t border-slate-800/50">
                      <StatusBadge status={reading.status} size="sm" />
                      <span className="text-[10px] text-slate-600">
                        Score: {reading.water_quality_score}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {filteredNodes.length === 0 && (
            <div className="text-center text-slate-500 text-sm py-8">
              No nodes match the filter
            </div>
          )}
        </div>

        {/* Node detail */}
        <div className="xl:col-span-2 space-y-4">
          {selectedNode ? (
            <>
              {/* Node header */}
              <div className="panel">
                <div className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h2 className="text-lg font-bold text-slate-100">{selectedNode.name}</h2>
                      <p className="text-xs text-slate-500">
                        {selectedNode.village}, {selectedNode.district}, {selectedNode.state}
                      </p>
                    </div>
                    <StatusBadge status={selectedNode.status} size="lg" pulse={selectedNode.status === "online"} />
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                    <div>
                      <span className="text-slate-500">{t("nodes.battery")}</span>
                      <div className="flex items-center gap-2 mt-1">
                        <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              selectedNode.battery_level > 50 ? "bg-safe-500" :
                              selectedNode.battery_level > 20 ? "bg-warn-500" : "bg-danger-500"
                            }`}
                            style={{ width: `${selectedNode.battery_level}%` }}
                          />
                        </div>
                        <span className="text-slate-300 font-semibold tabular-nums">{selectedNode.battery_level}%</span>
                      </div>
                    </div>
                    <div>
                      <span className="text-slate-500">{t("nodes.signal")}</span>
                      <div className="text-slate-300 font-semibold mt-1">{selectedNode.signal_strength} dBm</div>
                    </div>
                    <div>
                      <span className="text-slate-500">{t("nodes.firmware")}</span>
                      <div className="text-slate-300 font-mono mt-1">v{selectedNode.firmware_version}</div>
                    </div>
                    <div>
                      <span className="text-slate-500">{t("nodes.lastSeen")}</span>
                      <div className="text-slate-300 mt-1">
                        {new Date(selectedNode.last_seen).toLocaleString("en-IN", {
                          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Sensor value cards */}
              {selectedReading && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                  <SensorCard label="TDS" value={selectedReading.tds} unit="ppm"
                    status={selectedReading.tds > 500 ? "warning" : "safe"} />
                  <SensorCard label="pH" value={selectedReading.ph} unit=""
                    status={selectedReading.ph < 6.5 || selectedReading.ph > 8.5 ? "warning" : "safe"} />
                  <SensorCard label="Turbidity" value={selectedReading.turbidity} unit="NTU"
                    status={selectedReading.turbidity > 5 ? "warning" : "safe"} />
                  <SensorCard label="Flow Rate" value={selectedReading.flow_rate} unit="L/min" status="safe" />
                  <SensorCard label="Water Level" value={selectedReading.water_level} unit="m"
                    status={selectedReading.water_level < 2 ? "danger" : "safe"} />
                  <SensorCard label="Temperature" value={selectedReading.temperature} unit="°C" status="safe" />
                  <SensorCard label="Dissolved O₂" value={selectedReading.dissolved_oxygen} unit="mg/L"
                    status={selectedReading.dissolved_oxygen < 4 ? "warning" : "safe"} />
                  <SensorCard label="Quality Score" value={selectedReading.water_quality_score} unit="/100"
                    status={selectedReading.status} />
                </div>
              )}

              {/* Time range selector */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">Time Range:</span>
                <div className="flex bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
                  {TIME_RANGES.map((r) => (
                    <button
                      key={r.value}
                      onClick={() => setTimeRange(r.value)}
                      className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                        timeRange === r.value
                          ? "bg-water-600 text-white"
                          : "text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Historical charts */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <MiniChart title="TDS (ppm)" data={tdsHistory} color="#22d3ee" />
                <MiniChart title="pH" data={phHistory} color="#34d399" />
                <MiniChart title="Turbidity (NTU)" data={turbHistory} color="#fbbf24" />
                <MiniChart title="Water Level (m)" data={levelHistory} color="#a855f7" />
              </div>
            </>
          ) : (
            <div className="panel">
              <div className="p-12 text-center">
                <svg className="w-12 h-12 mx-auto text-slate-700 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
                </svg>
                <p className="text-sm text-slate-500">Select a sensor node to view details</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Mini Chart Sub-component
// ============================================================

function MiniChart({
  title,
  data,
  color,
}: {
  title: string;
  data: { time: string; value: number }[];
  color: string;
}) {
  return (
    <div className="panel">
      <div className="panel-header">
        <h4 className="text-xs font-semibold text-slate-300">{title}</h4>
      </div>
      <div className="p-3">
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="time" stroke="#475569" fontSize={9} tickLine={false} interval={Math.floor(data.length / 5)} />
            <YAxis stroke="#475569" fontSize={9} tickLine={false} domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                border: "1px solid #334155",
                borderRadius: "8px",
                fontSize: "11px",
              }}
            />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
