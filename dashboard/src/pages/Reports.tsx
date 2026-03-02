import { useState } from "react";
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
} from "recharts";
import type { ComplianceReport, ComplianceViolation } from "../types";

// ============================================================
// Demo compliance data
// ============================================================

const DEMO_REPORTS: ComplianceReport[] = [
  {
    id: "rpt-01",
    title: "December 2025 JJM Compliance Report",
    period_start: "2025-12-01",
    period_end: "2025-12-31",
    generated_at: "2026-01-02T08:00:00Z",
    total_readings: 14_580,
    compliant_readings: 13_843,
    compliance_percentage: 94.9,
    violations: [
      { parameter: "TDS", count: 312, max_value: 1250, threshold: 500, node_ids: ["node-04", "node-05"] },
      { parameter: "pH", count: 189, max_value: 5.2, threshold: 6.5, node_ids: ["node-02", "node-04"] },
      { parameter: "Turbidity", count: 236, max_value: 18.4, threshold: 5, node_ids: ["node-03", "node-04", "node-05"] },
    ],
    summary: "Overall compliance rate of 94.9% meets the JJM minimum of 90%. Two nodes (Lohta Reservoir and Chaukaghat Tank) require attention for recurring TDS and turbidity violations.",
  },
  {
    id: "rpt-02",
    title: "November 2025 JJM Compliance Report",
    period_start: "2025-11-01",
    period_end: "2025-11-30",
    generated_at: "2025-12-02T08:00:00Z",
    total_readings: 13_200,
    compliant_readings: 12_672,
    compliance_percentage: 96.0,
    violations: [
      { parameter: "TDS", count: 198, max_value: 980, threshold: 500, node_ids: ["node-04"] },
      { parameter: "Turbidity", count: 330, max_value: 22.1, threshold: 5, node_ids: ["node-03", "node-04"] },
    ],
    summary: "Compliance improved from previous month. Heavy monsoon rains caused turbidity spikes across multiple nodes.",
  },
  {
    id: "rpt-03",
    title: "October 2025 JJM Compliance Report",
    period_start: "2025-10-01",
    period_end: "2025-10-31",
    generated_at: "2025-11-02T08:00:00Z",
    total_readings: 14_880,
    compliant_readings: 13_690,
    compliance_percentage: 92.0,
    violations: [
      { parameter: "TDS", count: 480, max_value: 1450, threshold: 500, node_ids: ["node-04", "node-05"] },
      { parameter: "pH", count: 310, max_value: 4.8, threshold: 6.5, node_ids: ["node-02", "node-04", "node-05"] },
      { parameter: "Turbidity", count: 400, max_value: 25.3, threshold: 5, node_ids: ["node-03", "node-04", "node-05"] },
    ],
    summary: "Post-monsoon period showed elevated TDS and turbidity. Emergency filtration deployed at Lohta Reservoir.",
  },
];

// Monthly compliance trend
const complianceTrend = [
  { month: "Jul", compliance: 97.2 },
  { month: "Aug", compliance: 95.8 },
  { month: "Sep", compliance: 93.1 },
  { month: "Oct", compliance: 92.0 },
  { month: "Nov", compliance: 96.0 },
  { month: "Dec", compliance: 94.9 },
];

// Parameter violation breakdown for pie chart
const violationBreakdown = [
  { name: "TDS", value: 312, color: "#22d3ee" },
  { name: "pH", value: 189, color: "#fbbf24" },
  { name: "Turbidity", value: 236, color: "#f87171" },
  { name: "DO", value: 45, color: "#a855f7" },
];

// ============================================================
// Reports Component
// ============================================================

