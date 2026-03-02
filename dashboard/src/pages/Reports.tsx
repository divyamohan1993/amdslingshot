import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { useAppStore } from "../stores/appStore";
import type { ComplianceReport } from "../types";

// ============================================================
// Demo compliance reports
// ============================================================

const DEMO_REPORTS: ComplianceReport[] = [
  {
    id: "rpt-001",
    title: "Monthly Compliance Report - December 2025",
    period_start: "2025-12-01",
    period_end: "2025-12-31",
    generated_at: "2026-01-02T08:30:00Z",
    total_readings: 14_520,
    compliant_readings: 13_196,
    compliance_percentage: 90.9,
    violations: [
      { parameter: "TDS", count: 312, max_value: 1250, threshold: 500, node_ids: ["node-04", "node-05"] },
      { parameter: "pH", count: 487, max_value: 5.1, threshold: 6.5, node_ids: ["node-02", "node-04"] },
      { parameter: "Turbidity", count: 225, max_value: 15.6, threshold: 5, node_ids: ["node-04"] },
    ],
    summary: "Overall compliance at 90.9%. Major violations at Lohta Reservoir and Chaukaghat Tank require corrective action. TDS and pH levels exceeded JJM thresholds intermittently throughout the month.",
  },
  {
    id: "rpt-002",
    title: "Monthly Compliance Report - November 2025",
    period_start: "2025-11-01",
    period_end: "2025-11-30",
    generated_at: "2025-12-02T09:15:00Z",
    total_readings: 13_890,
    compliant_readings: 12_918,
    compliance_percentage: 93.0,
    violations: [
      { parameter: "TDS", count: 198, max_value: 920, threshold: 500, node_ids: ["node-04"] },
      { parameter: "pH", count: 412, max_value: 5.8, threshold: 6.5, node_ids: ["node-02"] },
      { parameter: "Turbidity", count: 362, max_value: 12.1, threshold: 5, node_ids: ["node-03", "node-04"] },
    ],
    summary: "Compliance improved to 93.0% from 91.2% in October. Heavy rainfall events in mid-November caused temporary turbidity spikes across multiple nodes.",
  },
  {
    id: "rpt-003",
    title: "Monthly Compliance Report - October 2025",
    period_start: "2025-10-01",
    period_end: "2025-10-31",
    generated_at: "2025-11-02T10:00:00Z",
    total_readings: 14_200,
    compliant_readings: 12_944,
    compliance_percentage: 91.2,
    violations: [
      { parameter: "TDS", count: 420, max_value: 1100, threshold: 500, node_ids: ["node-04", "node-05"] },
      { parameter: "pH", count: 380, max_value: 5.5, threshold: 6.5, node_ids: ["node-02", "node-04"] },
      { parameter: "Turbidity", count: 156, max_value: 8.4, threshold: 5, node_ids: ["node-04"] },
      { parameter: "Dissolved Oxygen", count: 300, max_value: 3.1, threshold: 4.0, node_ids: ["node-05"] },
    ],
    summary: "Compliance at 91.2%. Dissolved oxygen violations emerged at Chaukaghat Tank due to stagnant water conditions. Remedial action initiated.",
  },
  {
    id: "rpt-004",
    title: "Quarterly Compliance Report - Q3 2025",
    period_start: "2025-07-01",
    period_end: "2025-09-30",
    generated_at: "2025-10-05T08:00:00Z",
    total_readings: 42_800,
    compliant_readings: 39_372,
    compliance_percentage: 92.0,
    violations: [
      { parameter: "TDS", count: 1024, max_value: 1180, threshold: 500, node_ids: ["node-04", "node-05"] },
      { parameter: "pH", count: 890, max_value: 5.2, threshold: 6.5, node_ids: ["node-02", "node-04"] },
      { parameter: "Turbidity", count: 814, max_value: 14.2, threshold: 5, node_ids: ["node-03", "node-04"] },
      { parameter: "Dissolved Oxygen", count: 700, max_value: 2.8, threshold: 4.0, node_ids: ["node-05"] },
    ],
    summary: "Quarterly compliance averaged 92.0% across all monitored parameters. Monsoon season contributed to elevated turbidity readings. Lohta Reservoir consistently flagged for TDS violations.",
  },
];

