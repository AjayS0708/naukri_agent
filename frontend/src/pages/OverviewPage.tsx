import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BriefcaseBusiness,
  CircleAlert,
  ListChecks,
  Play,
  RefreshCw,
  Sparkles,
  Square,
  UserCheck,
  XCircle,
} from "lucide-react";
import { getAIQueueStatus, getManualEligible } from "../services/api";
import type {
  AIQueueCounts,
  AutonomousCycleStatusResponse,
  DashboardSummary,
  HealthResponse,
  NeedsAttentionItem,
  Notification,
  RecentApplicationItem,
} from "../types/api";
import { AgentControl } from "../components/AgentControl";
import { ScreeningQuestionPanel } from "../components/ScreeningQuestionPanel";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { useShell } from "../app/shell";
import { PageHeader } from "../ui/PageHeader";
import { ProgressPanel } from "../ui/ProgressPanel";
import { StatCard } from "../ui/StatCard";
import { StatusBadge } from "../ui/StatusBadge";
import { asNumber, fmtDateTime, statusLabel } from "../ui/status";

interface OverviewPageProps {
  health: HealthResponse | null;
  dashboard: DashboardSummary | null;
  dashboardLoading: boolean;
  dashboardError: boolean;
  recentApps: RecentApplicationItem[];
  recentAppsLoading: boolean;
  recentAppsError: boolean;
  needsAttention: NeedsAttentionItem[];
  needsAttentionLoading: boolean;
  needsAttentionError: boolean;
  notifications: Notification[];
  cycleStatus: AutonomousCycleStatusResponse | null;
  cycleConflict: boolean;
  startCycleLoading: boolean;
  stopCycleLoading: boolean;
  cycleRequestInFlight: boolean;
  answerNotice: string | null;
  isRefreshing: boolean;
  onConfirmRunCycle: () => void;
  onStopCycle: () => void;
  onRefreshCycle: () => void;
  onAnswered: (notice: string) => void;
  onRefresh: () => void;
  onRetry: () => void;
}

const STALL_THRESHOLD_MS = 5 * 60 * 1000;

