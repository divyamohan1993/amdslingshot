import { useAppStore } from "../stores/appStore";
import { useTranslation } from "react-i18next";

/**
 * Critical alert banner that shows at the top of the page
 * when there are unacknowledged critical alerts.
 */
export default function AlertBanner() {
  const { t } = useTranslation();
  const alerts = useAppStore((s) => s.alerts);

  const criticalAlerts = alerts.filter(
    (a) => a.severity === "critical" && a.state === "active",
  );

  if (criticalAlerts.length === 0) return null;

  return (
    <div className="bg-danger-900/60 border-b border-danger-700/50 px-4 py-2">
      <div className="flex items-center gap-3">
        {/* Pulsing icon */}
        <div className="relative flex-shrink-0">
          <span className="flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-danger-500" />
          </span>
        </div>

        {/* Alert text */}
        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold text-danger-300">
            {criticalAlerts.length} Critical Alert{criticalAlerts.length !== 1 ? "s" : ""}
          </span>
          <span className="text-sm text-danger-400 ml-2 truncate">
            {criticalAlerts[0].title}
            {criticalAlerts.length > 1 &&
              ` (+${criticalAlerts.length - 1} more)`}
          </span>
        </div>

        {/* View button */}
        <a
          href="/alerts"
          className="flex-shrink-0 text-xs font-medium text-danger-300 hover:text-danger-200 bg-danger-800/50 px-3 py-1 rounded-full border border-danger-700/50 transition-colors"
        >
          View All
        </a>
      </div>
    </div>
  );
}
