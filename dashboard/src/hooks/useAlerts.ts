import { useState, useEffect, useCallback } from "react";
import type { Alert, AlertState } from "../types";
import {
  getActiveAlerts,
  getAlerts,
  acknowledgeAlert,
  resolveAlert,
} from "../services/api";
import { useAppStore } from "../stores/appStore";

/**
 * Hook for managing alerts with filtering and actions.
 */
export function useAlerts(options?: {
  stateFilter?: AlertState;
  autoRefreshMs?: number;
}) {
  const { stateFilter, autoRefreshMs = 30_000 } = options ?? {};
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const alerts = useAppStore((s) => s.alerts);
  const setAlerts = useAppStore((s) => s.setAlerts);
  const updateAlertInStore = useAppStore((s) => s.updateAlert);

  const fetchAlerts = useCallback(async () => {
    try {
      let data: Alert[];
      if (!stateFilter || stateFilter === "active") {
        data = await getActiveAlerts();
      } else {
        const response = await getAlerts({ state: stateFilter, per_page: 100 });
        data = response.items;
      }
      setAlerts(data);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to fetch alerts";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [stateFilter, setAlerts]);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, autoRefreshMs);
    return () => clearInterval(interval);
  }, [fetchAlerts, autoRefreshMs]);

  const acknowledge = useCallback(
    async (alertId: string) => {
      try {
        const updated = await acknowledgeAlert(alertId);
        updateAlertInStore(alertId, updated);
      } catch (err) {
        console.error("Failed to acknowledge alert:", err);
      }
    },
    [updateAlertInStore],
  );

  const resolve = useCallback(
    async (alertId: string) => {
      try {
        const updated = await resolveAlert(alertId);
        updateAlertInStore(alertId, updated);
      } catch (err) {
        console.error("Failed to resolve alert:", err);
      }
    },
    [updateAlertInStore],
  );

  // Derived counts
  const activeAlerts = alerts.filter((a) => a.state === "active");
  const criticalAlerts = alerts.filter(
    (a) => a.severity === "critical" && a.state === "active",
  );

  return {
    alerts,
    activeAlerts,
    criticalAlerts,
    loading,
    error,
    refresh: fetchAlerts,
    acknowledge,
    resolve,
  };
}