export default function Reports() {
  const { t } = useTranslation();
  const [selectedReport, setSelectedReport] = useState<ComplianceReport>(DEMO_REPORTS[0]);
  const [generating, setGenerating] = useState(false);

  // Generate report (mock)
  const handleGenerate = () => {
    setGenerating(true);
    setTimeout(() => setGenerating(false), 2000);
  };

  // Export report (mock)
  const handleExport = (format: "pdf" | "csv" | "xlsx") => {
    console.log(`Exporting report ${selectedReport.id} as ${format}`);
    // In real implementation, call exportReport API
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">{t("reports.title")}</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Jal Jeevan Mission water quality compliance reporting
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="btn-primary flex items-center gap-2"
          >
            {generating ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
            )}
            {generating ? "Generating..." : t("reports.generate")}
          </button>
        </div>
      </div>

      {/* Compliance overview cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">{t("reports.compliance")}</div>
          <div className={`text-3xl font-bold ${
            selectedReport.compliance_percentage >= 95 ? "text-safe-400" :
            selectedReport.compliance_percentage >= 90 ? "text-warn-400" :
            "text-danger-400"
          }`}>
            {selectedReport.compliance_percentage.toFixed(1)}%
          </div>
          <div className="text-xs text-slate-500 mt-1">
            JJM minimum: 90%
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Total Readings</div>
          <div className="text-3xl font-bold text-slate-100">{selectedReport.total_readings.toLocaleString()}</div>
          <div className="text-xs text-safe-400 mt-1">
            {selectedReport.compliant_readings.toLocaleString()} compliant
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Violations</div>
          <div className="text-3xl font-bold text-danger-400">
            {selectedReport.violations.reduce((s, v) => s + v.count, 0)}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {selectedReport.violations.length} parameters affected
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">{t("reports.period")}</div>
          <div className="text-lg font-bold text-slate-200">
            {new Date(selectedReport.period_start).toLocaleDateString("en-IN", { month: "short", year: "numeric" })}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {new Date(selectedReport.period_start).toLocaleDateString("en-IN", { day: "numeric", month: "short" })} - {new Date(selectedReport.period_end).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Compliance trend */}
        <div className="panel xl:col-span-2">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">Compliance Trend (6 Months)</h3>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={complianceTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="month" stroke="#475569" fontSize={11} />
                <YAxis stroke="#475569" fontSize={11} domain={[85, 100]} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(v: number) => [`${v}%`, "Compliance"]}
                />
                {/* JJM threshold line */}
                <Bar dataKey="compliance" radius={[4, 4, 0, 0]}>
                  {complianceTrend.map((entry, idx) => (
                    <Cell
                      key={idx}
                      fill={entry.compliance >= 95 ? "#34d399" : entry.compliance >= 90 ? "#fbbf24" : "#f87171"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-2 flex items-center justify-center gap-4 text-xs text-slate-500">
              <div className="flex items-center gap-1">
                <span className="w-3 h-1.5 rounded bg-safe-400" />
                <span>&ge; 95%</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="w-3 h-1.5 rounded bg-warn-400" />
                <span>90-95%</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="w-3 h-1.5 rounded bg-danger-400" />
                <span>&lt; 90%</span>
              </div>
              <div className="flex items-center gap-1 border-l border-slate-700 pl-4">
                <span className="w-6 h-px bg-danger-400 border-t border-dashed border-danger-400" />
                <span>JJM Min (90%)</span>
              </div>
            </div>
          </div>
        </div>

        {/* Violation breakdown pie */}
        <div className="panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">Violation Breakdown</h3>
          </div>
          <div className="panel-body">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={violationBreakdown}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={75}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {violationBreakdown.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap justify-center gap-3 mt-2">
              {violationBreakdown.map((v) => (
                <div key={v.name} className="flex items-center gap-1.5 text-xs text-slate-400">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: v.color }} />
                  {v.name}: {v.value}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Report list + detail */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Report list */}
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-300 mb-3">Previous Reports</h3>
          {DEMO_REPORTS.map((report) => (
            <div
              key={report.id}
              onClick={() => setSelectedReport(report)}
              className={`panel cursor-pointer transition-all ${
                selectedReport.id === report.id
                  ? "border-water-600/50 bg-water-900/10"
                  : "hover:border-slate-700"
              }`}
            >
              <div className="p-3">
                <h4 className="text-sm font-medium text-slate-200 truncate">{report.title}</h4>
                <div className="flex items-center justify-between mt-2">
                  <span className={`text-lg font-bold ${
                    report.compliance_percentage >= 95 ? "text-safe-400" :
                    report.compliance_percentage >= 90 ? "text-warn-400" :
                    "text-danger-400"
                  }`}>
                    {report.compliance_percentage.toFixed(1)}%
                  </span>
                  <span className="text-xs text-slate-500">
                    {new Date(report.generated_at).toLocaleDateString("en-IN", { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Report detail */}
        <div className="xl:col-span-2 panel">
          <div className="panel-header">
            <h3 className="text-sm font-semibold text-slate-200">{selectedReport.title}</h3>
            <div className="flex items-center gap-2">
              <button onClick={() => handleExport("pdf")} className="btn-secondary text-xs px-3 py-1">
                PDF
              </button>
              <button onClick={() => handleExport("csv")} className="btn-secondary text-xs px-3 py-1">
                CSV
              </button>
              <button onClick={() => handleExport("xlsx")} className="btn-secondary text-xs px-3 py-1">
                Excel
              </button>
            </div>
          </div>
          <div className="panel-body space-y-4">
            {/* Summary */}
            <div className="bg-slate-800/40 rounded-lg p-4 border border-slate-800">
              <h4 className="text-xs font-semibold text-slate-400 uppercase mb-2">Summary</h4>
              <p className="text-sm text-slate-300 leading-relaxed">{selectedReport.summary}</p>
            </div>

            {/* Compliance bar */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-slate-500">Overall Compliance</span>
                <span className={`text-sm font-bold ${
                  selectedReport.compliance_percentage >= 95 ? "text-safe-400" :
                  selectedReport.compliance_percentage >= 90 ? "text-warn-400" :
                  "text-danger-400"
                }`}>
                  {selectedReport.compliance_percentage.toFixed(1)}%
                </span>
              </div>
              <div className="w-full h-3 bg-slate-800 rounded-full overflow-hidden relative">
                {/* JJM threshold marker */}
                <div className="absolute left-[90%] top-0 w-px h-full bg-danger-500 z-10" />
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    selectedReport.compliance_percentage >= 95 ? "bg-safe-500" :
                    selectedReport.compliance_percentage >= 90 ? "bg-warn-500" :
                    "bg-danger-500"
                  }`}
                  style={{ width: `${selectedReport.compliance_percentage}%` }}
                />
              </div>
            </div>

            {/* Violations table */}
            <div>
              <h4 className="text-xs font-semibold text-slate-400 uppercase mb-3">Violations Detail</h4>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800">
                    <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">Parameter</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">Count</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">Max Value</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-slate-500">Threshold</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-slate-500">Affected Nodes</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedReport.violations.map((v, idx) => (
                    <tr key={idx} className="border-b border-slate-800/50">
                      <td className="px-3 py-2 text-slate-200 font-medium">{v.parameter}</td>
                      <td className="px-3 py-2 text-right text-danger-400 font-semibold tabular-nums">{v.count}</td>
                      <td className="px-3 py-2 text-right text-slate-300 tabular-nums">{v.max_value}</td>
                      <td className="px-3 py-2 text-right text-slate-500 tabular-nums">{v.threshold}</td>
                      <td className="px-3 py-2 text-xs text-slate-400">{v.node_ids.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Report metadata */}
            <div className="flex items-center justify-between text-xs text-slate-600 pt-2 border-t border-slate-800">
              <span>Generated: {new Date(selectedReport.generated_at).toLocaleString("en-IN")}</span>
              <span>{selectedReport.total_readings.toLocaleString()} readings analyzed</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