// Monthly compliance trend data
const complianceTrendData = [
  { month: "Jul", compliance: 91.5, readings: 14100 },
  { month: "Aug", compliance: 92.8, readings: 14400 },
  { month: "Sep", compliance: 91.7, readings: 14300 },
  { month: "Oct", compliance: 91.2, readings: 14200 },
  { month: "Nov", compliance: 93.0, readings: 13890 },
  { month: "Dec", compliance: 90.9, readings: 14520 },
];

const PARAMETER_COLORS: Record<string, string> = {
  TDS: "#f87171",
  pH: "#fbbf24",
  Turbidity: "#22d3ee",
  "Dissolved Oxygen": "#a855f7",
};

// ============================================================
// Reports Component
// ============================================================

export default function Reports() {
  const { t } = useTranslation();
  const nodes = useAppStore((s) => s.nodes);

  const [selectedReportId, setSelectedReportId] = useState<string | null>(DEMO_REPORTS[0].id);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isExporting, setIsExporting] = useState<string | null>(null);
  const [periodStart, setPeriodStart] = useState("2026-01-01");
  const [periodEnd, setPeriodEnd] = useState("2026-01-31");

  const selectedReport = DEMO_REPORTS.find((r) => r.id === selectedReportId);

  // Compliance status helper
  const getComplianceStatus = (pct: number) => {
    if (pct >= 95) return { label: "Excellent", color: "text-safe-400", bg: "bg-safe-500/15 border-safe-500/30" };
    if (pct >= 90) return { label: "Good", color: "text-water-400", bg: "bg-water-500/15 border-water-500/30" };
    if (pct >= 80) return { label: "Fair", color: "text-warn-400", bg: "bg-warn-500/15 border-warn-500/30" };
    return { label: "Poor", color: "text-danger-400", bg: "bg-danger-500/15 border-danger-500/30" };
  };

  // Pie chart data from selected report
  const violationPieData = useMemo(() => {
    if (!selectedReport) return [];
    return selectedReport.violations.map((v) => ({
      name: v.parameter,
      value: v.count,
    }));
  }, [selectedReport]);

  // Simulate report generation
  const handleGenerateReport = () => {
    setIsGenerating(true);
    setTimeout(() => {
      setIsGenerating(false);
    }, 2500);
  };

  // Simulate export
  const handleExport = (reportId: string, format: "pdf" | "csv" | "xlsx") => {
    setIsExporting(reportId);
    setTimeout(() => {
      setIsExporting(null);
    }, 1500);
  };

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{t("reports.title")}</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            JJM (Jal Jeevan Mission) compliance tracking and report generation
          </p>
        </div>
      </div>

      {/* Compliance overview cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            Latest {t("reports.compliance")}
          </div>
          <div className={`text-3xl font-bold ${getComplianceStatus(DEMO_REPORTS[0].compliance_percentage).color}`}>
            {DEMO_REPORTS[0].compliance_percentage.toFixed(1)}%
          </div>
          <div className="mt-1">
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${getComplianceStatus(DEMO_REPORTS[0].compliance_percentage).bg}`}>
              {getComplianceStatus(DEMO_REPORTS[0].compliance_percentage).label}
            </span>
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            Total Readings
          </div>
          <div className="text-3xl font-bold text-slate-100">
            {(DEMO_REPORTS[0].total_readings / 1000).toFixed(1)}k
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {DEMO_REPORTS[0].compliant_readings.toLocaleString()} compliant
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            Violations
          </div>
          <div className="text-3xl font-bold text-danger-400">
            {DEMO_REPORTS[0].violations.reduce((sum, v) => sum + v.count, 0).toLocaleString()}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            Across {DEMO_REPORTS[0].violations.length} parameters
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            Reports Generated
          </div>
          <div className="text-3xl font-bold text-slate-100">
            {DEMO_REPORTS.length}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {DEMO_REPORTS.filter((r) => r.period_end >= "2025-10-01").length} in last quarter
          </div>
        </div>
      </div>

      {/* Compliance trend chart + violation breakdown */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Compliance trend (6-month) */}
        <div className="panel xl:col-span-2">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">
              Compliance Trend (6 Months)
            </h3>
            <span className="text-xs text-slate-500">JJM threshold: 90%</span>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={complianceTrendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="month" stroke="#475569" fontSize={11} tickLine={false} />
                <YAxis
                  stroke="#475569"
                  fontSize={11}
                  tickLine={false}
                  domain={[85, 100]}
                  tickFormatter={(v: number) => `${v}%`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(value: number, name: string) => {
                    if (name === "compliance") return [`${value.toFixed(1)}%`, "Compliance"];
                    return [value, name];
                  }}
                />
                {/* JJM threshold reference line */}
                <Bar dataKey="compliance" radius={[6, 6, 0, 0]}>
                  {complianceTrendData.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={entry.compliance >= 95 ? "#34d399" : entry.compliance >= 90 ? "#22d3ee" : "#f87171"}
                      opacity={0.85}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            {/* Threshold indicator */}
            <div className="flex items-center justify-center gap-4 mt-2 text-xs text-slate-500">
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-2 rounded-sm bg-safe-400" />
                <span>Excellent (95%+)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-2 rounded-sm bg-water-400" />
                <span>Good (90-95%)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-2 rounded-sm bg-danger-400" />
                <span>Below Target (&lt;90%)</span>
              </div>
            </div>
          </div>
        </div>

        {/* Violation breakdown pie */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">
              Violation Breakdown
            </h3>
            <span className="text-xs text-slate-500">Latest period</span>
          </div>
          <div className="panel-body flex flex-col items-center">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={violationPieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={75}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {violationPieData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={PARAMETER_COLORS[entry.name] ?? "#64748b"}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(value: number) => [`${value} violations`, ""]}
                />
                <Legend
                  wrapperStyle={{ fontSize: "11px" }}
                  formatter={(value: string) => (
                    <span className="text-slate-400">{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Generate new report section */}
      <div className="panel">
        <div className="panel-header">
          <h3 className="text-sm font-semibold text-slate-200">
            {t("reports.generate")}
          </h3>
        </div>
        <div className="panel-body">
          <div className="flex flex-col sm:flex-row items-start sm:items-end gap-4">
            <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-4 w-full">
              <div>
                <label className="block text-xs text-slate-500 mb-1.5 font-medium">
                  Start Date
                </label>
                <input
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-water-500 focus:border-water-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1.5 font-medium">
                  End Date
                </label>
                <input
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-water-500 focus:border-water-500"
                />
              </div>
            </div>
            <button
              onClick={handleGenerateReport}
              disabled={isGenerating}
              className="flex items-center gap-2 px-5 py-2.5 bg-water-600 hover:bg-water-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors whitespace-nowrap"
            >
              {isGenerating ? (
                <>
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Generating...
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                  {t("reports.generate")}
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Report list + detail */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Report list */}
        <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
          {DEMO_REPORTS.map((report) => {
            const isSelected = report.id === selectedReportId;
            const status = getComplianceStatus(report.compliance_percentage);

            return (
              <div
                key={report.id}
                onClick={() => setSelectedReportId(report.id)}
                className={`panel cursor-pointer transition-all duration-150 ${
                  isSelected
                    ? "border-water-600/50 bg-water-900/10 shadow-lg shadow-water-900/10"
                    : "hover:border-slate-700"
                }`}
              >
                <div className="p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className={`text-lg font-bold tabular-nums ${status.color}`}>
                      {report.compliance_percentage.toFixed(1)}%
                    </span>
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${status.bg}`}>
                      {status.label}
                    </span>
                  </div>
                  <h4 className="text-xs font-medium text-slate-200 mb-1 line-clamp-1">
                    {report.title}
                  </h4>
                  <div className="flex items-center gap-3 text-[10px] text-slate-500">
                    <span>{report.total_readings.toLocaleString()} readings</span>
                    <span>{report.violations.length} parameters violated</span>
                  </div>
                  <div className="text-[10px] text-slate-600 mt-1">
                    {new Date(report.period_start).toLocaleDateString("en-IN", { month: "short", day: "numeric" })}
                    {" - "}
                    {new Date(report.period_end).toLocaleDateString("en-IN", { month: "short", day: "numeric", year: "numeric" })}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Report detail */}
        <div className="xl:col-span-2 space-y-4">
          {selectedReport ? (
            <>
              {/* Report header */}
              <div className="panel">
                <div className="p-4">
                  <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-4">
                    <div>
                      <h2 className="text-lg font-bold text-slate-100">
                        {selectedReport.title}
                      </h2>
                      <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                        <span>
                          {t("reports.period")}:{" "}
                          {new Date(selectedReport.period_start).toLocaleDateString("en-IN")}
                          {" - "}
                          {new Date(selectedReport.period_end).toLocaleDateString("en-IN")}
                        </span>
                        <span>
                          Generated: {new Date(selectedReport.generated_at).toLocaleDateString("en-IN")}
                        </span>
                      </div>
                    </div>

                    {/* Export buttons */}
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {(["pdf", "csv", "xlsx"] as const).map((format) => (
                        <button
                          key={format}
                          onClick={() => handleExport(selectedReport.id, format)}
                          disabled={isExporting === selectedReport.id}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 text-xs font-medium rounded-lg border border-slate-700 transition-colors"
                        >
                          {isExporting === selectedReport.id ? (
                            <svg className="animate-spin w-3 h-3" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                            </svg>
                          ) : (
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                            </svg>
                          )}
                          {format.toUpperCase()}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Summary stats */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <div className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <div className={`text-2xl font-bold ${getComplianceStatus(selectedReport.compliance_percentage).color}`}>
                        {selectedReport.compliance_percentage.toFixed(1)}%
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">{t("reports.compliance")}</div>
                    </div>
                    <div className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <div className="text-2xl font-bold text-slate-100">
                        {selectedReport.total_readings.toLocaleString()}
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Total Readings</div>
                    </div>
                    <div className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <div className="text-2xl font-bold text-safe-400">
                        {selectedReport.compliant_readings.toLocaleString()}
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Compliant</div>
                    </div>
                    <div className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <div className="text-2xl font-bold text-danger-400">
                        {(selectedReport.total_readings - selectedReport.compliant_readings).toLocaleString()}
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Non-Compliant</div>
                    </div>
                  </div>

                  {/* Summary text */}
                  <div className="bg-slate-800/30 rounded-lg p-3 border border-slate-800">
                    <p className="text-sm text-slate-300 leading-relaxed">
                      {selectedReport.summary}
                    </p>
                  </div>
                </div>
              </div>

              {/* Violations table */}
              <div className="panel">
                <div className="panel-header">
                  <h3 className="text-sm font-semibold text-slate-200">
                    Parameter Violations
                  </h3>
                  <span className="text-xs text-slate-500">
                    {selectedReport.violations.length} parameters exceeded thresholds
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-800">
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">Parameter</th>
                        <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">Violations</th>
                        <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">Max Value</th>
                        <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">JJM Threshold</th>
                        <th className="px-4 py-3 text-right text-xs font-medium text-slate-500 uppercase">Exceedance</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 uppercase">Affected Nodes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedReport.violations.map((violation, idx) => {
                        const exceedance = violation.parameter === "pH"
                          ? ((violation.threshold - violation.max_value) / violation.threshold * 100).toFixed(1)
                          : ((violation.max_value - violation.threshold) / violation.threshold * 100).toFixed(1);

                        return (
                          <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2">
                                <span
                                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                  style={{ backgroundColor: PARAMETER_COLORS[violation.parameter] ?? "#64748b" }}
                                />
                                <span className="text-slate-200 font-medium">{violation.parameter}</span>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span className="text-danger-400 font-semibold tabular-nums">{violation.count}</span>
                            </td>
                            <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                              {violation.max_value}
                            </td>
                            <td className="px-4 py-3 text-right tabular-nums text-slate-400">
                              {violation.threshold}
                            </td>
                            <td className="px-4 py-3 text-right">
                              <span className="text-warn-400 font-semibold tabular-nums">
                                {exceedance}%
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-1 flex-wrap">
                                {violation.node_ids.map((nodeId) => {
                                  const node = nodes.find((n) => n.id === nodeId);
                                  return (
                                    <span
                                      key={nodeId}
                                      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700"
                                    >
                                      {node?.name ?? nodeId}
                                    </span>
                                  );
                                })}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Compliance progress bar */}
              <div className="panel">
                <div className="panel-header">
                  <h3 className="text-sm font-semibold text-slate-200">
                    Compliance Breakdown
                  </h3>
                </div>
                <div className="panel-body space-y-4">
                  {/* Overall progress bar */}
                  <div>
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <span className="text-slate-400 font-medium">Overall Compliance</span>
                      <span className={`font-bold ${getComplianceStatus(selectedReport.compliance_percentage).color}`}>
                        {selectedReport.compliance_percentage.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full h-3 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-700 ${
                          selectedReport.compliance_percentage >= 95
                            ? "bg-gradient-to-r from-safe-600 to-safe-400"
                            : selectedReport.compliance_percentage >= 90
                              ? "bg-gradient-to-r from-water-600 to-water-400"
                              : "bg-gradient-to-r from-danger-600 to-danger-400"
                        }`}
                        style={{ width: `${selectedReport.compliance_percentage}%` }}
                      />
                    </div>
                    {/* JJM threshold marker */}
                    <div className="relative mt-0.5">
                      <div className="absolute left-[90%] -translate-x-1/2 flex flex-col items-center">
                        <div className="w-0.5 h-2 bg-slate-500" />
                        <span className="text-[9px] text-slate-500 mt-0.5">90% JJM Target</span>
                      </div>
                    </div>
                  </div>

                  {/* Per-parameter compliance */}
                  <div className="mt-8 space-y-3">
                    {selectedReport.violations.map((violation) => {
                      const violationRate = (violation.count / selectedReport.total_readings) * 100;
                      const paramCompliance = 100 - violationRate;

                      return (
                        <div key={violation.parameter}>
                          <div className="flex items-center justify-between text-xs mb-1">
                            <div className="flex items-center gap-2">
                              <span
                                className="w-2 h-2 rounded-full flex-shrink-0"
                                style={{ backgroundColor: PARAMETER_COLORS[violation.parameter] ?? "#64748b" }}
                              />
                              <span className="text-slate-400">{violation.parameter}</span>
                            </div>
                            <span className="text-slate-300 font-semibold tabular-nums">
                              {paramCompliance.toFixed(1)}%
                            </span>
                          </div>
                          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{
                                width: `${paramCompliance}%`,
                                backgroundColor: PARAMETER_COLORS[violation.parameter] ?? "#64748b",
                                opacity: 0.7,
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="panel">
              <div className="p-12 text-center">
                <svg className="w-12 h-12 mx-auto text-slate-700 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <p className="text-sm text-slate-500">Select a report to view details</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