export function OverviewPage(props: OverviewPageProps) {
  const { navigate } = useShell();
  const {
    health,
    dashboard,
    dashboardLoading,
    dashboardError,
    recentApps,
    recentAppsLoading,
    recentAppsError,
    needsAttention,
    needsAttentionLoading,
    needsAttentionError,
    notifications,
    cycleStatus,
    cycleConflict,
    startCycleLoading,
    stopCycleLoading,
    cycleRequestInFlight,
    answerNotice,
    isRefreshing,
    onConfirmRunCycle,
    onStopCycle,
    onRefreshCycle,
    onAnswered,
    onRefresh,
    onRetry,
  } = props;

  const [eligibleCount, setEligibleCount] = useState<number | null>(null);
  const [aiCounts, setAiCounts] = useState<AIQueueCounts | null>(null);

  const loadAux = async () => {
    try {
      const [eligible, queue] = await Promise.all([getManualEligible(1, 0, false, ""), getAIQueueStatus()]);
      setEligibleCount(eligible.eligible_count);
      setAiCounts(queue);
    } catch {
      // Auxiliary cards render "—" until the next successful refresh.
    }
  };

  useEffect(() => {
    void loadAux();
  }, []);

  const activeCycle = cycleStatus?.active_run ?? null;
  const lastCycle = cycleStatus?.last_run ?? null;
  // Dashboard summary counts unresolved attempts; the list endpoint is
  // page-limited, so the summary is the authoritative open-item total.
  const unresolvedAttention = dashboard?.applications.needs_attention ?? needsAttention.length;
  const isCycleRunning = cycleStatus?.active_state === "RUNNING";
  const cycleLoginRequired = lastCycle?.status === "LOGIN_REQUIRED";
  const isWaitingForAnswer = Boolean(isCycleRunning && activeCycle?.waiting_for_user);
  const cancelling = activeCycle?.status === "CANCELLING";
  const progress = activeCycle?.progress ?? null;

  const progressUpdatedAt = progress?.progress_updated_at ?? null;
  const possiblyStalled =
    isCycleRunning &&
    !isWaitingForAnswer &&
    !cancelling &&
    Boolean(progressUpdatedAt) &&
    (() => {
      const t = new Date(progressUpdatedAt as string).getTime();
      return !Number.isNaN(t) && Date.now() - t > STALL_THRESHOLD_MS;
    })();

  const discoveryMode = Boolean(progress && ((progress.search_total ?? 0) > 0 || progress.phase === "DISCOVERY"));

  const runStats = (() => {
    if (!progress) return [];
    const stats: Array<{ label: string; value: ReactNode }> = [];
    if (discoveryMode) {
      stats.push({
        label: "Discovery",
        value: `${progress.search_index ?? 0} / ${progress.search_total ?? "?"} searches`,
      });
      if (typeof progress.jobs_new === "number") stats.push({ label: "New jobs", value: progress.jobs_new });
      if (typeof progress.jobs_duplicate === "number") stats.push({ label: "Duplicates", value: progress.jobs_duplicate });
      if (progress.current_search) stats.push({ label: "Current search", value: progress.current_search });
    } else {
      stats.push({
        label: "Processed",
        value: `${asNumber(progress.processed) ?? 0} / ${asNumber(progress.candidates_total) ?? "?"}`,
      });
      if (asNumber(progress.applied) !== null) stats.push({ label: "Applied", value: asNumber(progress.applied) });
      if (asNumber(progress.skipped) !== null && progress.skipped! > 0) stats.push({ label: "Skipped", value: asNumber(progress.skipped) });
      if (asNumber(progress.external) !== null && progress.external! > 0) stats.push({ label: "External", value: asNumber(progress.external) });
      if (asNumber(progress.needs_attention) !== null && progress.needs_attention! > 0)
        stats.push({ label: "Needs attention", value: asNumber(progress.needs_attention) });
      if (asNumber(progress.failed) !== null && progress.failed! > 0) stats.push({ label: "Failed", value: asNumber(progress.failed) });
      if (typeof progress.current_job_title === "string" && progress.current_job_title)
        stats.push({ label: "Current job", value: progress.current_job_title });
      if (progress.current_step && !isWaitingForAnswer)
        stats.push({ label: "Step", value: progress.current_step.replaceAll("_", " ") });
      if (asNumber(progress.remaining) !== null) stats.push({ label: "Remaining", value: asNumber(progress.remaining) });
    }
    if (progressUpdatedAt) {
      const parsed = new Date(progressUpdatedAt);
      if (!Number.isNaN(parsed.getTime()))
        stats.push({ label: "Last update", value: parsed.toLocaleTimeString() });
    }
    return stats;
  })();

  return (
    <div className="page">
      <PageHeader
        eyebrow="Dashboard"
        title="Overview"
        description="Operational command center: live run state, queue health, and everything waiting on you."
        actions={
          <button type="button" className="btn btn-secondary" onClick={onRefresh} disabled={isRefreshing}>
            <RefreshCw size={15} className={isRefreshing ? "spin" : ""} />
            Refresh
          </button>
        }
      />

      {isCycleRunning && (
        <ProgressPanel
          eyebrow={cancelling ? "Cycle stopping" : isWaitingForAnswer ? "Cycle waiting for answer" : "Cycle running"}
          stateLabel={
            cancelling
              ? "Stopping…"
              : isWaitingForAnswer
                ? "Waiting for your answer"
                : discoveryMode
                  ? "Discovering jobs"
                  : "Applying to jobs"
          }
          stateTone={cancelling || isWaitingForAnswer ? "amber" : "green"}
          description={
            isWaitingForAnswer
              ? "The run is paused on a screening question. Answer below to resume, skip this job, or stop the run."
              : cancelling
                ? "Cancellation requested. Finishing the current safe step…"
                : discoveryMode
                  ? "Searching Naukri for matching jobs."
                  : "Applications are being processed with the standard safety checks."
          }
          stats={runStats}
          actions={
            <button
              type="button"
              className="btn btn-danger"
              onClick={onStopCycle}
              disabled={cycleRequestInFlight || cancelling}
              aria-label="Stop autonomous cycle"
            >
              <Square size={15} />
              {stopCycleLoading || cancelling ? "Stopping…" : "Stop"}
            </button>
          }
          footer={
            possiblyStalled ? (
              <span className="stall-hint">
                <AlertTriangle size={14} />
                No recent progress updates — the run may be stalled. Check the backend logs or stop and retry.
              </span>
            ) : null
          }
        />
      )}

      {isCycleRunning && isWaitingForAnswer && (
        <ScreeningQuestionPanel active onAnswered={onAnswered} heading="Screening question" />
      )}

      {!isCycleRunning && answerNotice && (
        <div className="banner banner-success" role="status" aria-live="polite">
          {answerNotice}
        </div>
      )}

      <div className="stat-grid">
        <StatCard
          icon={BriefcaseBusiness}
          label="Jobs discovered"
          value={dashboardLoading ? "…" : dashboardError ? "—" : dashboard?.discovery.jobs_discovered ?? 0}
          sub={
            dashboard
              ? dashboard.discovery.run_id
                ? `latest run #${dashboard.discovery.run_id}`
                : "all-time total"
              : undefined
          }
          onClick={() => navigate("jobs")}
        />
        <StatCard
          icon={ListChecks}
          label="Eligible now"
          value={eligibleCount ?? "…"}
          tone="green"
          sub="backend verdict"
          onClick={() => navigate("apply")}
        />
        <StatCard
          icon={UserCheck}
          label="Applications"
          value={dashboardLoading ? "…" : dashboardError ? "—" : dashboard?.applications.applied ?? 0}
          sub="APPLIED + SUBMITTED"
          tone="green"
          onClick={() => navigate("applications", { statusFilter: "APPLIED" })}
        />
        <StatCard
          icon={CircleAlert}
          label="Needs attention"
          value={dashboardLoading ? "…" : dashboardError ? "—" : dashboard?.applications.needs_attention ?? 0}
          tone="amber"
          sub="unresolved"
          onClick={() => navigate("attention")}
        />
        <StatCard
          icon={XCircle}
          label="Skipped"
          value={dashboardLoading ? "…" : dashboardError ? "—" : dashboard?.applications.skipped ?? 0}
          tone="gray"
          onClick={() => navigate("applications", { statusFilter: "SKIPPED" })}
        />
        <StatCard
          icon={Sparkles}
          label="AI queue"
          value={aiCounts ? aiCounts.total_items : "…"}
          tone="violet"
          sub={aiCounts ? `${aiCounts.total_queued} queued · ${aiCounts.total_failed} failed` : "loading"}
          onClick={() => navigate("ai-queue")}
        />
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">Autonomous cycle</p>
              <h2 className="card-title">
                {isCycleRunning
                  ? cancelling
                    ? "Stopping"
                    : isWaitingForAnswer
                      ? "Waiting for answer"
                      : "Running"
                  : cycleLoginRequired
                    ? "Login required"
                    : cycleConflict
                      ? "Conflict"
                      : lastCycle
                        ? `Last: ${statusLabel(lastCycle.status)}`
                        : "Idle"}
              </h2>
            </div>
            <StatusBadge
              status={
                isCycleRunning
                  ? cancelling
                    ? "CANCELLING"
                    : "RUNNING"
                  : cycleLoginRequired
                    ? "LOGIN_REQUIRED"
                    : lastCycle?.status ?? "IDLE"
              }
              size="md"
            />
          </div>
          <p className="card-note">
            {isCycleRunning && isWaitingForAnswer
              ? "Paused on a screening question — answer it in the panel above."
              : isCycleRunning
                ? "Discovery and application in progress."
                : cycleLoginRequired
                  ? "Naukri session is signed out. Applications were not started. Sign in manually in the agent browser, then run the cycle again."
                  : cycleConflict
                    ? "Another cycle is already running — refresh the status."
                    : lastCycle?.status === "COMPLETED"
                      ? "Last cycle completed successfully."
                      : lastCycle?.status === "CANCELLED"
                        ? "Last cycle was cancelled."
                        : lastCycle?.status === "FAILED"
                          ? "Last cycle failed. Check logs for details."
                          : "No autonomous run yet. Starts with discovery, then applies to every eligible match."}
          </p>
          <div className="card-actions">
            {!isCycleRunning && !cycleConflict && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={onConfirmRunCycle}
                disabled={cycleRequestInFlight}
              >
                <Play size={15} />
                {startCycleLoading ? "Starting…" : "Run autonomous cycle"}
              </button>
            )}
            {cycleConflict && (
              <button type="button" className="btn btn-secondary" onClick={onRefreshCycle}>
                Refresh status
              </button>
            )}
            {activeCycle?.run_id || lastCycle?.run_id ? (
              <span className="meta-item quiet">
                Run #{activeCycle?.run_id ?? lastCycle?.run_id}
              </span>
            ) : null}
            {!isCycleRunning && lastCycle && Object.keys(lastCycle.stats).length > 0 && (
              <span className="meta-item quiet">
                {typeof lastCycle.stats.applied === "number" ? `${lastCycle.stats.applied} applied` : ""}
                {typeof lastCycle.stats.needs_attention === "number"
                  ? ` · ${lastCycle.stats.needs_attention} needs attention`
                  : ""}
                {typeof lastCycle.stats.external === "number" ? ` · ${lastCycle.stats.external} external` : ""}
              </span>
            )}
          </div>
        </section>

        <AgentControl />
      </div>

      <div className="shortcut-row">
        <button type="button" className="shortcut" onClick={() => navigate("apply")}>
          <ListChecks size={18} />
          <span>
            <b>Apply Queue</b>
            <small>Apply to discovered jobs on demand</small>
          </span>
          <ArrowUpRight size={15} className="shortcut-arrow" />
        </button>
        <button type="button" className="shortcut" onClick={() => navigate("ai-queue")}>
          <Sparkles size={18} />
          <span>
            <b>AI Queue</b>
            <small>
              {aiCounts
                ? `${aiCounts.total_queued} queued · ${aiCounts.total_quota_blocked} quota-blocked`
                : "Analysis workbench"}
            </small>
          </span>
          <ArrowUpRight size={15} className="shortcut-arrow" />
        </button>
        <button type="button" className="shortcut" onClick={() => navigate("attention")}>
          <CircleAlert size={18} />
          <span>
            <b>Needs Attention</b>
            <small>
              {needsAttentionLoading
                ? "Loading…"
                : `${unresolvedAttention} open item${unresolvedAttention === 1 ? "" : "s"}`}
            </small>
          </span>
          <ArrowUpRight size={15} className="shortcut-arrow" />
        </button>
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">Review</p>
              <h2 className="card-title">Needs attention</h2>
            </div>
            <button type="button" className="link-button" onClick={() => navigate("attention")}>
              View all <ArrowUpRight size={13} />
            </button>
          </div>
          {needsAttentionLoading ? (
            <LoadingState compact title="Loading…" />
          ) : needsAttentionError ? (
            <ErrorState compact title="Needs-attention data unavailable" message="Please retry." action={{ label: "Retry", onClick: onRetry }} />
          ) : needsAttention.length === 0 ? (
            <EmptyState compact title="Nothing needs attention" message="Unresolved issues will appear here." />
          ) : (
            <ul className="mini-list">
              {needsAttention.slice(0, 5).map((item) => (
                <li key={item.application_id}>
                  <div className="cell-title">
                    <strong>{item.job_title}</strong>
                    <span>{item.company}</span>
                  </div>
                  <div className="mini-meta">
                    <StatusBadge status={item.status} />
                    {item.failure_reason && (
                      <span className="reason-text" title={item.failure_reason}>
                        {item.failure_reason}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">Activity</p>
              <h2 className="card-title">Latest applications</h2>
            </div>
            <button type="button" className="link-button" onClick={() => navigate("activity")}>
              View all <ArrowUpRight size={13} />
            </button>
          </div>
          {recentAppsLoading ? (
            <LoadingState compact title="Loading…" />
          ) : recentAppsError ? (
            <ErrorState compact title="Activity data unavailable" message="Please retry." action={{ label: "Retry", onClick: onRetry }} />
          ) : recentApps.length === 0 ? (
            <EmptyState compact title="No applications yet" message="Run the agent to begin." />
          ) : (
            <ul className="mini-list">
              {recentApps.slice(0, 5).map((app) => (
                <li key={app.application_id}>
                  <div className="cell-title">
                    <strong>{app.job_title}</strong>
                    <span>{app.company}</span>
                  </div>
                  <div className="mini-meta">
                    <StatusBadge status={app.status} />
                    <span className="meta-item quiet">{fmtDateTime(app.applied_at ?? app.created_at)}</span>
                    {app.is_dry_run && <span className="badge tone-gray">Dry run</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">System</p>
              <h2 className="card-title">Agent & profile</h2>
            </div>
          </div>
          <dl className="detail-list">
            <div>
              <dt>Backend</dt>
              <dd>{health ? `${health.service} v${health.version}` : "Not available"}</dd>
            </div>
            <div>
              <dt>Agent state</dt>
              <dd>{health?.agent_state.replaceAll("_", " ") ?? "Unknown"}</dd>
            </div>
            <div>
              <dt>Profile</dt>
              <dd>
                {dashboardLoading
                  ? "…"
                  : dashboard
                    ? `${statusLabel(dashboard.profile.status)}${dashboard.profile.confirmed ? " · confirmed" : ""}`
                    : "—"}
              </dd>
            </div>
            <div>
              <dt>Resume</dt>
              <dd>{dashboard?.profile.original_filename ?? "Not uploaded"}</dd>
            </div>
            <div>
              <dt>Discovery runs</dt>
              <dd>{dashboardLoading ? "…" : dashboard?.discovery.total_runs ?? 0}</dd>
            </div>
            <div>
              <dt>Last discovery</dt>
              <dd>
                {dashboard?.discovery.run_id
                  ? `#${dashboard.discovery.run_id} · ${dashboard.discovery.jobs_discovered} jobs · ${dashboard.discovery.status}`
                  : "No runs yet"}
              </dd>
            </div>
          </dl>
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <p className="eyebrow">Notifications</p>
              <h2 className="card-title">Recent events</h2>
            </div>
            <button type="button" className="link-button" onClick={() => navigate("notifications")}>
              View all <ArrowUpRight size={13} />
            </button>
          </div>
          {notifications.length === 0 ? (
            <EmptyState compact title="No notifications recorded" />
          ) : (
            <ul className="mini-list">
              {notifications.slice(0, 5).map((notification) => (
                <li key={notification.id}>
                  <div className="cell-title">
                    <strong>{notification.title}</strong>
                    <span className="meta-item quiet">{fmtDateTime(notification.created_at)}</span>
                  </div>
                  <p className="mini-note">{notification.message}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
