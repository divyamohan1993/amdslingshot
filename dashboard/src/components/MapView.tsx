import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from "react-leaflet";
import type { SensorNode, SensorReading } from "../types";
import type { WaterStatus } from "../types";
import StatusBadge from "./StatusBadge";

interface MapViewProps {
  nodes: SensorNode[];
  readings?: Map<string, SensorReading>;
  selectedNodeId?: string | null;
  onNodeSelect?: (nodeId: string) => void;
  center?: [number, number];
  zoom?: number;
  height?: string;
  className?: string;
}

const statusMarkerColor: Record<WaterStatus, string> = {
  safe: "#34d399",
  warning: "#fbbf24",
  danger: "#f87171",
  critical: "#c084fc",
};

const statusFillOpacity: Record<WaterStatus, number> = {
  safe: 0.3,
  warning: 0.4,
  danger: 0.5,
  critical: 0.6,
};

/** Re-center the map when center prop changes */
function MapUpdater({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  map.setView(center, zoom);
  return null;
}

export default function MapView({
  nodes,
  readings,
  selectedNodeId,
  onNodeSelect,
  center = [22.5, 78.5], // Center of India
  zoom = 5,
  height = "h-96",
  className = "",
}: MapViewProps) {
  return (
    <div className={`panel overflow-hidden ${height} ${className}`}>
      <MapContainer
        center={center}
        zoom={zoom}
        className="w-full h-full z-0"
        style={{ background: "#0f172a" }}
        zoomControl={false}
        attributionControl={false}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>'
        />

        {nodes.map((node) => {
          const reading = readings?.get(node.id);
          const color = statusMarkerColor[node.water_status] ?? "#64748b";
          const fillOpacity = statusFillOpacity[node.water_status] ?? 0.3;
          const isSelected = node.id === selectedNodeId;

          return (
            <CircleMarker
              key={node.id}
              center={[node.location.lat, node.location.lng]}
              radius={isSelected ? 14 : 10}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: isSelected ? 0.7 : fillOpacity,
                weight: isSelected ? 3 : 2,
              }}
              eventHandlers={{
                click: () => onNodeSelect?.(node.id),
              }}
            >
              <Popup>
                <div className="text-slate-900 min-w-48">
                  <div className="font-bold text-sm mb-1">{node.name}</div>
                  <div className="text-xs text-slate-600 mb-2">
                    {node.village}, {node.district}
                  </div>

                  <div className="mb-2">
                    <StatusBadge status={node.water_status} size="sm" />
                  </div>

                  {reading && (
                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                      <div>
                        <span className="text-slate-500">TDS:</span>{" "}
                        <span className="font-medium">{reading.tds.toFixed(0)} ppm</span>
                      </div>
                      <div>
                        <span className="text-slate-500">pH:</span>{" "}
                        <span className="font-medium">{reading.ph.toFixed(1)}</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Turbidity:</span>{" "}
                        <span className="font-medium">{reading.turbidity.toFixed(1)} NTU</span>
                      </div>
                      <div>
                        <span className="text-slate-500">Level:</span>{" "}
                        <span className="font-medium">{reading.water_level.toFixed(1)} m</span>
                      </div>
                    </div>
                  )}

                  <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                    <span>Battery: {node.battery_level}%</span>
                    <span>Signal: {node.signal_strength} dBm</span>
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
