import type { WaterStatus } from "../types";

interface WaterQualityGaugeProps {
  score: number; // 0-100
  status: WaterStatus;
  size?: number; // diameter in px
  label?: string;
  className?: string;
}

const statusColors: Record<WaterStatus, { stroke: string; text: string; glow: string }> = {
  safe: {
    stroke: "#34d399",
    text: "text-safe-400",
    glow: "drop-shadow(0 0 8px rgba(52, 211, 153, 0.5))",
  },
  warning: {
    stroke: "#fbbf24",
    text: "text-warn-400",
    glow: "drop-shadow(0 0 8px rgba(251, 191, 36, 0.5))",
  },
  danger: {
    stroke: "#f87171",
    text: "text-danger-400",
    glow: "drop-shadow(0 0 8px rgba(248, 113, 113, 0.5))",
  },
  critical: {
    stroke: "#c084fc",
    text: "text-critical-400",
    glow: "drop-shadow(0 0 8px rgba(192, 132, 252, 0.5))",
  },
};

export default function WaterQualityGauge({
  score,
  status,
  size = 160,
  label = "Quality Score",
  className = "",
}: WaterQualityGaugeProps) {
  const clampedScore = Math.max(0, Math.min(100, score));
  const colors = statusColors[status];

  // SVG arc calculation
  const strokeWidth = size * 0.08;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const arcLength = circumference * 0.75; // 270-degree arc
  const offset = arcLength - (arcLength * clampedScore) / 100;

  return (
    <div className={`flex flex-col items-center ${className}`}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-[135deg]"
          style={{ filter: colors.glow }}
        >
          {/* Background arc */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#1e293b"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={`${arcLength} ${circumference}`}
          />
          {/* Value arc */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={colors.stroke}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeDashoffset={offset}
            className="transition-all duration-700 ease-out"
          />
        </svg>

        {/* Center text */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`text-4xl font-bold tabular-nums ${colors.text}`}>
            {Math.round(clampedScore)}
          </span>
          <span className="text-xs text-slate-500 mt-0.5">/ 100</span>
        </div>
      </div>

      <span className="text-xs text-slate-400 mt-2 font-medium">{label}</span>
    </div>
  );
}
