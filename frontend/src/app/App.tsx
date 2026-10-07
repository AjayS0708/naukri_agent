import { useEffect, useState } from "react";
import { Activity, Bot, BriefcaseBusiness, ChartNoAxesColumn, CircleAlert, Settings, Sparkles, BarChart3, LayoutDashboard, User, Bell, Menu, X, MoreHorizontal } from "lucide-react";
import { getDashboardSummary, getHealth, getNotifications, getRecentApplications } from "../services/api";
import type { DashboardSummary, HealthResponse, Notification, ProfileResponse, RecentApplicationItem } from "../types/api";
import { ProfileWorkspace } from "../components/ProfileWorkspace";
import { AIStatus } from "../components/AIStatus";
import { JobPreferences } from "../components/JobPreferences";
import { AgentControl } from "../components/AgentControl";
import { AnalyticsDashboard } from "../components/AnalyticsDashboard";
import { BackendState } from "../components/BackendState";

const STATUS_LABEL: Record<string, string> = {
  APPLIED: "Applied",
  SUBMITTED: "Submitted",
  NEEDS_ATTENTION: "Needs attention",
  SKIPPED: "Skipped",
  EXTERNAL_APPLICATION: "External",
  FAILED: "Failed",
  APPLICATION_STARTED: "Started",
  PRE_APPLY: "Pre-apply",
  DISCOVERED: "Discovered",
  FILTERED: "Filtered",
  AI_ANALYZED: "AI Analyzed",
  APPROVED_BY_RULES: "Approved",
};

