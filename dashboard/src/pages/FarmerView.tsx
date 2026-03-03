import { useTranslation } from "react-i18next";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { useAppStore } from "../stores/appStore";
import type { WaterStatus, IrrigationSchedule } from "../types";

// ============================================================
// Demo data
// ============================================================

function generateForecastData(days: number) {
  const data = [];
  const now = Date.now();
  let level = 6.5;
  for (let i = 0; i < days; i++) {
    const date = new Date(now + i * 86400_000);
    level += (Math.random() - 0.52) * 0.3;
    level = Math.max(1, Math.min(12, level));
    data.push({
      date: date.toLocaleDateString("en-IN", { month: "short", day: "numeric" }),
      level: +level.toFixed(1),
      upper: +(level + 0.8 + Math.random() * 0.4).toFixed(1),
      lower: +(level - 0.8 - Math.random() * 0.4).toFixed(1),
    });
  }
  return data;
}

const DEMO_SCHEDULE: IrrigationSchedule[] = [
  { id: "s1", node_id: "node-01", date: "Mon", start_time: "06:00", end_time: "07:30", duration_minutes: 90, recommended_volume_liters: 450, crop_type: "Wheat", status: "completed", water_saved_percent: 18 },
  { id: "s2", node_id: "node-01", date: "Tue", start_time: "06:00", end_time: "06:45", duration_minutes: 45, recommended_volume_liters: 250, crop_type: "Wheat", status: "completed", water_saved_percent: 22 },
  { id: "s3", node_id: "node-01", date: "Wed", start_time: "05:30", end_time: "07:00", duration_minutes: 90, recommended_volume_liters: 420, crop_type: "Wheat", status: "in_progress", water_saved_percent: 15 },
  { id: "s4", node_id: "node-01", date: "Thu", start_time: "06:00", end_time: "07:00", duration_minutes: 60, recommended_volume_liters: 320, crop_type: "Wheat", status: "scheduled", water_saved_percent: 20 },
  { id: "s5", node_id: "node-01", date: "Fri", start_time: "06:00", end_time: "06:30", duration_minutes: 30, recommended_volume_liters: 180, crop_type: "Wheat", status: "scheduled", water_saved_percent: 25 },
  { id: "s6", node_id: "node-01", date: "Sat", start_time: "", end_time: "", duration_minutes: 0, recommended_volume_liters: 0, crop_type: "Wheat", status: "skipped", water_saved_percent: 100 },
  { id: "s7", node_id: "node-01", date: "Sun", start_time: "06:00", end_time: "07:15", duration_minutes: 75, recommended_volume_liters: 400, crop_type: "Wheat", status: "scheduled", water_saved_percent: 17 },
];

const forecastData = generateForecastData(30);

// ============================================================
// Status display config
// ============================================================

const statusConfig: Record<WaterStatus, {
  bg: string; border: string; text: string; glow: string;
  labelEn: string; labelHi: string; messageKey: string; emoji: string;
}> = {
  safe: {
    bg: "bg-safe-500/10", border: "border-safe-500/40", text: "text-safe-400",
    glow: "shadow-safe-500/20 shadow-2xl", labelEn: "SAFE", labelHi: "सुरक्षित",
    messageKey: "farmer.safe_message", emoji: "",
  },
  warning: {
    bg: "bg-warn-500/10", border: "border-warn-500/40", text: "text-warn-400",
    glow: "shadow-warn-500/20 shadow-2xl", labelEn: "CAUTION", labelHi: "सावधानी",
    messageKey: "farmer.warning_message", emoji: "",
  },
  danger: {
    bg: "bg-danger-500/10", border: "border-danger-500/40", text: "text-danger-400",
    glow: "shadow-danger-500/20 shadow-2xl", labelEn: "DANGER", labelHi: "खतरा",
    messageKey: "farmer.danger_message", emoji: "",
  },
  critical: {
    bg: "bg-critical-500/10", border: "border-critical-500/40", text: "text-critical-400",
    glow: "shadow-critical-500/20 shadow-2xl", labelEn: "CRITICAL", labelHi: "गंभीर खतरा",
    messageKey: "farmer.danger_message", emoji: "",
  },
};

const scheduleStatusColors: Record<string, string> = {
  completed: "bg-safe-500",
  in_progress: "bg-water-500 animate-pulse",
  scheduled: "bg-slate-600",
  skipped: "bg-slate-800 border border-slate-700",
};

// ============================================================
// FarmerView Component
// ============================================================

