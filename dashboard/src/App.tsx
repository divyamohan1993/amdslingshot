import { Routes, Route, Navigate } from "react-router-dom";
import { useEffect } from "react";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import AlertBanner from "./components/AlertBanner";
import Dashboard from "./pages/Dashboard";
import FarmerView from "./pages/FarmerView";
import Alerts from "./pages/Alerts";
import Predictions from "./pages/Predictions";
import Nodes from "./pages/Nodes";
import Reports from "./pages/Reports";
import { useAppStore } from "./stores/appStore";
import { useWebSocket } from "./hooks/useWebSocket";

export default function App() {
  const { sidebarOpen, toggleSidebar } = useAppStore();
  useWebSocket();

  // Close sidebar on mobile when navigating
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024) {
        useAppStore.getState().setSidebarOpen(true);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <Sidebar isOpen={sidebarOpen} onToggle={toggleSidebar} />

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-30 lg:hidden"
          onClick={() => useAppStore.getState().setSidebarOpen(false)}
        />
      )}

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header onMenuToggle={toggleSidebar} />
        <AlertBanner />

        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/farmer" element={<FarmerView />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/predictions" element={<Predictions />} />
            <Route path="/nodes" element={<Nodes />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