function fmtStatus(s: string): string {
  return STATUS_LABEL[s] ?? s.replace(/_/g, " ");
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [currentPage, setCurrentPage] = useState<"overview" | "profile" | "preferences" | "analytics" | "activity">("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [dashboardError, setDashboardError] = useState(false);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [recentApps, setRecentApps] = useState<RecentApplicationItem[]>([]);
  const [recentAppsLoading, setRecentAppsLoading] = useState(true);
  const [recentAppsError, setRecentAppsError] = useState(false);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setFailed(true));
    getNotifications().then((response) => setNotifications(response.notifications)).catch(() => setNotifications([]));

    // Dashboard summary (discovery + applications + profile status)
    setDashboardLoading(true);
    getDashboardSummary()
      .then((data) => { setDashboard(data); setDashboardError(false); })
      .catch(() => setDashboardError(true))
      .finally(() => setDashboardLoading(false));

    // Recent applications with job title/company
    setRecentAppsLoading(true);
    getRecentApplications(10)
      .then((data) => { setRecentApps(data.applications); setRecentAppsError(false); })
      .catch(() => setRecentAppsError(true))
      .finally(() => setRecentAppsLoading(false));
  }, []);

  const connection = failed ? "local_offline" : health ? "connected" : "checking";
  // Use dashboard profile data when available; fall back to local profile state
  const profileStatus = dashboard?.profile.status ?? profile?.status ?? null;
  const profileConfirmed = dashboard?.profile.confirmed ?? profile?.confirmed ?? false;
  const profileFilename = dashboard?.profile.original_filename ?? profile?.original_filename ?? null;
  const profileSummary = profileStatus ? profileStatus.replaceAll("_", " ") : "Not configured";
  const agentState = health?.agent_state.replaceAll("_", " ") ?? "NOT RUNNING";

  const handleRetry = () => {
    setFailed(false);
    setDashboardError(false);
    setRecentAppsError(false);

    getHealth().then(setHealth).catch(() => setFailed(true));

    setDashboardLoading(true);
    getDashboardSummary()
      .then((data) => { setDashboard(data); setDashboardError(false); })
      .catch(() => setDashboardError(true))
      .finally(() => setDashboardLoading(false));

    setRecentAppsLoading(true);
    getRecentApplications(10)
      .then((data) => { setRecentApps(data.applications); setRecentAppsError(false); })
      .catch(() => setRecentAppsError(true))
      .finally(() => setRecentAppsLoading(false));
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

            {/* Metrics — real data from /api/dashboard/summary */}
            <section className="metrics">
              <article className="metric">
                <BriefcaseBusiness size={20} />
                <p>Applications total</p>
                <strong aria-live="polite">
                  {dashboardLoading ? "…" : dashboardError ? "—" : dashboard!.applications.applied}
                </strong>
              </article>
              <article className="metric">
                <ChartNoAxesColumn size={20} />
                <p>Jobs discovered</p>
                <strong aria-live="polite">
                  {dashboardLoading ? "…" : dashboardError ? "Unavailable" : dashboard!.discovery.jobs_discovered}
                </strong>
              </article>
              <article className="metric">
                <Sparkles size={20} />
                <p>Discovery runs</p>
                <strong aria-live="polite">
                  {dashboardLoading ? "…" : dashboardError ? "Unavailable" : dashboard!.discovery.total_runs}
                </strong>
              </article>
              <article className="metric">
                <CircleAlert size={20} />
                <p>Needs attention</p>
                <strong aria-live="polite">
                  {dashboardLoading ? "…" : dashboardError ? "—" : dashboard!.applications.needs_attention}
                </strong>
              </article>
            </section>

            {/* Profile panel — real data from dashboard summary */}
            <section className="status-panel">
              <div>
                <p className="eyebrow">PROFILE</p>
                <strong>{profileSummary}</strong>
                <p>{profileConfirmed ? "Profile confirmed for automation." : "Resume/profile review is required before automation."}</p>
              </div>
              <div className="status-meta">
                <span>Resume</span>
                <b>{profileFilename ?? "Not uploaded"}</b>
              </div>
            </section>

            <section id="ai-status"><AIStatus /></section>

            <section className="activity" aria-labelledby="notifications-heading">
              <div>
                <p className="eyebrow">NOTIFICATIONS</p>
                <h2 id="notifications-heading">Recent notifications</h2>
              </div>
              {notifications.length === 0 ? <p>No notifications recorded.</p> : (
                <ul>
                  {notifications.slice(0, 5).map((notification) => (
                    <li key={notification.id}>
                      <strong>{notification.title}</strong> — {notification.message}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="activity">
              <div>
                <p className="eyebrow">RECENT ACTIVITY</p>
                <h2>Latest applications</h2>
              </div>
              {recentAppsLoading ? (
                <p className="text-[var(--color-text-secondary)]">Loading activity…</p>
              ) : recentAppsError ? (
                <p className="error-text">Activity data unavailable. Please retry.</p>
              ) : recentApps.length === 0 ? (
                <p>No applications recorded yet. Run the agent to begin.</p>
              ) : (
                <ul>
                  {recentApps.map((app) => (
                    <li key={app.application_id}>
                      <strong>{app.job_title}</strong> at {app.company}
                      {" — "}
                      <span>{fmtStatus(app.status)}</span>
                      {app.applied_at && <span className="text-[var(--color-text-secondary)]"> · {fmtDate(app.applied_at)}</span>}
                      {app.is_dry_run && <span className="text-[var(--color-text-secondary)]"> (dry run)</span>}
                    </li>
                  ))}
                </ul>
              )}
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
              <h2>Application History</h2>
            </div>
            {recentAppsLoading ? (
              <p className="text-[var(--color-text-secondary)]">Loading activity…</p>
            ) : recentAppsError ? (
              <p className="error-text">Activity data unavailable. Backend may be offline.</p>
            ) : recentApps.length === 0 ? (
              <p>No applications recorded yet. Start the agent to begin tracking events.</p>
            ) : (
              <ul>
                {recentApps.map((app) => (
                  <li key={app.application_id}>
                    <strong>{app.job_title}</strong> at {app.company}
                    {" — "}
                    <span>{fmtStatus(app.status)}</span>
                    {app.applied_at
                      ? <span className="text-[var(--color-text-secondary)]"> · Applied {fmtDate(app.applied_at)}</span>
                      : <span className="text-[var(--color-text-secondary)]"> · {fmtDate(app.created_at)}</span>}
                    {app.application_method && <span className="text-[var(--color-text-secondary)]"> · {app.application_method.replace("_", " ")}</span>}
                    {app.is_dry_run && <span className="text-[var(--color-text-secondary)]"> (dry run)</span>}
                    {app.needs_attention && <span style={{ color: "var(--color-warning)" }}> ⚠ Needs attention</span>}
                    {app.skip_reason && <span className="text-[var(--color-text-secondary)]"> · {app.skip_reason}</span>}
                  </li>
                ))}
              </ul>
            )}
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
