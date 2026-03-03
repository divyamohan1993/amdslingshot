import { create } from "zustand";
import type {
  SensorNode,
  SensorReading,
  Alert,
  SystemHealth,
  TimeRange,
  WaterStatus,
} from "../types";
import type { ConnectionState } from "../services/websocket";

// ============================================================
// Application State Interface
// ============================================================

interface AppState {
  // -- UI State --
  sidebarOpen: boolean;
  language: "en" | "hi";
  timeRange: TimeRange;

  // -- Selected / Focus --
  selectedNodeId: string | null;

  // -- Real-Time Data Cache --
  nodes: SensorNode[];
  latestReadings: Map<string, SensorReading>; // keyed by node_id
  alerts: Alert[];

  // -- System --
  systemHealth: SystemHealth | null;
  wsConnectionState: ConnectionState;

  // -- Actions --
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setLanguage: (lang: "en" | "hi") => void;
  setTimeRange: (range: TimeRange) => void;
  setSelectedNode: (nodeId: string | null) => void;

  setNodes: (nodes: SensorNode[]) => void;
  updateNodeStatus: (nodeId: string, status: WaterStatus) => void;
  setLatestReading: (reading: SensorReading) => void;
  setLatestReadings: (readings: SensorReading[]) => void;

  setAlerts: (alerts: Alert[]) => void;
  addAlert: (alert: Alert) => void;
  updateAlert: (alertId: string, updates: Partial<Alert>) => void;
  removeAlert: (alertId: string) => void;

  setSystemHealth: (health: SystemHealth) => void;
  setWsConnectionState: (state: ConnectionState) => void;
}

// ============================================================
// Zustand Store
// ============================================================

export const useAppStore = create<AppState>((set, get) => ({
  // -- UI State --
  sidebarOpen: typeof window !== "undefined" && window.innerWidth >= 1024,
  language: "en",
  timeRange: "24h",

  // -- Selected --
  selectedNodeId: null,

  // -- Data --
  nodes: [],
  latestReadings: new Map(),
  alerts: [],

  // -- System --
  systemHealth: null,
  wsConnectionState: "disconnected",

  // -- UI Actions --
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  setLanguage: (lang) => {
    set({ language: lang });
    localStorage.setItem("jalnetra_lang", lang);
  },

  setTimeRange: (range) => set({ timeRange: range }),
  setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId }),

  // -- Nodes --
  setNodes: (nodes) => set({ nodes }),

  updateNodeStatus: (nodeId, status) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === nodeId ? { ...n, water_status: status } : n,
      ),
    })),

  // -- Readings --
  setLatestReading: (reading) =>
    set((s) => {
      const newMap = new Map(s.latestReadings);
      newMap.set(reading.node_id, reading);
      return { latestReadings: newMap };
    }),

  setLatestReadings: (readings) =>
    set(() => {
      const newMap = new Map<string, SensorReading>();
      readings.forEach((r) => newMap.set(r.node_id, r));
      return { latestReadings: newMap };
    }),

  // -- Alerts --
  setAlerts: (alerts) => set({ alerts }),

  addAlert: (alert) =>
    set((s) => ({
      alerts: [alert, ...s.alerts],
    })),

  updateAlert: (alertId, updates) =>
    set((s) => ({
      alerts: s.alerts.map((a) =>
        a.id === alertId ? { ...a, ...updates } : a,
      ),
    })),

  removeAlert: (alertId) =>
    set((s) => ({
      alerts: s.alerts.filter((a) => a.id !== alertId),
    })),

  // -- System --
  setSystemHealth: (health) => set({ systemHealth: health }),
  setWsConnectionState: (state) => set({ wsConnectionState: state }),
}));
