import { useEffect, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  Bell,
  BriefcaseBusiness,
  ChartNoAxesColumn,
  LayoutDashboard,
  ListChecks,
  Menu,
  RefreshCw,
  Settings,
  ShieldAlert,
  Sparkles,
  User,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  getAutonomousCycleStatus,
  getDashboardSummary,
  getHealth,
  getNeedsAttention,
  getNotifications,
  getRecentApplications,
  startAutonomousCycle,
  stopAutonomousCycle,
} from "../services/api";
import type {
  AutonomousCycleStatusResponse,
  DashboardSummary,
  HealthResponse,
  NeedsAttentionItem,
  Notification,
  ProfileResponse,
  RecentApplicationItem,
} from "../types/api";
import { ShellContext, type NavigateOptions, type PageId } from "./shell";
import { OverviewPage } from "../pages/OverviewPage";
import { JobsPage } from "../pages/JobsPage";
import { ApplyQueuePage } from "../pages/ApplyQueuePage";
import { ApplicationsPage } from "../pages/ApplicationsPage";
import { NeedsAttentionPage } from "../pages/NeedsAttentionPage";
import { AIQueuePage } from "../pages/AIQueuePage";
import { NotificationsPage } from "../pages/NotificationsPage";
import { AnalyticsPage } from "../pages/AnalyticsPage";
import { ActivityPage } from "../pages/ActivityPage";
import { ProfilePage } from "../pages/ProfilePage";
import { PreferencesPage } from "../pages/PreferencesPage";
import { agentStateTone } from "../ui/status";

interface NavItem {
  id: PageId;
  label: string;
  icon: LucideIcon;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Work",
    items: [
      { id: "overview", label: "Overview", icon: LayoutDashboard },
      { id: "jobs", label: "Jobs", icon: BriefcaseBusiness },
      { id: "apply", label: "Apply Queue", icon: ListChecks },
      { id: "applications", label: "Applications", icon: ChartNoAxesColumn },
      { id: "attention", label: "Needs Attention", icon: ShieldAlert },
      { id: "ai-queue", label: "AI Queue", icon: Sparkles },
    ],
  },
  {
    label: "Insights",
    items: [
      { id: "analytics", label: "Analytics", icon: BarChart3 },
      { id: "activity", label: "Activity", icon: Activity },
      { id: "notifications", label: "Notifications", icon: Bell },
    ],
  },
  {
    label: "Settings",
    items: [
      { id: "profile", label: "Profile", icon: User },
      { id: "preferences", label: "Preferences", icon: Settings },
    ],
  },
];

