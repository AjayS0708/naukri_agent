import { useEffect, useRef, useState } from "react";
import { Activity, Bot, BriefcaseBusiness, ChartNoAxesColumn, CircleAlert, Settings, Sparkles, BarChart3, LayoutDashboard, User, Bell, Menu, X, MoreHorizontal, RefreshCw, Play, AlertTriangle, Square } from "lucide-react";
import { getDashboardSummary, getHealth, getNeedsAttention, getNotifications, getRecentApplications, startAutonomousCycle, getAutonomousCycleStatus, stopAutonomousCycle, getPendingQuestion, answerPendingQuestion } from "../services/api";
import type { AnswerQuestionRequest, DashboardSummary, HealthResponse, NeedsAttentionItem, Notification, PendingQuestion, ProfileResponse, RecentApplicationItem, AutonomousCycleStatusResponse } from "../types/api";
import { ProfileWorkspace } from "../components/ProfileWorkspace";
import { AIStatus } from "../components/AIStatus";
import { JobPreferences } from "../components/JobPreferences";
import { AgentControl } from "../components/AgentControl";
import { AnalyticsDashboard } from "../components/AnalyticsDashboard";
import { BackendState } from "../components/BackendState";
import { ApplicationsList } from "../components/ApplicationsList";
import { JobsList } from "../components/JobsList";

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
  const [currentPage, setCurrentPage] = useState<"overview" | "profile" | "preferences" | "analytics" | "activity" | "applications" | "jobs">("overview");
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

  // Autonomous cycle state (E3)
  const [cycleStatus, setCycleStatus] = useState<AutonomousCycleStatusResponse | null>(null);
  const [cycleLoading, setCycleLoading] = useState(false);
  const [showRunConfirmation, setShowRunConfirmation] = useState(false);
  const [startCycleLoading, setStartCycleLoading] = useState(false);
  const [stopCycleLoading, setStopCycleLoading] = useState(false);
  const [cycleConflict, setCycleConflict] = useState(false);
  const cycleRequestInFlight = startCycleLoading || stopCycleLoading;
  // E5-R22: synchronous double-submit guard — React state (startCycleLoading)
  // can lag behind rapid clicks, so a ref blocks re-entry before re-render.
  const startCycleInFlightRef = useRef(false);

  // E5-R21: human-in-the-loop screening answer state
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [rememberAnswer, setRememberAnswer] = useState(true);
  const [rememberAllJobs, setRememberAllJobs] = useState(false);
  const [answerSubmitting, setAnswerSubmitting] = useState(false);
  const [answerError, setAnswerError] = useState<string | null>(null);

  const syncPendingQuestion = (status: AutonomousCycleStatusResponse) => {
    if (status.active_run?.waiting_for_user) {
      getPendingQuestion()
        .then(setPendingQuestion)
        .catch(() => setPendingQuestion(null));
    } else {
      setPendingQuestion(null);
    }
  };

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

    // Needs attention items
    setNeedsAttentionLoading(true);
    getNeedsAttention(10)
      .then((data) => { setNeedsAttention(data.applications); setNeedsAttentionError(false); })
      .catch(() => setNeedsAttentionError(true))
      .finally(() => setNeedsAttentionLoading(false));

    // Autonomous cycle status (E3)
    setCycleLoading(true);
    getAutonomousCycleStatus()
      .then((data) => { setCycleStatus(data); setCycleConflict(false); syncPendingQuestion(data); })
      .catch(() => setCycleStatus(null))
      .finally(() => setCycleLoading(false));
  }, []);

  // Poll autonomous cycle status while running (E3)
  useEffect(() => {
    if (!cycleStatus || cycleStatus.active_state !== "RUNNING") {
      return;
    }

    const pollInterval = setInterval(() => {
      getAutonomousCycleStatus()
        .then((data) => {
          setCycleStatus(data);
          setCycleConflict(false);
          syncPendingQuestion(data);
          // Stop polling when completed or failed and refresh dashboard
          if (data.active_state === "IDLE") {
            clearInterval(pollInterval);
            // Refresh dashboard data after completion
            setDashboardLoading(true);
            setRecentAppsLoading(true);
            setNeedsAttentionLoading(true);
            Promise.all([
              getDashboardSummary().then((d) => { setDashboard(d); setDashboardError(false); }).catch(() => setDashboardError(true)),
              getRecentApplications(10).then((d) => { setRecentApps(d.applications); setRecentAppsError(false); }).catch(() => setRecentAppsError(true)),
              getNeedsAttention(10).then((d) => { setNeedsAttention(d.applications); setNeedsAttentionError(false); }).catch(() => setNeedsAttentionError(true)),
            ]).finally(() => {
              setDashboardLoading(false);
              setRecentAppsLoading(false);
              setNeedsAttentionLoading(false);
            });
          }
        })
        .catch(() => {
          // Backend error - stop polling
          clearInterval(pollInterval);
        });
    }, 4000); // Poll every 4 seconds

    return () => clearInterval(pollInterval);
  }, [cycleStatus?.active_state]);

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
    setNeedsAttentionError(false);

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

    setNeedsAttentionLoading(true);
    getNeedsAttention(10)
      .then((data) => { setNeedsAttention(data.applications); setNeedsAttentionError(false); })
      .catch(() => setNeedsAttentionError(true))
      .finally(() => setNeedsAttentionLoading(false));
  };

  const handleRefresh = () => {
    if (isRefreshing) return;
    setIsRefreshing(true);

    Promise.all([
      getDashboardSummary().then((data) => { setDashboard(data); setDashboardError(false); }).catch(() => setDashboardError(true)),
      getRecentApplications(10).then((data) => { setRecentApps(data.applications); setRecentAppsError(false); }).catch(() => setRecentAppsError(true)),
      getNeedsAttention(10).then((data) => { setNeedsAttention(data.applications); setNeedsAttentionError(false); }).catch(() => setNeedsAttentionError(true)),
    ]).finally(() => setIsRefreshing(false));
  };

  // Autonomous cycle handlers (E3 / E5-R15)
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
    } catch (error: any) {
      if (error?.status === 409) {
        setCycleConflict(true);
        // Refresh status to get current run info
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
      // Best-effort: still refresh so the UI reflects backend state.
      await refreshCycleStatus();
    } finally {
      setStopCycleLoading(false);
    }
  };

  const handleConfirmRunCycle = () => {
    if (cycleRequestInFlight || isCycleRunning) return;
    setShowRunConfirmation(true);
  };

  // E5-R21: answer or skip the run's pending screening question
  const handleAnswerQuestion = async (skip: boolean) => {
    if (!pendingQuestion?.pending_question_id || answerSubmitting) return;
    if (!skip && !answerText.trim()) {
      setAnswerError("Enter an answer, or skip this job.");
      return;
    }
    setAnswerSubmitting(true);
    setAnswerError(null);
    try {
      const request: AnswerQuestionRequest = skip
        ? { pending_question_id: pendingQuestion.pending_question_id, skip: true }
        : {
            pending_question_id: pendingQuestion.pending_question_id,
            answer: answerText.trim(),
            remember: rememberAnswer,
            scope: rememberAllJobs ? "GLOBAL" : "JOB",
            allow_global_reuse: rememberAnswer && rememberAllJobs,
          };
      await answerPendingQuestion(request);
      setPendingQuestion(null);
      setAnswerText("");
      setRememberAllJobs(false);
      await refreshCycleStatus();
    } catch (error: any) {
      setAnswerError(error?.message ?? "The answer could not be submitted. Please try again.");
    } finally {
      setAnswerSubmitting(false);
    }
  };

  const handleCancelRunCycle = () => {
    setShowRunConfirmation(false);
  };

  const handleNavClick = (page: typeof currentPage) => {
    setCurrentPage(page);
    setApplicationsFilter(null);
    setSidebarOpen(false);
  };

  const handleViewApplications = (filter: string | null = null) => {
    setApplicationsFilter(filter);
    setCurrentPage("applications");
  };

  const handleViewJobs = () => {
    setCurrentPage("jobs");
  };

  const closeSidebar = () => setSidebarOpen(false);
  const activeCycle = cycleStatus?.active_run ?? null;
  const lastCycle = cycleStatus?.last_run ?? null;
  const isCycleRunning = cycleStatus?.active_state === "RUNNING";
  // E5-R16: the run halted because the Naukri session is not authenticated.
  const cycleLoginRequired = lastCycle?.status === "LOGIN_REQUIRED";
  // E5-R21: the run is blocked on a screening question awaiting an answer.
  const isWaitingForAnswer = Boolean(isCycleRunning && activeCycle?.waiting_for_user);
  const cycleProgress = activeCycle?.progress ?? null;

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
        <a className={`nav-item ${currentPage === "jobs" ? "active" : ""}`} href="#jobs" onClick={(e) => { e.preventDefault(); handleNavClick("jobs"); }}><BriefcaseBusiness size={18} />Jobs</a>
        <a className={`nav-item ${currentPage === "applications" ? "active" : ""}`} href="#applications" onClick={(e) => { e.preventDefault(); handleNavClick("applications"); }}><ChartNoAxesColumn size={18} />Applications</a>
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
          <h1>{currentPage === "overview" ? "Agent Overview" : currentPage === "profile" ? "Profile" : currentPage === "preferences" ? "Preferences" : currentPage === "analytics" ? "Analytics" : currentPage === "applications" ? "Applications" : currentPage === "jobs" ? "Jobs" : "Activity"}</h1>
          <p className="page-description">{currentPage === "overview" ? "Monitor and control your job search automation" : currentPage === "profile" ? "Manage your resume and professional profile" : currentPage === "preferences" ? "Configure job search preferences and automation settings" : currentPage === "analytics" ? "View performance metrics and decision analytics" : currentPage === "applications" ? "View and filter application history" : currentPage === "jobs" ? "View discovered jobs" : "Track agent activity and events"}</p>
        </div>
        <div className="topbar-actions">
          <button
            className="icon-button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            aria-label="Refresh dashboard"
            title="Refresh dashboard data"
          >
            <RefreshCw size={20} className={isRefreshing ? "animate-spin" : ""} />
          </button>
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

            {/* Autonomous Cycle Control (E3 / E5-R15 / E5-R16) */}
            <section className="status-panel">
              <div>
                <p className="eyebrow">AUTONOMOUS CYCLE</p>
                <strong className={`agent-state ${(isCycleRunning ? (cycleStatus?.active_run?.status === "CANCELLING" ? "PAUSED" : isWaitingForAnswer ? "PAUSED" : "RUNNING") : cycleLoginRequired ? "AUTH_REQUIRED" : "IDLE").toLowerCase()}`}>
                  {isCycleRunning ? (cycleStatus?.active_run?.status === "CANCELLING" ? "Stopping…" : isWaitingForAnswer ? "Waiting for your answer" : "Running") : cycleLoginRequired ? "Login required" : "Idle"}
                </strong>
                {isCycleRunning && !isWaitingForAnswer && cycleStatus?.active_run?.status !== "CANCELLING" && <p>Discovery and application in progress...</p>}
                {isCycleRunning && isWaitingForAnswer && (
                  <p>The run is paused on a screening question. Answer below to resume, skip this job, or stop the run entirely.</p>
                )}
                {isCycleRunning && cycleStatus?.active_run?.status === "CANCELLING" && <p>Cancellation requested. Finishing the current safe step...</p>}
                {!isCycleRunning && cycleLoginRequired && (
                  <p className="warning-text">
                    Naukri session is signed out. Applications were not started. Sign in manually in the agent
                    browser, then run the cycle again.
                  </p>
                )}
                {!isCycleRunning && lastCycle?.status === "COMPLETED" && <p>Last cycle completed successfully.</p>}
                {!isCycleRunning && lastCycle?.status === "CANCELLED" && <p>Last cycle was cancelled.</p>}
                {!isCycleRunning && lastCycle?.status === "FAILED" && <p className="error-text">Last cycle failed. Check logs for details.</p>}
                {cycleConflict && <p className="error-text">An autonomous cycle is already running.</p>}
              </div>
              <div className="control-buttons">
                {!isCycleRunning && !cycleConflict && (
                  <button
                    onClick={handleConfirmRunCycle}
                    disabled={cycleRequestInFlight || isCycleRunning}
                    className="btn btn-primary"
                  >
                    <Play size={16} />
                    {startCycleLoading ? "Starting..." : "Run Autonomous Cycle"}
                  </button>
                )}
                {isCycleRunning && (
                  <button
                    onClick={handleStopCycle}
                    disabled={cycleRequestInFlight || cycleStatus?.active_run?.status === "CANCELLING"}
                    className="btn btn-danger"
                    aria-label="Stop autonomous cycle"
                  >
                    <Square size={16} />
                    {stopCycleLoading || cycleStatus?.active_run?.status === "CANCELLING" ? "Stopping..." : "Stop"}
                  </button>
                )}
                {cycleConflict && (
                  <button
                    onClick={() => refreshCycleStatus()}
                    className="btn btn-secondary"
                  >
                    Refresh Status
                  </button>
                )}
              </div>
              {(activeCycle?.run_id ?? lastCycle?.run_id) && (
                <div className="status-meta">
                  <span>Run ID</span>
                  <b>#{activeCycle?.run_id ?? lastCycle?.run_id}</b>
                </div>
              )}
              {/* Completion stats */}
              {!isCycleRunning && lastCycle?.status === "COMPLETED" && Object.keys(lastCycle.stats).length > 0 && (
                <div className="status-meta">
                  <span>Stats</span>
                  <b>
                    {lastCycle.stats.applied !== undefined ? `${lastCycle.stats.applied} applied` : "Not available"}
                    {lastCycle.stats.needs_attention !== undefined && `, ${lastCycle.stats.needs_attention} needs attention`}
                    {lastCycle.stats.external !== undefined && `, ${lastCycle.stats.external} external`}
                  </b>
                </div>
              )}
              {/* E5-R21: live multi-job progress while the run is active */}
              {isCycleRunning && cycleProgress && (
                <div className="status-meta">
                  <span>Progress</span>
                  <b>
                    {`${cycleProgress.processed ?? 0} / ${cycleProgress.candidates_total ?? "?"} processed`}
                    {typeof cycleProgress.applied === "number" ? ` · ${cycleProgress.applied} applied` : ""}
                    {typeof cycleProgress.skipped === "number" && cycleProgress.skipped > 0 ? ` · ${cycleProgress.skipped} skipped` : ""}
                    {typeof cycleProgress.needs_attention === "number" && cycleProgress.needs_attention > 0 ? ` · ${cycleProgress.needs_attention} needs attention` : ""}
                    {typeof cycleProgress.remaining === "number" ? ` · ${cycleProgress.remaining} remaining` : ""}
                    {cycleProgress.current_job_title ? ` · current: ${cycleProgress.current_job_title}` : ""}
                    {cycleProgress.current_step && !isWaitingForAnswer ? ` (${cycleProgress.current_step.replaceAll("_", " ")})` : ""}
                  </b>
                </div>
              )}
              {/* E5-R21: pending screening question — answer, skip, or stop */}
              {isWaitingForAnswer && pendingQuestion?.found && pendingQuestion.question_text && (
                <div
                  role="alert"
                  aria-live="assertive"
                  style={{ marginTop: "0.75rem", padding: "0.75rem", border: "1px solid var(--color-warning)", borderRadius: "8px", display: "grid", gap: "0.5rem" }}
                >
                  <p className="eyebrow" style={{ margin: 0 }}>
                    ANSWER NEEDED{pendingQuestion.job_title ? ` — ${pendingQuestion.job_title}` : ""}
                    {pendingQuestion.employer ? ` · ${pendingQuestion.employer}` : ""}
                  </p>
                  <p style={{ margin: 0 }}><strong>{pendingQuestion.question_text}</strong></p>
                  {pendingQuestion.options && pendingQuestion.options.length > 0 ? (
                    <select
                      value={answerText}
                      onChange={(e) => setAnswerText(e.target.value)}
                      aria-label="Choose an answer"
                    >
                      <option value="">Select an answer…</option>
                      {pendingQuestion.options.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={answerText}
                      onChange={(e) => setAnswerText(e.target.value)}
                      placeholder="Type your answer"
                      aria-label="Your answer"
                    />
                  )}
                  <label style={{ display: "flex", gap: "0.4rem", alignItems: "center", fontSize: "0.85rem" }}>
                    <input
                      type="checkbox"
                      checked={rememberAnswer}
                      onChange={(e) => setRememberAnswer(e.target.checked)}
                    />
                    Save this answer for future applications
                  </label>
                  <label style={{ display: "flex", gap: "0.4rem", alignItems: "center", fontSize: "0.85rem" }}>
                    <input
                      type="checkbox"
                      checked={rememberAllJobs}
                      disabled={!rememberAnswer}
                      onChange={(e) => setRememberAllJobs(e.target.checked)}
                    />
                    Reuse it for all jobs (salary, notice, relocation, …)
                  </label>
                  {answerError && <p className="error-text" style={{ margin: 0 }}>{answerError}</p>}
                  <div className="control-buttons" style={{ marginTop: "0.25rem" }}>
                    <button
                      className="btn btn-primary"
                      onClick={() => handleAnswerQuestion(false)}
                      disabled={answerSubmitting || !answerText.trim()}
                    >
                      {answerSubmitting ? "Submitting…" : "Answer & resume"}
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleAnswerQuestion(true)}
                      disabled={answerSubmitting}
                    >
                      Skip this job
                    </button>
                  </div>
                </div>
              )}
            </section>

            {/* Run Confirmation Modal (E3) */}
            {showRunConfirmation && (
              <div className="modal-overlay" onClick={handleCancelRunCycle}>
                <div className="modal" onClick={(e) => e.stopPropagation()}>
                  <div className="modal-header">
                    <h2>Run Autonomous Cycle</h2>
                    <button onClick={handleCancelRunCycle} className="icon-button"><X size={20} /></button>
                  </div>
                  <div className="modal-body">
                    <p>This will run the autonomous job application cycle, which may:</p>
                    <ul>
                      <li>Discover jobs from Naukri</li>
                      <li>Apply deterministic hard filters</li>
                      <li>Evaluate candidates with Gemini AI</li>
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
                    <p className="warning-text" style={{ marginTop: "0" }}>
                      The run continues until every eligible matching job is processed or a genuine blocker stops it. There is no hourly or daily application-count cap.
                    </p>
                    <p className="warning-text">Only one autonomous cycle can run at a time.</p>
                  </div>
                  <div className="modal-footer">
                    <button onClick={handleCancelRunCycle} className="btn btn-secondary">Cancel</button>
                    <button
                      onClick={handleStartCycle}
                      disabled={startCycleLoading}
                      className="btn btn-primary"
                    >
                      {startCycleLoading ? "Starting..." : "Run Cycle"}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Metrics — real data from /api/dashboard/summary */}
            <section className="metrics">
              <article className="metric clickable" onClick={() => handleViewApplications("APPLIED")} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleViewApplications("APPLIED"); }}>
                <BriefcaseBusiness size={20} />
                <p>Applications total</p>
                <strong aria-live="polite">
                  {dashboardLoading ? "…" : dashboardError ? "—" : dashboard!.applications.applied}
                </strong>
              </article>
              <article className="metric clickable" onClick={handleViewJobs} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleViewJobs(); }}>
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
              <article className="metric clickable" onClick={() => handleViewApplications("NEEDS_ATTENTION")} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleViewApplications("NEEDS_ATTENTION"); }}>
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

            {/* Latest autonomous run — real data from dashboard summary */}
            <section className="status-panel">
              <div>
                <p className="eyebrow">LATEST RUN</p>
                <strong>{dashboardLoading ? "…" : dashboardError ? "Unavailable" : dashboard!.discovery.status ?? "No runs yet"}</strong>
                <p>
                  {dashboardLoading ? "Loading…" : dashboardError ? "Run data unavailable" : dashboard!.discovery.run_id
                    ? `Run #${dashboard!.discovery.run_id} — ${dashboard!.discovery.jobs_discovered} jobs discovered, ${dashboard!.discovery.new_jobs} new jobs`
                    : "No discovery runs recorded yet."}
                </p>
              </div>
              {dashboard && dashboard.discovery.completed_at && (
                <div className="status-meta">
                  <span>Completed</span>
                  <b>{fmtDate(dashboard.discovery.completed_at)}</b>
                </div>
              )}
            </section>

            {/* Needs attention section */}
            <section className="activity" aria-labelledby="needs-attention-heading">
              <div>
                <p className="eyebrow">NEEDS ATTENTION</p>
                <h2 id="needs-attention-heading">Items requiring review</h2>
              </div>
              {needsAttentionLoading ? (
                <p className="text-[var(--color-text-secondary)]">Loading needs-attention items…</p>
              ) : needsAttentionError ? (
                <p className="error-text">Needs-attention data unavailable. Please retry.</p>
              ) : needsAttention.length === 0 ? (
                <p>No items need attention at this time.</p>
              ) : (
                <ul>
                  {needsAttention.map((item) => (
                    <li key={item.application_id}>
                      <strong>{item.job_title}</strong> at {item.company}
                      {" — "}
                      <span style={{ color: "var(--color-warning)" }}>{fmtStatus(item.status)}</span>
                      {item.skip_reason && <span className="text-[var(--color-text-secondary)]"> · {item.skip_reason}</span>}
                      {item.failure_reason && <span className="text-[var(--color-text-secondary)]"> · {item.failure_reason}</span>}
                    </li>
                  ))}
                </ul>
              )}
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

            <section id="analytics-dashboard"><AnalyticsDashboard onOutcomeClick={handleViewApplications} /></section>
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

        {currentPage === "applications" && (
          <ApplicationsList statusFilter={applicationsFilter} onBack={() => handleNavClick("overview")} />
        )}

        {currentPage === "jobs" && (
          <JobsList onBack={() => handleNavClick("overview")} />
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
      <button
        className={`bottom-nav-item ${currentPage === "jobs" ? "active" : ""}`}
        onClick={() => handleNavClick("jobs")}
        aria-label="Jobs"
      >
        <BriefcaseBusiness size={20} />
        <span>Jobs</span>
      </button>
      <button
        className={`bottom-nav-item ${currentPage === "applications" ? "active" : ""}`}
        onClick={() => handleNavClick("applications")}
        aria-label="Applications"
      >
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
