import type { WaterStatus, AlertSeverity, NodeStatus } from "../types";
import { useTranslation } from "react-i18next";

type BadgeVariant = WaterStatus | AlertSeverity | NodeStatus;

interface StatusBadgeProps {
  status: BadgeVariant;
  size?: "sm" | "md" | "lg";
  pulse?: boolean;
  className?: string;
}

const variantStyles: Record<string, string> = {
  safe: "bg-safe-500/20 text-safe-400 border-safe-500/30",
  info: "bg-water-500/20 text-water-400 border-water-500/30",
  warning: "bg-warn-500/20 text-warn-400 border-warn-500/30",
  danger: "bg-danger-500/20 text-danger-400 border-danger-500/30",
  critical: "bg-critical-500/20 text-critical-400 border-critical-500/30",
  online: "bg-safe-500/20 text-safe-400 border-safe-500/30",
  offline: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  maintenance: "bg-warn-500/20 text-warn-400 border-warn-500/30",
  error: "bg-danger-500/20 text-danger-400 border-danger-500/30",
};

const dotColors: Record<string, string> = {
  safe: "bg-safe-400",
  info: "bg-water-400",
  warning: "bg-warn-400",
  danger: "bg-danger-400",
  critical: "bg-critical-400",
  online: "bg-safe-400",
  offline: "bg-slate-500",
  maintenance: "bg-warn-400",
  error: "bg-danger-400",
};

const sizeStyles = {
  sm: "px-2 py-0.5 text-xs",
  md: "px-2.5 py-1 text-xs",
  lg: "px-3 py-1.5 text-sm",
};

export default function StatusBadge({
  status,
  size = "md",
  pulse = false,
  className = "",
}: StatusBadgeProps) {
  const { t } = useTranslation();

  const label =
    t(`status.${status}`, { defaultValue: "" }) ||
    status.charAt(0).toUpperCase() + status.slice(1);

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${variantStyles[status] ?? variantStyles.info} ${sizeStyles[size]} ${className}`}
    >
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${dotColors[status] ?? dotColors.info} ${pulse ? "animate-pulse" : ""}`}
      />
      {label}
    </span>
  );
}
