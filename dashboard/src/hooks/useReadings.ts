import { useState, useEffect, useCallback } from "react";
import type { SensorReading, SensorReadingHistory, TimeRange } from "../types";
import { getLatestReadings, getNodeReadings } from "../services/api";
import { useAppStore } from "../stores/appStore";

/**
 * Hook for fetching and auto-refreshing the latest sensor readings
 * across all nodes.
 */
export function useLatestReadings(refreshIntervalMs: number = 30_000) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const setLatestReadings = useAppStore((s) => s.setLatestReadings);
  const readings = useAppStore((s) => s.latestReadings);

  const fetchReadings = useCallback(async () => {
    try {
      const data = await getLatestReadings();
      setLatestReadings(data);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to fetch readings";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [setLatestReadings]);

  useEffect(() => {
    fetchReadings();
    const interval = setInterval(fetchReadings, refreshIntervalMs);
    return () => clearInterval(interval);
  }, [fetchReadings, refreshIntervalMs]);

  return {
    readings: Array.from(readings.values()),
    readingsMap: readings,
    loading,
    error,
    refresh: fetchReadings,
  };
}

/**
 * Hook for fetching historical readings for a specific node.
 */
export function useNodeReadings(nodeId: string | null, timeRange?: TimeRange) {
  const [data, setData] = useState<SensorReadingHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storeTimeRange = useAppStore((s) => s.timeRange);
  const range = timeRange ?? storeTimeRange;

  const fetchData = useCallback(async () => {
    if (!nodeId) return;
    setLoading(true);
    try {
      const result = await getNodeReadings(nodeId, range);
      setData(result);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to fetch node readings";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [nodeId, range]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refresh: fetchData };
}
