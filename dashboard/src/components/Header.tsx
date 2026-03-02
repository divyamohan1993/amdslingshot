import { useTranslation } from "react-i18next";
import { useAppStore } from "../stores/appStore";
import type { ConnectionState } from "../services/websocket";

interface HeaderProps {
  onMenuToggle: () => void;
}

const connectionLabels: Record<ConnectionState, { text: string; color: string }> = {
  connected: { text: "Live", color: "bg-safe-400" },
  connecting: { text: "Connecting...", color: "bg-warn-400" },
  disconnecting: { text: "Disconnecting", color: "bg-warn-400" },
  disconnected: { text: "Offline", color: "bg-slate-500" },
};

export default function Header({ onMenuToggle }: HeaderProps) {
  const { t, i18n } = useTranslation();
  const wsState = useAppStore((s) => s.wsConnectionState);
  const systemHealth = useAppStore((s) => s.systemHealth);
  const language = useAppStore((s) => s.language);
  const setLanguage = useAppStore((s) => s.setLanguage);

  const connInfo = connectionLabels[wsState];

  const handleLanguageChange = (lang: "en" | "hi") => {
    setLanguage(lang);
    i18n.changeLanguage(lang);
  };

  return (
    <header className="flex items-center justify-between px-4 py-3 bg-slate-900/80 backdrop-blur-sm border-b border-slate-800 z-20">
      {/* Left: Menu toggle (mobile) */}
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuToggle}
          className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          aria-label="Toggle menu"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>

        {/* Connection status */}
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connInfo.color} ${wsState === "connected" ? "animate-pulse" : ""}`} />
          <span className="text-xs font-medium text-slate-400">{connInfo.text}</span>
        </div>
      </div>

      {/* Center: System health summary (desktop) */}
      {systemHealth && (
        <div className="hidden md:flex items-center gap-6 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Nodes:</span>
            <span className="text-safe-400 font-semibold">{systemHealth.online_nodes}</span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-400">{systemHealth.total_nodes}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Alerts:</span>
            <span className={`font-semibold ${systemHealth.critical_alerts > 0 ? "text-danger-400" : "text-slate-400"}`}>
              {systemHealth.active_alerts}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Quality:</span>
            <span className="text-water-400 font-semibold">
              {systemHealth.avg_water_quality.toFixed(0)}%
            </span>
          </div>
        </div>
      )}

      {/* Right: Language selector + actions */}
      <div className="flex items-center gap-2">
        {/* Language toggle */}
        <div className="flex items-center bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <button
            onClick={() => handleLanguageChange("en")}
            className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
              language === "en"
                ? "bg-water-600 text-white"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            EN
          </button>
          <button
            onClick={() => handleLanguageChange("hi")}
            className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
              language === "hi"
                ? "bg-water-600 text-white"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            HI
          </button>
        </div>

        {/* Settings/profile placeholder */}
        <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
