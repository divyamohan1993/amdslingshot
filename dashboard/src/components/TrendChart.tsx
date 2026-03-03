import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
  Legend,
} from "recharts";

export interface TrendChartDataPoint {
  timestamp: string;
  value: number;
  predicted?: number;
  upperBound?: number;
  lowerBound?: number;
}

interface TrendChartProps {
  data: TrendChartDataPoint[];
  title?: string;
  color?: string;
  unit?: string;
  height?: number;
  showPrediction?: boolean;
  showConfidence?: boolean;
  yDomain?: [number, number];
  className?: string;
}

function formatTimestamp(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

function formatTooltipTime(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleString("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function TrendChart({
  data,
  title,
  color = "#22d3ee",
  unit = "",
  height = 280,
  showPrediction = false,
  showConfidence = false,
  yDomain,
  className = "",
}: TrendChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className={`panel ${className}`}>
        {title && (
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          </div>
        )}
        <div className="panel-body flex items-center justify-center h-48">
          <span className="text-slate-500 text-sm">No data available</span>
        </div>
      </div>
    );
  }

  const ChartComponent = showConfidence ? AreaChart : LineChart;

  return (
    <div className={`panel ${className}`}>
      {title && (
        <div className="panel-header">
          <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          {unit && <span className="text-xs text-slate-500">{unit}</span>}
        </div>
      )}
      <div className="panel-body">
        <ResponsiveContainer width="100%" height={height}>
          <ChartComponent data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatTimestamp}
              stroke="#475569"
              fontSize={11}
              tickLine={false}
            />
            <YAxis
              stroke="#475569"
              fontSize={11}
              tickLine={false}
              domain={yDomain ?? ["auto", "auto"]}
              tickFormatter={(v: number) => v.toFixed(1)}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                border: "1px solid #334155",
                borderRadius: "8px",
                fontSize: "12px",
              }}
              labelFormatter={formatTooltipTime}
              formatter={(value: number) => [`${value.toFixed(2)} ${unit}`, ""]}
            />

            {/* Confidence band */}
            {showConfidence && (
              <Area
                type="monotone"
                dataKey="upperBound"
                stroke="none"
                fill={color}
                fillOpacity={0.1}
                isAnimationActive={false}
              />
            )}
            {showConfidence && (
              <Area
                type="monotone"
                dataKey="lowerBound"
                stroke="none"
                fill={color}
                fillOpacity={0.1}
                isAnimationActive={false}
              />
            )}

            {/* Actual line */}
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              dot={false}
              name="Actual"
              isAnimationActive={false}
            />

            {/* Prediction line */}
            {showPrediction && (
              <Line
                type="monotone"
                dataKey="predicted"
                stroke="#a855f7"
                strokeWidth={2}
                strokeDasharray="6 3"
                dot={false}
                name="Predicted"
                isAnimationActive={false}
              />
            )}

            {(showPrediction || showConfidence) && (
              <Legend
                wrapperStyle={{ fontSize: "11px", color: "#94a3b8" }}
              />
            )}
          </ChartComponent>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