export default function FarmerView() {
  const { t } = useTranslation();
  const language = useAppStore((s) => s.language);
  const nodes = useAppStore((s) => s.nodes);
  const readingsMap = useAppStore((s) => s.latestReadings);

  // Use first node or default
  const node = nodes[0];
  const reading = node ? readingsMap.get(node.id) : undefined;
  const waterStatus: WaterStatus = reading?.status ?? node?.water_status ?? "safe";
  const config = statusConfig[waterStatus];

  // Water saved calculation
  const avgWaterSaved = DEMO_SCHEDULE.reduce((s, item) => s + item.water_saved_percent, 0) / DEMO_SCHEDULE.length;

  return (
    <div className="max-w-lg mx-auto space-y-6 pb-8">
      {/* Page title */}
      <div className="text-center">
        <h1 className="text-3xl font-bold text-slate-100">
          {t("farmer.title")}
        </h1>
        {node && (
          <p className="text-sm text-slate-500 mt-1">{node.name} - {node.village}</p>
        )}
      </div>

      {/* Large Water Status Indicator */}
      <div className={`${config.bg} ${config.border} ${config.glow} border-2 rounded-2xl p-8 text-center`}>
        {/* Large status circle */}
        <div className={`w-32 h-32 mx-auto rounded-full ${config.border} border-4 flex items-center justify-center mb-4 ${config.bg}`}>
          <span className={`text-5xl font-black ${config.text}`}>
            {reading?.water_quality_score?.toFixed(0) ?? "--"}
          </span>
        </div>

        {/* Status label (large, bilingual) */}
        <div className={`text-4xl font-black tracking-wide ${config.text} mb-2`}>
          {language === "hi" ? config.labelHi : config.labelEn}
        </div>

        {/* Message */}
        <p className="text-lg text-slate-300">
          {t(config.messageKey)}
        </p>

        {/* Key readings in large text */}
        {reading && (
          <div className="grid grid-cols-3 gap-4 mt-6">
            <div>
              <div className="text-2xl font-bold text-slate-200">{reading.ph.toFixed(1)}</div>
              <div className="text-xs text-slate-500">{t("sensors.ph")}</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-200">{reading.tds.toFixed(0)}</div>
              <div className="text-xs text-slate-500">{t("sensors.tds")}</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-slate-200">{reading.turbidity.toFixed(1)}</div>
              <div className="text-xs text-slate-500">{t("sensors.turbidity")}</div>
            </div>
          </div>
        )}
      </div>

      {/* Irrigation Schedule - Visual Blocks */}
      <div className="panel">
        <div className="panel-header">
          <h2 className="text-base font-semibold text-slate-200">
            {t("farmer.irrigationSchedule")}
          </h2>
        </div>
        <div className="panel-body">
          <div className="grid grid-cols-7 gap-2">
            {DEMO_SCHEDULE.map((slot) => (
              <div key={slot.id} className="text-center">
                <div className="text-xs text-slate-500 mb-2 font-medium">{slot.date}</div>
                <div
                  className={`h-16 rounded-lg ${scheduleStatusColors[slot.status]} flex flex-col items-center justify-center transition-all`}
                  title={slot.status === "skipped" ? "No irrigation" : `${slot.start_time} - ${slot.end_time}`}
                >
                  {slot.status !== "skipped" ? (
                    <>
                      <span className="text-xs font-bold text-white">{slot.duration_minutes}m</span>
                      <span className="text-[9px] text-white/70">{slot.start_time}</span>
                    </>
                  ) : (
                    <span className="text-xs text-slate-500">--</span>
                  )}
                </div>
                {slot.status !== "skipped" && (
                  <div className="text-[10px] text-slate-600 mt-1">{slot.recommended_volume_liters}L</div>
                )}
              </div>
            ))}
          </div>

          {/* Legend */}
          <div className="flex items-center justify-center gap-4 mt-4 text-xs text-slate-500">
            <div className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm bg-safe-500" />
              <span>{language === "hi" ? "पूर्ण" : "Done"}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm bg-water-500" />
              <span>{language === "hi" ? "चालू" : "Now"}</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm bg-slate-600" />
              <span>{language === "hi" ? "अनुसूचित" : "Planned"}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Groundwater Level Forecast */}
      <div className="panel">
        <div className="panel-header">
          <h2 className="text-base font-semibold text-slate-200">
            {t("farmer.groundwaterForecast")}
          </h2>
          <span className="text-xs text-slate-500">30 {language === "hi" ? "दिन" : "days"}</span>
        </div>
        <div className="panel-body">
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={forecastData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="date"
                stroke="#475569"
                fontSize={10}
                tickLine={false}
                interval={6}
              />
              <YAxis
                stroke="#475569"
                fontSize={10}
                tickLine={false}
                domain={["auto", "auto"]}
                label={{ value: language === "hi" ? "मीटर" : "meters", angle: -90, position: "insideLeft", style: { fill: "#475569", fontSize: 10 } }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
              />
              <Area
                type="monotone"
                dataKey="upper"
                stroke="none"
                fill="#22d3ee"
                fillOpacity={0.08}
              />
              <Area
                type="monotone"
                dataKey="lower"
                stroke="none"
                fill="#22d3ee"
                fillOpacity={0.08}
              />
              <Area
                type="monotone"
                dataKey="level"
                stroke="#22d3ee"
                fill="#22d3ee"
                fillOpacity={0.15}
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Water Saved Gauge */}
      <div className="panel">
        <div className="panel-header">
          <h2 className="text-base font-semibold text-slate-200">
            {t("farmer.waterSaved")}
          </h2>
        </div>
        <div className="panel-body flex flex-col items-center py-6">
          {/* Simple percentage bar */}
          <div className="text-5xl font-black text-safe-400 mb-2">
            {avgWaterSaved.toFixed(0)}%
          </div>
          <p className="text-sm text-slate-400 mb-4">
            {language === "hi"
              ? "इस हफ्ते AI सिफारिशों से बचाया गया पानी"
              : "Water saved this week with AI recommendations"}
          </p>

          {/* Progress bar */}
          <div className="w-full max-w-xs h-4 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-water-600 to-safe-500 rounded-full transition-all duration-1000"
              style={{ width: `${avgWaterSaved}%` }}
            />
          </div>

          {/* Before/After comparison */}
          <div className="grid grid-cols-2 gap-8 mt-6 text-center">
            <div>
              <div className="text-xs text-slate-500 mb-1">
                {language === "hi" ? "पहले" : "Before AI"}
              </div>
              <div className="text-xl font-bold text-slate-400">2,840 L</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">
                {language === "hi" ? "अब" : "With AI"}
              </div>
              <div className="text-xl font-bold text-safe-400">2,020 L</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
