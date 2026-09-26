import { useEffect, useState } from "react";
import { Activity, Bot, BriefcaseBusiness, ChartNoAxesColumn, CircleAlert, Settings, Sparkles, BarChart3, LayoutDashboard, User, Bell, Menu, X, MoreHorizontal } from "lucide-react";
import { getHealth } from "../services/api";
import type { HealthResponse, ProfileResponse } from "../types/api";
import { ProfileWorkspace } from "../components/ProfileWorkspace";
import { AIStatus } from "../components/AIStatus";
import { JobPreferences } from "../components/JobPreferences";
import { AgentControl } from "../components/AgentControl";
import { AnalyticsDashboard } from "../components/AnalyticsDashboard";
import { BackendState } from "../components/BackendState";

const metrics = [["Applications today", "0", BriefcaseBusiness], ["Jobs discovered", "Not available", ChartNoAxesColumn], ["Jobs analyzed", "Not available", Sparkles], ["Needs attention", "0", CircleAlert]] as const;

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [currentPage, setCurrentPage] = useState<"overview" | "profile" | "preferences" | "analytics" | "activity">("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => { getHealth().then(setHealth).catch(() => setFailed(true)); }, []);

  const connection = failed ? "local_offline" : health ? "connected" : "checking";
  const profileSummary = profile?.status ? profile.status.replaceAll("_", " ") : "Not configured";
  const agentState = health?.agent_state.replaceAll("_", " ") ?? "NOT RUNNING";

  const handleRetry = () => {
    setFailed(false);
    getHealth().then(setHealth).catch(() => setFailed(true));
  };

  const handleNavClick = (page: typeof currentPage) => {
    setCurrentPage(page);
    setSidebarOpen(false);
  };

  const closeSidebar = () => setSidebarOpen(false);

  return <main className="app-shell">
    <a href="#main-content" className="skip-to-content">Skip to main content</a>

    {/* Mobile Header */}
    <header className="mobile-header">
      <button
        className="mobile-menu-button"
        onClick={() => setSidebarOpen(!sidebarOpen)}
        aria-label={sidebarOpen ? "Close navigation menu" : "Open navigation menu"}
      >
        {sidebarOpen ? <X size={24} /> : <Menu size={24} />}
      </button>
      <div className="mobile-header-brand">
        <Bot size={20} />
        <span>Naukri Agent</span>
      </div>
      <button className="icon-button" aria-label="Notifications"><Bell size={20} /></button>
    </header>

    {/* Sidebar Backdrop for Mobile */}
    {sidebarOpen && <div className="sidebar-backdrop" onClick={closeSidebar} role="presentation" />}

    <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
      <div className="brand"><Bot size={24} /><span>Naukri Agent</span></div>
      <nav aria-label="Primary navigation">
        <a className={`nav-item ${currentPage === "overview" ? "active" : ""}`} href="#overview" onClick={(e) => { e.preventDefault(); handleNavClick("overview"); }}><LayoutDashboard size={18} />Overview</a>
        <a className={`nav-item ${currentPage === "activity" ? "active" : ""}`} href="#activity" onClick={(e) => { e.preventDefault(); handleNavClick("activity"); }}><Activity size={18} />Activity</a>
        <span className="nav-item disabled"><BriefcaseBusiness size={18} />Jobs</span>
        <span className="nav-item disabled"><ChartNoAxesColumn size={18} />Applications</span>
        <a className={`nav-item ${currentPage === "analytics" ? "active" : ""}`} href="#analytics" onClick={(e) => { e.preventDefault(); handleNavClick("analytics"); }}><BarChart3 size={18} />Analytics</a>
        <a className={`nav-item ${currentPage === "profile" ? "active" : ""}`} href="#profile" onClick={(e) => { e.preventDefault(); handleNavClick("profile"); }}><User size={18} />Profile</a>
        <a className={`nav-item ${currentPage === "preferences" ? "active" : ""}`} href="#preferences" onClick={(e) => { e.preventDefault(); handleNavClick("preferences"); }}><Settings size={18} />Preferences</a>
      </nav>
      <div className="sidebar-footer">
        <div className="agent-status-indicator">
          <span className={`status-dot ${agentState === "RUNNING" ? "running" : agentState === "PAUSED" ? "paused" : "stopped"}`} />
          <span className="status-text">{agentState}</span>
        </div>
      </div>
    </aside>

    <section className="main-content">
      <header className="topbar">
        <div className="page-header">
          <p className="eyebrow">DASHBOARD</p>
          <h1>{currentPage === "overview" ? "Agent Overview" : currentPage === "profile" ? "Profile" : currentPage === "preferences" ? "Preferences" : currentPage === "analytics" ? "Analytics" : "Activity"}</h1>
          <p className="page-description">{currentPage === "overview" ? "Monitor and control your job search automation" : currentPage === "profile" ? "Manage your resume and professional profile" : currentPage === "preferences" ? "Configure job search preferences and automation settings" : currentPage === "analytics" ? "View performance metrics and decision analytics" : "Track agent activity and events"}</p>
        </div>
        <div className="topbar-actions">
          <BackendState status={connection as any} onRetry={handleRetry} />
          <button className="icon-button" aria-label="Notifications"><Bell size={20} /></button>
        </div>
      </header>

      <div className="content-area" id="main-content" tabIndex={-1}>
        {currentPage === "overview" && (
          <>
            <section className="status-panel">
              <div>
                <p className="eyebrow">AGENT STATUS</p>
                <strong className={`agent-state ${health?.agent_state.toLowerCase() || "idle"}`}>{agentState}</strong>
                <p>Configure your profile and preferences to enable automation.</p>
              </div>
              <div className="status-meta">
                <span>Backend</span>
                <b>{health ? `${health.service} v${health.version}` : "Not available"}</b>
              </div>
            </section>

            <section id="agent-control"><AgentControl /></section>

            <section className="metrics">
              {metrics.map(([label, value, Icon]) => (
                <article className="metric" key={label}>
                  <Icon size={20} />
                  <p>{label}</p>
                  <strong>{value}</strong>
                </article>
              ))}
            </section>

            <section className="status-panel">
              <div>
                <p className="eyebrow">PROFILE</p>
                <strong>{profileSummary}</strong>
                <p>{profile?.confirmed ? "Profile confirmed for automation." : "Resume/profile review is required before automation."}</p>
              </div>
              <div className="status-meta">
                <span>Resume</span>
                <b>{profile?.original_filename ?? "Not uploaded"}</b>
              </div>
            </section>

            <section id="ai-status"><AIStatus /></section>

            <section className="activity">
              <div>
                <p className="eyebrow">TODAY'S ACTIVITY</p>
                <h2>Agent Activity</h2>
              </div>
              <p>No discovery, AI analysis, or application actions have been enabled.</p>
            </section>

            <section id="analytics-dashboard"><AnalyticsDashboard /></section>
          </>
        )}

        {currentPage === "profile" && (
          <section id="profile"><ProfileWorkspace onProfileChange={setProfile} /></section>
        )}

        {currentPage === "preferences" && (
          <section id="preferences"><JobPreferences /></section>
        )}

        {currentPage === "analytics" && (
          <section id="analytics-dashboard"><AnalyticsDashboard /></section>
        )}

        {currentPage === "activity" && (
          <section className="activity">
            <div>
              <p className="eyebrow">ACTIVITY</p>
              <h2>Agent Activity</h2>
            </div>
            <p>No activity recorded yet. Start the agent to begin tracking events.</p>
          </section>
        )}
      </div>
    </section>

    {/* Mobile Bottom Navigation */}
    <nav className="bottom-navigation">
      <button
        className={`bottom-nav-item ${currentPage === "overview" ? "active" : ""}`}
        onClick={() => handleNavClick("overview")}
        aria-label="Overview"
      >
        <LayoutDashboard size={20} />
        <span>Home</span>
      </button>
      <button
        className={`bottom-nav-item ${currentPage === "activity" ? "active" : ""}`}
        onClick={() => handleNavClick("activity")}
        aria-label="Activity"
      >
        <Activity size={20} />
        <span>Activity</span>
      </button>
      <button className="bottom-nav-item" disabled aria-label="Jobs (disabled)">
        <BriefcaseBusiness size={20} />
        <span>Jobs</span>
      </button>
      <button className="bottom-nav-item" disabled aria-label="Applications (disabled)">
        <ChartNoAxesColumn size={20} />
        <span>Apps</span>
      </button>
      <button
        className={`bottom-nav-item ${["analytics", "profile", "preferences"].includes(currentPage) ? "active" : ""}`}
        onClick={() => setCurrentPage("analytics")}
        aria-label="More options"
      >
        <MoreHorizontal size={20} />
        <span>More</span>
      </button>
    </nav>
  </main>;
}
