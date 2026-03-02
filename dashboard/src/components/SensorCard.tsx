import {
  LineChart,
  Line,
  ResponsiveContainer,
  YAxis,
} from "recharts";
import type { WaterStatus } from "../types";

interface SensorCardProps {
  label: string;
  value: number;
  unit: string;
  status: WaterStatus;
  icon?: React.ReactNode;
  sparklineData?: number[];
  className?: string;
}

const statusColor: Record<WaterStatus, string> = {
  safe: "text-safe-400",
  warning: "text-warn-400",
  danger: "text-danger-400",
  critical: "text-critical-400",
};

const statusBorder: Record<WaterStatus, string> = {
  safe: "border-safe-700/30",
  warning: "border-warn-700/30",
  danger: "border-danger-700/30",
  critical: "border-critical-700/30",
};

const sparklineColor: Record<WaterStatus, string> = {
  safe: "#34d399",
  warning: "#fbbf24",
  danger: "#f87171",
  critical: "#c084fc",
};

export default function SensorCard({
  label,
  value,
  unit,
  status,
  icon,
  sparklineData,
  className = "",
}: SensorCardProps) {
  const chartData = sparklineData?.map((v, i) => ({ i, v }));

  return (
    <div
      className={`card-hover relative overflow-hidden ${statusBorder[status]} ${className}`}
    >
      {/* Subtle glow effect */}
      <div
        className={`absolute top-0 right-0 w-24 h-24 rounded-full blur-3xl opacity-10 ${
          status === "safe"
            ? "bg-safe-400"
            : status === "warning"
              ? "bg-warn-400"
              : status === "danger"
                ? "bg-danger-400"
                : "bg-critical-400"
        }`}
      />

      <div className="relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            {label}
          </span>
          {icon && <span className="text-slate-500">{icon}</span>}
        </div>

        {/* Value */}
        <div className="flex items-baseline gap-1.5 mb-3">
          <span className={`text-3xl font-bold tabular-nums ${statusColor[status]}`}>
            {typeof value === "number" ? value.toFixed(1) : "--"}
          </span>
          <span className="text-sm text-slate-500">{unit}</span>
        </div>

        {/* Sparkline */}
        {chartData && chartData.length > 1 && (
          <div className="h-10 -mx-1">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <YAxis domain={["dataMin", "dataMax"]} hide />
                <Line
                  type="monotone"
                  dataKey="v"
                  stroke={sparklineColor[status]}
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
