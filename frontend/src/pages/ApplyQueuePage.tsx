import { useCallback, useEffect, useRef, useState } from "react";
import { ListChecks, Play, Square } from "lucide-react";
import {
  getManualEligible,
  getManualApplyStatus,
  skipManualJob,
  startManualApply,
  stopManualApply,
} from "../services/api";
import type { ManualApplyEligibleItem, ManualApplyStatusResponse } from "../types/api";
import { ScreeningQuestionPanel } from "../components/ScreeningQuestionPanel";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { ConfirmAction } from "../ui/ConfirmAction";
import { JobCard } from "../ui/JobCard";
import { PageHeader } from "../ui/PageHeader";
import { ProgressPanel } from "../ui/ProgressPanel";
import { QueueSummary } from "../ui/QueueSummary";
import { SearchFilterBar } from "../ui/SearchFilterBar";
import { StatusBadge } from "../ui/StatusBadge";
import { asNumber, exclusionLabel, fmtDate, fmtElapsed } from "../ui/status";

const POLL_MS = 4000;
const PAGE_SIZE = 100;
const SEARCH_DEBOUNCE_MS = 300;

interface ApplyQueuePageProps {
  initialQuery?: string;
}

export function ApplyQueuePage({ initialQuery }: ApplyQueuePageProps) {
  const [items, setItems] = useState<ManualApplyEligibleItem[]>([]);
  const [meta, setMeta] = useState<{
    total: number;
    eligible_count: number;
    eligible_job_ids: number[];
    profile_confirmed: boolean;
    preferences_present: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<ManualApplyStatusResponse | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [query, setQuery] = useState(initialQuery ?? "");
  const [search, setSearch] = useState(initialQuery?.trim() ?? "");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [questionNotice, setQuestionNotice] = useState<string | null>(null);
  const [skipNotice, setSkipNotice] = useState<string | null>(null);
  const statusRef = useRef<ManualApplyStatusResponse | null>(null);
  const itemsRef = useRef<ManualApplyEligibleItem[]>([]);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  const loadEligible = useCallback(
    async (reset: boolean) => {
      const seq = ++requestSeqRef.current;
      const isFirstLoad = itemsRef.current.length === 0 && reset;
      if (isFirstLoad) setLoading(true);
      else if (!reset) setLoadingMore(true);
      try {
        const offset = reset ? 0 : itemsRef.current.length;
        const data = await getManualEligible(PAGE_SIZE, offset, eligibleOnly, search);
        if (seq !== requestSeqRef.current) return;
        const next = reset
          ? data.items
          : [
              ...itemsRef.current,
              ...data.items.filter(
                (item) => !itemsRef.current.some((loaded) => loaded.job_id === item.job_id),
              ),
            ];
        itemsRef.current = next;
        setItems(next);
        setMeta({
          total: data.total,
          eligible_count: data.eligible_count,
          eligible_job_ids: data.eligible_job_ids,
          profile_confirmed: data.profile_confirmed,
          preferences_present: data.preferences_present,
        });
        setLoadError(null);
      } catch (err: unknown) {
        if (seq !== requestSeqRef.current) return;
        setLoadError((err as { message?: string } | null)?.message ?? "Unable to load the apply queue.");
      } finally {
        if (seq === requestSeqRef.current) {
          if (isFirstLoad) setLoading(false);
          else setLoadingMore(false);
        }
      }
    },
    [eligibleOnly, search],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const data = await getManualApplyStatus();
      setStatus(data);
      statusRef.current = data;
      return data;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    void loadEligible(true);
  }, [loadEligible]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    let stopped = false;
    let prevActive = statusRef.current?.active_state ?? "IDLE";

    const pollOnce = () => {
      getManualApplyStatus()
        .then((data) => {
          if (stopped) return;
          const wasActive = prevActive !== "IDLE";
          prevActive = data.active_state;
          setStatus(data);
          statusRef.current = data;
          if (wasActive && data.active_state === "IDLE") {
            void loadEligible(true);
          }
        })
        .catch(() => {
          // Keep polling; transient failures are expected.
        });
    };

    const pollInterval = setInterval(() => {
      if (!stopped) pollOnce();
    }, POLL_MS);

    const onVisible = () => {
      if (!stopped && document.visibilityState === "visible") pollOnce();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);

    return () => {
      stopped = true;
      clearInterval(pollInterval);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [loadEligible]);

  const activeRun = status?.active_run ?? null;
  const runActive = status?.active_state === "RUNNING" && Boolean(activeRun);
  const cancelling = Boolean(activeRun && (activeRun.status === "CANCELLING" || activeRun.cancel_requested));
  const waitingForAnswer = Boolean(activeRun?.waiting_for_user);
  const progress = (activeRun?.progress ?? {}) as Record<string, unknown>;
  const lastManualRun = status?.last_manual_run ?? null;
  const lockBusy = Boolean(status?.lock_held);

  const handleSkipJob = async (jobId: number) => {
    setSkipNotice(null);
    try {
      const result = await skipManualJob({ job_id: jobId });
      setSkipNotice(result.message);
      await loadEligible(true);
      await refreshStatus();
    } catch (err: unknown) {
      setSkipNotice((err as { message?: string } | null)?.message ?? "The job could not be skipped.");
    }
  };

  const eligibleItems = items.filter((item) => item.eligible);
  const selectedEligibleIds = items
    .filter((item) => item.eligible && selected.has(item.job_id))
    .map((item) => item.job_id);
  const allEligibleIds = meta?.eligible_job_ids ?? eligibleItems.map((item) => item.job_id);
  const remainingCount = meta ? Math.max(0, meta.total - items.length) : 0;
  const excludedCount = meta ? Math.max(0, meta.total - meta.eligible_count) : 0;
  const processedLoaded = items.filter(
    (item) => item.application_status === "APPLIED" || item.application_status === "EXTERNAL_APPLICATION",
  ).length;
  const userSkippedLoaded = items.filter(
    (item) => item.application_status === "SKIPPED" && (item.skip_reason ?? "").startsWith("USER_SKIPPED"),
  ).length;

  const toggleSelect = (jobId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      eligibleItems.forEach((item) => next.add(item.job_id));
      return next;
    });
  };

  const handleStart = async (jobIds: number[]) => {
    if (starting || stopping || runActive || jobIds.length === 0) return;
    setStarting(true);
    setConflict(false);
    setActionError(null);
    setNotice(null);
    try {
      const result = await startManualApply({ job_ids: jobIds, dry_run: dryRun });
      if (result.status === "RUNNING") {
        const droppedNote =
          result.dropped_job_ids.length > 0
            ? ` ${result.dropped_job_ids.length} selected job(s) were ineligible and were dropped.`
            : "";
        setNotice(`${result.message}.${droppedNote}`);
        setSelected(new Set());
        await refreshStatus();
      } else if (result.status === "NO_ELIGIBLE_JOBS") {
        setActionError(
          `${result.message}.${result.dropped_job_ids.length > 0 ? ` ${result.dropped_job_ids.length} job(s) were dropped as ineligible.` : ""}`,
        );
        await loadEligible(true);
      } else {
        setNotice(result.message);
      }
    } catch (err: unknown) {
      const e = err as { status?: number; message?: string } | null;
      if (e?.status === 409) {
        setConflict(true);
        await refreshStatus();
      } else {
        setActionError(e?.message ?? "The manual apply run could not be started.");
      }
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      await stopManualApply({});
    } catch {
      // Best-effort: refresh regardless so the UI reflects backend state.
    } finally {
      await refreshStatus();
      setStopping(false);
    }
  };

  const handleRefreshQueue = () => {
    if (loading) return;
    setNotice(null);
    setActionError(null);
    void loadEligible(true);
    void refreshStatus();
  };

  const startButtonsDisabled = starting || runActive || lockBusy;

  const runStats = runActive
    ? [
        { label: "Processed", value: `${asNumber(progress.processed) ?? 0} / ${asNumber(progress.candidates_total) ?? "?"}` },
        ...(asNumber(progress.applied) !== null ? [{ label: "Applied", value: asNumber(progress.applied) }] : []),
        ...(asNumber(progress.skipped) !== null ? [{ label: "Skipped", value: asNumber(progress.skipped) }] : []),
        ...(asNumber(progress.external) !== null ? [{ label: "External", value: asNumber(progress.external) }] : []),
        ...(asNumber(progress.needs_attention) !== null
          ? [{ label: "Needs attention", value: asNumber(progress.needs_attention) }]
          : []),
        ...(asNumber(progress.failed) !== null ? [{ label: "Failed", value: asNumber(progress.failed) }] : []),
        {
          label: "Current job",
          value:
            typeof progress.current_job_title === "string" && progress.current_job_title
              ? String(progress.current_job_title)
              : asNumber(progress.current_job_id) !== null
                ? `#${asNumber(progress.current_job_id)}`
                : "—",
        },
        ...(typeof progress.current_step === "string" && progress.current_step && !waitingForAnswer
          ? [{ label: "Step", value: progress.current_step.replaceAll("_", " ") }]
          : []),
        ...(fmtElapsed(progress.current_job_started_at)
          ? [{ label: "On this job", value: fmtElapsed(progress.current_job_started_at) }]
          : []),
        ...(typeof progress.progress_updated_at === "string" && progress.progress_updated_at
          ? [
              {
                label: "Last update",
                value: new Date(String(progress.progress_updated_at)).toLocaleTimeString(),
              },
            ]
          : []),
      ]
    : [];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Manual apply"
        title="Apply Queue"
        description="Apply to jobs already discovered in the local database — no discovery runs. Every safety check of the autonomous cycle applies identically."
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleRefreshQueue}
            disabled={loading}
          >
            Refresh queue
          </button>
        }
      />

      {conflict && (
        <div className="banner banner-danger" role="alert">
          Another apply process is already running (autonomous cycle, manual apply, or the scheduler).
          Wait for it to finish or stop it from the Overview page before starting a manual run.
        </div>
      )}
      {actionError && <div className="banner banner-danger">{actionError}</div>}
      {notice && <div className="banner banner-info">{notice}</div>}
      {skipNotice && (
        <div className="banner banner-info" role="status" aria-live="polite">
          {skipNotice}
        </div>
      )}
      {questionNotice && !waitingForAnswer && (
        <div className="banner banner-success" role="status" aria-live="polite">
          {questionNotice}
        </div>
      )}

      {meta && !meta.profile_confirmed && (
        <div className="banner banner-warning">
          Confirm your profile before starting an apply run — jobs are excluded until then.
        </div>
      )}
      {meta && !meta.preferences_present && (
        <div className="banner banner-warning">
          Set your job preferences — relevance checks exclude jobs until preferences exist.
        </div>
      )}

      <QueueSummary
        ariaLabel="Apply queue summary"
        stats={[
          { label: "Total discovered", value: meta ? meta.total : "…", tone: "gray" },
          { label: "Eligible", value: meta ? meta.eligible_count : "…", tone: "green" },
          { label: "Loaded", value: items.length, tone: "blue" },
          { label: "Selected", value: selectedEligibleIds.length, tone: "violet" },
          { label: "Excluded / protected", value: excludedCount, tone: "red" },
          { label: "Processed (loaded)", value: processedLoaded, tone: "amber" },
        ]}
      />

      <SearchFilterBar
        query={query}
        onQueryChange={setQuery}
        searchPlaceholder="Filter by title or company"
        searchLabel="Filter jobs by title or company"
        onRefresh={handleRefreshQueue}
        refreshDisabled={loading}
      >
        <label className="toggle-field">
          <input type="checkbox" checked={eligibleOnly} onChange={(e) => setEligibleOnly(e.target.checked)} />
          Eligible only
        </label>
        <label className="toggle-field" title="Inspect application forms without submitting anything">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            disabled={runActive}
          />
          Dry run
        </label>
        {dryRun && <span className="chip chip-amber">Dry run — nothing will be submitted</span>}
      </SearchFilterBar>

      <p className="result-line" aria-live="polite">
        {meta
          ? `Showing ${items.length} of ${meta.total} discovered job(s) · ${meta.eligible_count} eligible` +
            (remainingCount > 0 ? ` · ${remainingCount} remaining` : "") +
            (search ? ` · matching “${search}”` : "")
          : "Loading queue…"}
        {userSkippedLoaded > 0 ? ` · ${userSkippedLoaded} skipped by you (loaded)` : ""}
      </p>

      {runActive && activeRun && (
        <ProgressPanel
          eyebrow="Run in progress"
          stateLabel={
            cancelling ? "Stopping…" : waitingForAnswer ? "Waiting for your answer" : "Running"
          }
          stateTone={cancelling || waitingForAnswer ? "amber" : "green"}
          description={
            waitingForAnswer
              ? "A screening question is waiting — answer it below to resume."
              : cancelling
                ? "Cancellation requested. Finishing the current safe step…"
                : "Applications are being processed with the standard safety checks."
          }
          stats={runStats}
          actions={
            <button
              className="btn btn-danger"
              onClick={handleStop}
              disabled={stopping || cancelling}
              aria-label="Stop apply run"
            >
              <Square size={15} />
              {stopping || cancelling ? "Stopping…" : "Stop run"}
            </button>
          }
        />
      )}

      {runActive && waitingForAnswer && (
        <ScreeningQuestionPanel
          active
          heading={`Screening question`}
          onAnswered={(message) => {
            setQuestionNotice(message);
            void refreshStatus();
          }}
        />
      )}

      {!runActive && conflict && status?.lock_held && (
        <div className="banner banner-warning">
          The lock is held by another process; manual starts are refused until it releases.
        </div>
      )}

      {!runActive && lastManualRun && (
        <ProgressPanel
          eyebrow="Last manual run"
          stateLabel={lastManualRun.status}
          stateTone={
            lastManualRun.status === "FAILED"
              ? "red"
              : lastManualRun.status === "CANCELLED"
                ? "gray"
                : lastManualRun.status === "COMPLETED"
                  ? "green"
                  : "blue"
          }
          variant="muted"
          description={
            <>
              {typeof lastManualRun.stats.applied === "number"
                ? `${lastManualRun.stats.applied} applied`
                : "No submissions"}
              {typeof lastManualRun.stats.skipped === "number" ? ` · ${lastManualRun.stats.skipped} skipped` : ""}
              {typeof lastManualRun.stats.failed === "number" && lastManualRun.stats.failed > 0
                ? ` · ${lastManualRun.stats.failed} failed`
                : ""}
              {typeof lastManualRun.stats.needs_attention === "number" && lastManualRun.stats.needs_attention > 0
                ? ` · ${lastManualRun.stats.needs_attention} needs attention`
                : ""}
              {typeof lastManualRun.stats.external === "number" && lastManualRun.stats.external > 0
                ? ` · ${lastManualRun.stats.external} external`
                : ""}
              {typeof lastManualRun.stats.submitted_unconfirmed === "number" && lastManualRun.stats.submitted_unconfirmed > 0
                ? ` · ${lastManualRun.stats.submitted_unconfirmed} unconfirmed`
                : ""}
              {typeof lastManualRun.stats.dropped === "number" && lastManualRun.stats.dropped > 0
                ? ` · ${lastManualRun.stats.dropped} dropped in preflight`
                : ""}
              {typeof lastManualRun.stats.cancelled_remaining === "number" && lastManualRun.stats.cancelled_remaining > 0
                ? ` · ${lastManualRun.stats.cancelled_remaining} not started (stopped)`
                : ""}
              {lastManualRun.error ? ` · ${lastManualRun.error}` : ""}
              {lastManualRun.completed_at ? ` · ${fmtDate(lastManualRun.completed_at)}` : ""}
            </>
          }
        />
      )}

      <div className="batch-actions">
        <button
          className="btn btn-primary"
          onClick={() => handleStart(selectedEligibleIds)}
          disabled={startButtonsDisabled || selectedEligibleIds.length === 0}
        >
          <Play size={15} />
          {starting ? "Starting…" : `Apply to Selected (${selectedEligibleIds.length})`}
        </button>
        <button
          className="btn btn-outline"
          onClick={() => handleStart(allEligibleIds)}
          disabled={startButtonsDisabled || allEligibleIds.length === 0}
          title="Server-side selection: every eligible job of the search-matched set, not just this page"
        >
          <ListChecks size={15} />
          Apply to All Eligible ({allEligibleIds.length})
        </button>
        <button className="btn btn-secondary btn-sm" onClick={selectAllVisible} disabled={eligibleItems.length === 0}>
          Select visible
        </button>
        <button className="btn btn-secondary btn-sm" onClick={() => setSelected(new Set())} disabled={selected.size === 0}>
          Clear selection
        </button>
      </div>

      {loading ? (
        <LoadingState title="Loading apply queue…" />
      ) : loadError ? (
        <ErrorState
          title="Unable to load the apply queue"
          message={loadError}
          action={{ label: "Retry", onClick: () => void loadEligible(true) }}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title={search ? `No jobs match “${search}”.` : "No jobs match the current filter."}
          message="Try clearing the search or the eligible-only filter."
          action={{ label: "Clear filters", onClick: () => { setQuery(""); setEligibleOnly(false); } }}
        />
      ) : (
        <>
          <ul className="job-list">
            {items.map((item) => (
              <li key={item.job_id}>
                <JobCard
                  job={{
                    job_id: item.job_id,
                    title: item.title,
                    company: item.company,
                    location: item.location,
                    experience: item.experience,
                    discovered_at: item.discovered_at,
                  }}
                  selected={selected.has(item.job_id)}
                  dimmed={!item.eligible}
                  checkbox={
                    <input
                      type="checkbox"
                      checked={selected.has(item.job_id)}
                      disabled={!item.eligible || runActive}
                      onChange={() => toggleSelect(item.job_id)}
                      aria-label={`Select ${item.title} at ${item.company}`}
                    />
                  }
                  badges={
                    <>
                      {item.eligible ? (
                        <span className="badge tone-green">Eligible</span>
                      ) : (
                        <span className="badge tone-red" title={item.exclusion_reason ?? undefined}>
                          {exclusionLabel(item.exclusion_reason)}
                        </span>
                      )}
                      {item.application_status && (
                        <StatusBadge
                          status={item.application_status}
                          title={item.skip_reason ?? undefined}
                          label={
                            item.application_status === "SKIPPED" &&
                            (item.skip_reason ?? "").startsWith("USER_SKIPPED")
                              ? "Skipped by you"
                              : undefined
                          }
                        />
                      )}
                    </>
                  }
                  meta={
                    <>
                      {item.application_mode && (
                        <span className="chip chip-quiet">
                          {item.application_mode.replaceAll("_", " ").toLowerCase()}
                        </span>
                      )}
                    </>
                  }
                  actions={
                    item.eligible ? (
                      <ConfirmAction
                        label="Skip this job"
                        confirmLabel="Confirm skip"
                        ariaLabel={`Skip ${item.title}`}
                        onConfirm={() => void handleSkipJob(item.job_id)}
                      />
                    ) : null
                  }
                />
              </li>
            ))}
          </ul>
          {remainingCount > 0 && (
            <div className="load-more">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void loadEligible(false)}
                disabled={loadingMore}
              >
                {loadingMore
                  ? "Loading…"
                  : `Load more (${remainingCount} of ${meta?.total ?? remainingCount} remaining)`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