const PAGE_META: Record<PageId, { label: string; group: string }> = {
  overview: { label: "Overview", group: "Work" },
  jobs: { label: "Jobs", group: "Work" },
  apply: { label: "Apply Queue", group: "Work" },
  applications: { label: "Applications", group: "Work" },
  attention: { label: "Needs Attention", group: "Work" },
  "ai-queue": { label: "AI Queue", group: "Work" },
  analytics: { label: "Analytics", group: "Insights" },
  activity: { label: "Activity", group: "Insights" },
  notifications: { label: "Notifications", group: "Insights" },
  profile: { label: "Profile", group: "Settings" },
  preferences: { label: "Preferences", group: "Settings" },
};

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [currentPage, setCurrentPage] = useState<PageId>("overview");
  const [navSeq, setNavSeq] = useState(0);
  const [navQuery, setNavQuery] = useState<string | null>(null);
  const [applicationsFilter, setApplicationsFilter] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [dashboardError, setDashboardError] = useState(false);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [recentApps, setRecentApps] = useState<RecentApplicationItem[]>([]);
  const [recentAppsLoading, setRecentAppsLoading] = useState(true);
  const [recentAppsError, setRecentAppsError] = useState(false);
  const [needsAttention, setNeedsAttention] = useState<NeedsAttentionItem[]>([]);
  const [needsAttentionLoading, setNeedsAttentionLoading] = useState(true);
  const [needsAttentionError, setNeedsAttentionError] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const [cycleStatus, setCycleStatus] = useState<AutonomousCycleStatusResponse | null>(null);
  const [showRunConfirmation, setShowRunConfirmation] = useState(false);
  const [startCycleLoading, setStartCycleLoading] = useState(false);
  const [stopCycleLoading, setStopCycleLoading] = useState(false);
  const [cycleConflict, setCycleConflict] = useState(false);
  const cycleRequestInFlight = startCycleLoading || stopCycleLoading;
  const startCycleInFlightRef = useRef(false);
  const [answerNotice, setAnswerNotice] = useState<string | null>(null);

  const fetchDashboardData = async () => {
    setDashboardLoading(true);
    setRecentAppsLoading(true);
    setNeedsAttentionLoading(true);
    await Promise.all([
      getDashboardSummary()
        .then((data) => { setDashboard(data); setDashboardError(false); })
        .catch(() => setDashboardError(true)),
      getRecentApplications(10)
        .then((data) => { setRecentApps(data.applications); setRecentAppsError(false); })
        .catch(() => setRecentAppsError(true)),
      getNeedsAttention(10)
        .then((data) => { setNeedsAttention(data.applications); setNeedsAttentionError(false); })
        .catch(() => setNeedsAttentionError(true)),
    ]).finally(() => {
      setDashboardLoading(false);
      setRecentAppsLoading(false);
      setNeedsAttentionLoading(false);
    });
  };

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setFailed(true));
    getNotifications(50).then((response) => setNotifications(response.notifications)).catch(() => setNotifications([]));
    void fetchDashboardData();
    getAutonomousCycleStatus()
      .then((data) => { setCycleStatus(data); setCycleConflict(false); })
      .catch(() => setCycleStatus(null));
  }, []);

  const cycleActiveRef = useRef(false);
  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    const refreshDashboardAfterRun = () => {
      void fetchDashboardData();
      getNotifications(50)
        .then((response) => setNotifications(response.notifications))
        .catch(() => undefined);
    };

    const pollOnce = async () => {
      try {
        const data = await getAutonomousCycleStatus();
        if (stopped) return;
        const wasActive = cycleActiveRef.current;
        const isActive = data.active_state === "RUNNING";
        cycleActiveRef.current = isActive;
        setCycleStatus(data);
        setCycleConflict(false);
        if (wasActive && !isActive) refreshDashboardAfterRun();
      } catch {
        // A single failed fetch must not kill polling.
      } finally {
        if (!stopped) {
          timer = window.setTimeout(pollOnce, cycleActiveRef.current ? 4000 : 10000);
        }
      }
    };

    void pollOnce();

    const healthTimer = window.setInterval(() => {
      if (!stopped) {
        getHealth().then(setHealth).catch(() => setFailed(true));
      }
    }, 15000);

    const onVisible = () => {
      if (!stopped && document.visibilityState === "visible") {
        if (timer !== undefined) window.clearTimeout(timer);
        void pollOnce();
        getHealth().then(setHealth).catch(() => undefined);
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);

    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
      window.clearInterval(healthTimer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, []);

  const connection = failed ? "local_offline" : health ? "connected" : "checking";
  const activeCycle = cycleStatus?.active_run ?? null;
  // E5-R33: the needs-attention list endpoint caps its page size, so the
  // authoritative unresolved total comes from the dashboard summary.
  const unresolvedAttention = dashboard?.applications.needs_attention ?? needsAttention.length;
  const isCycleRunning = cycleStatus?.active_state === "RUNNING";
  const isCancelling = activeCycle?.status === "CANCELLING";
  const isWaitingForAnswer = Boolean(isCycleRunning && activeCycle?.waiting_for_user);

  const agentChip = !health
    ? failed
      ? { label: "BACKEND OFFLINE", tone: "red" as const }
      : { label: "CHECKING…", tone: "gray" as const }
    : isCycleRunning
      ? isCancelling
        ? { label: "STOPPING", tone: "amber" as const }
        : isWaitingForAnswer
          ? { label: "WAITING FOR ANSWER", tone: "amber" as const }
          : { label: "RUNNING", tone: "green" as const }
      : { label: health.agent_state, tone: agentStateTone(health.agent_state) };

  const handleRetry = () => {
    setFailed(false);
    setDashboardError(false);
    setRecentAppsError(false);
    setNeedsAttentionError(false);
    getHealth().then(setHealth).catch(() => setFailed(true));
    void fetchDashboardData();
  };

  const handleRefresh = () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    void fetchDashboardData()
      .then(() => getNotifications(50).then((r) => setNotifications(r.notifications)).catch(() => undefined))
      .finally(() => setIsRefreshing(false));
  };

  const refreshCycleStatus = async () => {
    try {
      const data = await getAutonomousCycleStatus();
      setCycleStatus(data);
      return data;
    } catch {
      return null;
    }
  };

  const handleStartCycle = async () => {
    if (cycleRequestInFlight || startCycleInFlightRef.current) return;
    startCycleInFlightRef.current = true;
    setStartCycleLoading(true);
    setCycleConflict(false);
    try {
      const result = await startAutonomousCycle({});
      setCycleStatus({
        active_state: "RUNNING",
        lock_held: true,
        active_run: {
          status: "RUNNING",
          run_id: result.run_id,
          run_token: result.run_token ?? null,
          started_at: null,
          completed_at: null,
          max_applications: result.max_applications,
          stats: {},
          error: null,
          cancel_requested: false,
        },
        last_run: cycleStatus?.last_run ?? null,
      });
      setShowRunConfirmation(false);
    } catch (error: unknown) {
      const e = error as { status?: number } | null;
      if (e?.status === 409) {
        setCycleConflict(true);
        await refreshCycleStatus();
      }
    } finally {
      startCycleInFlightRef.current = false;
      setStartCycleLoading(false);
    }
  };

  const handleStopCycle = async () => {
    if (cycleRequestInFlight || !isCycleRunning) return;
    setStopCycleLoading(true);
    try {
      const runToken = cycleStatus?.active_run?.run_token ?? undefined;
      await stopAutonomousCycle({ run_token: runToken ?? null });
      await refreshCycleStatus();
    } catch {
      await refreshCycleStatus();
    } finally {
      setStopCycleLoading(false);
    }
  };

  const handleAnswered = async (notice: string) => {
    setAnswerNotice(notice);
    window.setTimeout(() => {
      setAnswerNotice((current) => (current === notice ? null : current));
    }, 8000);
    await refreshCycleStatus();
  };

  const navigate = (page: PageId, options?: NavigateOptions) => {
    const openedOverview = page === "overview" && page !== currentPage;
    setCurrentPage(page);
    setNavSeq((seq) => seq + 1);
    setNavQuery(options?.query ?? null);
    if (options && "statusFilter" in options) {
      setApplicationsFilter(options.statusFilter ?? null);
    } else if (page === "applications") {
      setApplicationsFilter(null);
    }
    setSidebarOpen(false);
    if (openedOverview) {
      void getAutonomousCycleStatus()
        .then((data) => {
          setCycleStatus(data);
          setCycleConflict(false);
        })
        .catch(() => undefined);
    }
  };

  const shellValue = { navigate, waitingForAnswer: isWaitingForAnswer };
  const pageMeta = PAGE_META[currentPage];

  return (
    <ShellContext.Provider value={shellValue}>
      <main className="app-shell">
        <a href="#main-content" className="skip-to-content">Skip to main content</a>

        <header className="mobile-header">
          <button
            className="mobile-menu-button"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label={sidebarOpen ? "Close navigation menu" : "Open navigation menu"}
          >
            {sidebarOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
          <div className="mobile-header-brand">
            <span className="brand-mark">N</span>
            <span>Naukri Agent</span>
          </div>
          <button
            className="icon-button"
            aria-label="Notifications"
            onClick={() => navigate("notifications")}
          >
            <Bell size={18} />
          </button>
        </header>

        {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} role="presentation" />}

        <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
          <div className="brand">
            <span className="brand-mark">N</span>
            <span className="brand-name">Naukri Agent</span>
          </div>
          <nav aria-label="Primary navigation">
            {NAV_GROUPS.map((group) => (
              <div key={group.label} className="nav-group">
                <p className="nav-group-label">{group.label}</p>
                {group.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`nav-item${currentPage === item.id ? " active" : ""}`}
                    onClick={() => navigate(item.id)}
                    aria-current={currentPage === item.id ? "page" : undefined}
                    title={item.label}
                  >
                    <item.icon size={17} strokeWidth={2} />
                    <span>{item.label}</span>
                    {item.id === "attention" && unresolvedAttention > 0 && (
                      <span className="nav-count">{unresolvedAttention}</span>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <span className={`agent-chip tone-${agentChip.tone}`}>
              <span className={`pulse-dot tone-${agentChip.tone}`} aria-hidden />
              {agentChip.label}
            </span>
            {health && <span className="sidebar-version">{health.service} v{health.version}</span>}
          </div>
        </aside>

        <div className="main-column">
          <header className="topbar">
            <div className="topbar-context">
              <span className="topbar-group">{pageMeta.group}</span>
              <span className="topbar-sep">/</span>
              <span className="topbar-page">{pageMeta.label}</span>
            </div>
            <div className="topbar-actions">
              <span className={`agent-chip tone-${agentChip.tone}`} title="Authoritative backend agent/run state">
                <span className={`pulse-dot tone-${agentChip.tone}`} aria-hidden />
                {agentChip.label}
              </span>
              <span
                className={`conn-chip ${connection}`}
                title={
                  connection === "connected"
                    ? "Backend reachable"
                    : connection === "checking"
                      ? "Checking backend…"
                      : "Backend not reachable"
                }
              >
                <span className="conn-dot" aria-hidden />
                {connection === "connected" ? "Connected" : connection === "checking" ? "Checking" : "Offline"}
              </span>
              {connection !== "connected" && (
                <button type="button" className="btn btn-secondary btn-sm" onClick={handleRetry}>
                  Retry
                </button>
              )}
              <button
                type="button"
                className="icon-button"
                onClick={handleRefresh}
                disabled={isRefreshing}
                aria-label="Refresh data"
                title="Refresh dashboard data"
              >
                <RefreshCw size={16} className={isRefreshing ? "spin" : ""} />
              </button>
              <button
                type="button"
                className="icon-button"
                aria-label="Notifications"
                onClick={() => navigate("notifications")}
              >
                <Bell size={16} />
              </button>
            </div>
          </header>

          <div className="content-area" id="main-content" tabIndex={-1}>
            {currentPage === "overview" && (
              <OverviewPage
                key={`overview-${navSeq}`}
                health={health}
                dashboard={dashboard}
                dashboardLoading={dashboardLoading}
                dashboardError={dashboardError}
                recentApps={recentApps}
                recentAppsLoading={recentAppsLoading}
                recentAppsError={recentAppsError}
                needsAttention={needsAttention}
                needsAttentionLoading={needsAttentionLoading}
                needsAttentionError={needsAttentionError}
                notifications={notifications}
                cycleStatus={cycleStatus}
                cycleConflict={cycleConflict}
                startCycleLoading={startCycleLoading}
                stopCycleLoading={stopCycleLoading}
                cycleRequestInFlight={cycleRequestInFlight}
                answerNotice={answerNotice}
                isRefreshing={isRefreshing}
                onConfirmRunCycle={() => {
                  if (cycleRequestInFlight || isCycleRunning) return;
                  setShowRunConfirmation(true);
                }}
                onStopCycle={() => void handleStopCycle()}
                onRefreshCycle={() => void refreshCycleStatus()}
                onAnswered={(notice) => void handleAnswered(notice)}
                onRefresh={handleRefresh}
                onRetry={handleRetry}
              />
            )}
            {currentPage === "jobs" && <JobsPage key={`jobs-${navSeq}`} initialQuery={navQuery ?? undefined} />}
            {currentPage === "apply" && <ApplyQueuePage key={`apply-${navSeq}`} initialQuery={navQuery ?? undefined} />}
            {currentPage === "applications" && (
              <ApplicationsPage
                key={`applications-${navSeq}`}
                statusFilter={applicationsFilter}
                onStatusFilterChange={setApplicationsFilter}
              />
            )}
            {currentPage === "attention" && (
              <NeedsAttentionPage
                key={`attention-${navSeq}`}
                unresolvedTotal={dashboard?.applications.needs_attention ?? null}
              />
            )}
            {currentPage === "ai-queue" && <AIQueuePage key={`ai-${navSeq}`} />}
            {currentPage === "notifications" && <NotificationsPage key={`notifications-${navSeq}`} />}
            {currentPage === "analytics" && <AnalyticsPage key={`analytics-${navSeq}`} />}
            {currentPage === "activity" && <ActivityPage key={`activity-${navSeq}`} />}
            {currentPage === "profile" && (
              <ProfilePage key={`profile-${navSeq}`} onProfileChange={setProfile} />
            )}
            {currentPage === "preferences" && <PreferencesPage key={`preferences-${navSeq}`} />}
          </div>
        </div>

        <nav className="bottom-navigation" aria-label="Mobile navigation">
          {(
            [
              { id: "overview" as PageId, label: "Home", icon: LayoutDashboard },
              { id: "jobs" as PageId, label: "Jobs", icon: BriefcaseBusiness },
              { id: "apply" as PageId, label: "Apply", icon: ListChecks },
              { id: "applications" as PageId, label: "Apps", icon: ChartNoAxesColumn },
            ]
          ).map((item) => (
            <button
              key={item.id}
              type="button"
              className={`bottom-nav-item${currentPage === item.id ? " active" : ""}`}
              onClick={() => navigate(item.id)}
              aria-label={item.label}
            >
              <item.icon size={19} />
              <span>{item.label}</span>
            </button>
          ))}
          <button
            type="button"
            className={`bottom-nav-item${["analytics", "activity", "notifications", "profile", "preferences", "attention", "ai-queue"].includes(currentPage) ? " active" : ""}`}
            onClick={() => setSidebarOpen(true)}
            aria-label="More sections"
          >
            <Menu size={19} />
            <span>More</span>
          </button>
        </nav>

        {showRunConfirmation && (
          <div className="modal-overlay" onClick={() => setShowRunConfirmation(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Run autonomous cycle">
              <div className="modal-header">
                <h2>Run autonomous cycle</h2>
                <button type="button" onClick={() => setShowRunConfirmation(false)} className="icon-button" aria-label="Close">
                  <X size={18} />
                </button>
              </div>
              <div className="modal-body">
                <p>This will run the autonomous job application cycle, which may:</p>
                <ul>
                  <li>Discover jobs from Naukri</li>
                  <li>Apply deterministic hard filters</li>
                  <li>Evaluate candidates with the configured AI provider</li>
                  <li><strong>Submit real Naukri applications</strong> to every eligible matching job</li>
                </ul>
                <p>All existing safety rules will be enforced:</p>
                <ul>
                  <li>Duplicate protection</li>
                  <li>External application boundary</li>
                  <li>Post-click evidence verification</li>
                  <li>CAPTCHA/security challenge handling</li>
                  <li>Truthful APPLIED confirmation only</li>
                </ul>
                <p className="warning-text">
                  The run continues until every eligible matching job is processed or a genuine blocker stops it. There is no hourly or daily application-count cap.
                </p>
                <p className="warning-text">Only one autonomous cycle can run at a time.</p>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowRunConfirmation(false)}>
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void handleStartCycle()}
                  disabled={startCycleLoading}
                  className="btn btn-primary"
                >
                  {startCycleLoading ? "Starting…" : "Run cycle"}
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </ShellContext.Provider>
  );
}
