import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Briefcase, ListChecks, MapPin, Play, RefreshCw, Search, Square } from "lucide-react";
import {
  answerPendingQuestion,
  getManualEligible,
  getManualApplyStatus,
  getPendingQuestion,
  skipManualJob,
  startManualApply,
  stopManualApply,
} from "../services/api";
import type {
  AnswerQuestionRequest,
  ManualApplyEligibleItem,
  ManualApplyStatusResponse,
  PendingQuestion,
} from "../types/api";

interface ManualApplyQueueProps {
  onBack: () => void;
}

const POLL_MS = 4000;
/** E5-R30: rows fetched per page; "Load more" pages through the server. */
const PAGE_SIZE = 100;
const SEARCH_DEBOUNCE_MS = 300;

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

/** E5-R31: human duration since an ISO timestamp ("42s", "3m 10s", "1h 4m"). */
function fmtElapsed(from: unknown): string | null {
  if (typeof from !== "string" || !from) return null;
  const started = new Date(from).getTime();
  if (!Number.isFinite(started)) return null;
  const deltaMs = Date.now() - started;
  if (deltaMs < 0) return null;
  const totalSeconds = Math.floor(deltaMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) return `${minutes}m ${totalSeconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function exclusionLabel(reason: string | null): string {
  if (!reason) return "Not eligible";
  if (reason === "external_application") return "External application — not selectable here";
  if (reason === "application_history") return "Already applied — protected by application history";
  if (reason === "listing_expired") return "Listing expired — removed from the queue";
  if (reason === "profile_not_confirmed") return "Profile not confirmed";
  if (reason === "preferences_missing") return "Job preferences missing";
  // E5-R32: an operator-requested skip excludes the job until a manual reset.
  if (reason === "user_skipped") return "Skipped by you — excluded from the queue";
  if (reason.startsWith("not_relevant:")) return `Not relevant — ${reason.slice("not_relevant:".length).trim()}`;
  if (reason.startsWith("hard_filtered:")) return `Filtered — ${reason.slice("hard_filtered:".length).trim()}`;
  return reason;
}

export function ManualApplyQueue({ onBack }: ManualApplyQueueProps) {
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
  const [query, setQuery] = useState("");
  // Debounced copy of `query` actually sent to the server (E5-R30: search is
  // server-side so counts and pagination always describe the matched set).
  const [search, setSearch] = useState("");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // E5-R32: in-place screening question (the queue used to tell the operator
  // to answer from the Overview page — and never fetched the question itself).
  const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
  const [questionLoading, setQuestionLoading] = useState(false);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [questionAnswerText, setQuestionAnswerText] = useState("");
  const [questionSubmitting, setQuestionSubmitting] = useState(false);
  const [questionNotice, setQuestionNotice] = useState<string | null>(null);
  // E5-R32: per-row two-step "Skip This Job".
  const [confirmSkipId, setConfirmSkipId] = useState<number | null>(null);
  const [skipBusy, setSkipBusy] = useState(false);
  const [skipNotice, setSkipNotice] = useState<string | null>(null);
  const statusRef = useRef<ManualApplyStatusResponse | null>(null);
  const itemsRef = useRef<ManualApplyEligibleItem[]>([]);
  // Only the latest request may apply its response (stale out-of-order
  // responses from rapid searches/pagination are dropped).
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
        if (seq !== requestSeqRef.current) return; // a newer request superseded this one
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
      } catch (err: any) {
        if (seq !== requestSeqRef.current) return;
        setLoadError(err?.message ?? "Unable to load the apply queue.");
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

  // Poll status while the queue is open (E5-R29 pattern): a single failed
  // fetch must never kill the loop, and a throttled background tab re-syncs
  // when it becomes visible again.
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
            // The run finished — refresh statuses so outcomes show up.
            void loadEligible(true);
          }
        })
        .catch(() => {
          // E5-R29: keep polling; transient failures are expected.
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

  // E5-R32: fetch the pending screening question while the run waits —
  // polled so a stale fetch self-heals, stopped the moment the wait ends.
  useEffect(() => {
    if (!waitingForAnswer) {
      setPendingQuestion(null);
      setQuestionError(null);
      setQuestionLoading(false);
      return;
    }
    let stopped = false;
    let timer: number | undefined;
    setQuestionNotice(null);
    setQuestionLoading(true);

    const fetchQuestion = async () => {
      try {
        const data = await getPendingQuestion();
        if (stopped) return;
        setPendingQuestion(data);
        setQuestionError(data.found ? null : "The question is not available yet — retrying…");
      } catch {
        if (!stopped) setQuestionError("The question could not be loaded — retrying…");
      } finally {
        if (!stopped) {
          setQuestionLoading(false);
          timer = window.setTimeout(fetchQuestion, 4000);
        }
      }
    };
    void fetchQuestion();

    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [waitingForAnswer]);

  const handleQuestionSubmit = async (skip: boolean) => {
    if (!pendingQuestion?.pending_question_id || questionSubmitting) return;
    if (!skip && !questionAnswerText.trim()) return;
    setQuestionSubmitting(true);
    setQuestionError(null);
    try {
      const request: AnswerQuestionRequest = skip
        ? { pending_question_id: pendingQuestion.pending_question_id, skip: true }
        : {
            pending_question_id: pendingQuestion.pending_question_id,
            answer: questionAnswerText.trim(),
            remember: true,
            scope: "JOB",
          };
      await answerPendingQuestion(request);
      setPendingQuestion(null);
      setQuestionAnswerText("");
      setQuestionNotice(
        skip
          ? "Job skipped — the run is resuming with the next job."
          : "Answer received — the run is resuming.",
      );
      await refreshStatus();
    } catch (error: any) {
      if (error?.status === 409) {
        // Stale question id or duplicate submit — re-sync instead of failing.
        setQuestionError("This question was already answered or has changed — refreshing…");
        const fresh = await getPendingQuestion().catch(() => null);
        setPendingQuestion(fresh);
      } else {
        setQuestionError(
          error?.message ?? "The answer could not be submitted. Please try again.",
        );
      }
    } finally {
      setQuestionSubmitting(false);
    }
  };

  // E5-R32: two-step per-row skip (accidental single clicks never skip).
  const handleSkipJob = async (jobId: number) => {
    if (skipBusy) return;
    if (confirmSkipId !== jobId) {
      setConfirmSkipId(jobId);
      return;
    }
    setSkipBusy(true);
    setSkipNotice(null);
    try {
      const result = await skipManualJob({ job_id: jobId });
      setSkipNotice(result.message);
      setConfirmSkipId(null);
      await loadEligible(true);
      await refreshStatus();
    } catch (error: any) {
      setSkipNotice(error?.message ?? "The job could not be skipped.");
      setConfirmSkipId(null);
    } finally {
      setSkipBusy(false);
    }
  };

  // E5-R30: search, eligibility filtering, and counts are computed
  // server-side; the loaded pages are already the matched set.
  const filtered = items;
  const eligibleItems = filtered.filter((item) => item.eligible);
  const selectedEligibleIds = items.filter((item) => item.eligible && selected.has(item.job_id)).map((item) => item.job_id);
  const allEligibleIds = meta?.eligible_job_ids ?? eligibleItems.map((item) => item.job_id);
  const remainingCount = meta ? Math.max(0, meta.total - items.length) : 0;

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
        const droppedNote = result.dropped_job_ids.length > 0
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
    } catch (err: any) {
      if (err?.status === 409) {
        setConflict(true);
        await refreshStatus();
      } else {
        setActionError(err?.message ?? "The manual apply run could not be started.");
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
  const statusLine = meta
    ? `Showing ${filtered.length} of ${meta.total} discovered job(s) · ${meta.eligible_count} eligible` +
      (remainingCount > 0 ? ` · ${remainingCount} remaining` : "") +
      (search ? ` · matching “${search}”` : "")
    : "Loading queue…";

  return (
    <section className="activity">
      <div className="section-header-with-back">
        <button onClick={onBack} className="back-button" aria-label="Back to dashboard">
          <ArrowLeft size={20} />
          Back
        </button>
        <div>
          <p className="eyebrow">MANUAL APPLY</p>
          <h2>Apply to Discovered Jobs</h2>
          <p className="page-description">
            Pick jobs that are already in the local database — no discovery runs. Every safety check the
            autonomous cycle uses is applied identically.
          </p>
        </div>
      </div>

      {conflict && (
        <div role="alert" className="manual-queue-banner conflict">
          Another apply process is already running (autonomous cycle, manual apply, or the scheduler).
          Wait for it to finish or stop it from the Overview page before starting a manual run.
        </div>
      )}
      {actionError && <p className="error-text">{actionError}</p>}
      {notice && <p className="manual-queue-banner info">{notice}</p>}
      {/* E5-R32: result of a per-job skip (recorded / queued / refused). */}
      {skipNotice && (
        <p className="manual-queue-banner info" role="status" aria-live="polite">
          {skipNotice}
        </p>
      )}

      {meta && !meta.profile_confirmed && (
        <p className="warning-text">Confirm your profile before starting an apply run — jobs are excluded until then.</p>
      )}
      {meta && !meta.preferences_present && (
        <p className="warning-text">Set your job preferences — relevance checks exclude jobs until preferences exist.</p>
      )}

      <div className="manual-queue-controls">
        <label className="manual-queue-search">
          <Search size={16} aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by title or company"
            aria-label="Filter jobs by title or company"
          />
        </label>
        <label className="manual-queue-toggle">
          <input
            type="checkbox"
            checked={eligibleOnly}
            onChange={(e) => setEligibleOnly(e.target.checked)}
          />
          Eligible only
        </label>
        <label className="manual-queue-toggle" title="Inspect application forms without submitting anything">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            disabled={runActive}
          />
          Dry run
        </label>
        <button className="btn btn-secondary" onClick={handleRefreshQueue} disabled={loading} aria-label="Refresh apply queue">
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      <p className="manual-queue-summary" aria-live="polite">{statusLine}</p>

      {/* Live run status (shared singleton lock) */}
      {runActive && activeRun && (
        <div className="manual-queue-run" role="status">
          <div>
            <p className="eyebrow" style={{ marginBottom: 4 }}>RUN IN PROGRESS</p>
            <strong className="agent-state running">
              {cancelling ? "Stopping…" : waitingForAnswer ? "Waiting for your answer" : "Running"}
            </strong>
            <p>
              {waitingForAnswer
                ? "A screening question is waiting — answer it below to resume."
                : cancelling
                  ? "Cancellation requested. Finishing the current safe step…"
                  : "Applications are being processed with the standard safety checks."}
            </p>
          </div>
          <div className="manual-queue-progress">
            <span>
              {asNumber(progress.processed) ?? 0} / {asNumber(progress.candidates_total) ?? "?"} processed
            </span>
            {asNumber(progress.applied) !== null && <span>{asNumber(progress.applied)} applied</span>}
            {typeof progress.skipped === "number" && progress.skipped > 0 && <span>{progress.skipped} skipped</span>}
            {typeof progress.external === "number" && progress.external > 0 && <span>{progress.external} external</span>}
            {typeof progress.needs_attention === "number" && progress.needs_attention > 0 && (
              <span>{progress.needs_attention} needs attention</span>
            )}
            {typeof progress.failed === "number" && progress.failed > 0 && <span>{progress.failed} failed</span>}
            {asNumber(progress.current_job_id) !== null && <span>Job #{asNumber(progress.current_job_id)}</span>}
            {/* E5-R31: which job, how long it's been on it, and when the
                progress document last moved (stall detection). */}
            {typeof progress.current_job_title === "string" && progress.current_job_title && (
              <span title={String(progress.current_job_title)}>
                {String(progress.current_job_title).length > 40
                  ? `${String(progress.current_job_title).slice(0, 40)}…`
                  : String(progress.current_job_title)}
              </span>
            )}
            {fmtElapsed(progress.current_job_started_at) !== null && (
              <span>{fmtElapsed(progress.current_job_started_at)} on this job</span>
            )}
            {typeof progress.progress_updated_at === "string" && progress.progress_updated_at && (
              <span>
                updated{" "}
                {(() => {
                  const ts = new Date(String(progress.progress_updated_at));
                  return Number.isNaN(ts.getTime())
                    ? String(progress.progress_updated_at)
                    : ts.toLocaleTimeString();
                })()}
              </span>
            )}
            {typeof progress.current_step === "string" && !waitingForAnswer && (
              <span>{String(progress.current_step).replaceAll("_", " ")}</span>
            )}
          </div>
          <div className="control-buttons">
            <button
              className="btn btn-danger"
              onClick={handleStop}
              disabled={stopping || cancelling}
              aria-label="Stop apply run"
            >
              <Square size={16} />
              {stopping || cancelling ? "Stopping…" : "Stop run"}
            </button>
          </div>
        </div>
      )}

      {/* E5-R32: the waiting screening question, answered in place — with
          Waiting / Answer received / Resuming states. */}
      {runActive && waitingForAnswer && (
        <div className="manual-queue-run" role="alert" style={{ marginTop: "0.5rem" }}>
          <div>
            <p className="eyebrow" style={{ marginBottom: 4 }}>
              SCREENING QUESTION
              {pendingQuestion?.job_title ? ` — ${pendingQuestion.job_title}` : ""}
              {pendingQuestion?.employer ? ` · ${pendingQuestion.employer}` : ""}
            </p>
            {questionLoading && !pendingQuestion ? (
              <p>Loading the question…</p>
            ) : pendingQuestion?.found && pendingQuestion.question_text ? (
              <>
                <p style={{ margin: "0.35rem 0" }}>
                  <strong>{pendingQuestion.question_text}</strong>
                </p>
                {pendingQuestion.options && pendingQuestion.options.length > 0 ? (
                  <select
                    value={questionAnswerText}
                    onChange={(e) => setQuestionAnswerText(e.target.value)}
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
                    value={questionAnswerText}
                    onChange={(e) => setQuestionAnswerText(e.target.value)}
                    placeholder="Type your answer"
                    aria-label="Your answer"
                  />
                )}
                {questionError && <p className="error-text">{questionError}</p>}
                <div className="control-buttons" style={{ marginTop: "0.5rem" }}>
                  <button
                    className="btn btn-primary"
                    onClick={() => void handleQuestionSubmit(false)}
                    disabled={questionSubmitting || !questionAnswerText.trim()}
                  >
                    {questionSubmitting ? "Submitting…" : "Answer & resume"}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => void handleQuestionSubmit(true)}
                    disabled={questionSubmitting}
                  >
                    Skip this job
                  </button>
                </div>
              </>
            ) : (
              <p>{questionError ?? "Waiting for the question…"}</p>
            )}
          </div>
        </div>
      )}
      {/* Answer received — the wait has cleared, the run is resuming. */}
      {questionNotice && !waitingForAnswer && (
        <p className="manual-queue-banner info" role="status" aria-live="polite">
          {questionNotice}
        </p>
      )}

      {!runActive && conflict && status?.lock_held && (
        <p className="warning-text">The lock is held by another process; manual starts are refused until it releases.</p>
      )}

      {/* Last manual run summary */}
      {!runActive && lastManualRun && (
        <div className="manual-queue-run" role="status">
          <div>
            <p className="eyebrow" style={{ marginBottom: 4 }}>LAST MANUAL RUN</p>
            <strong>
              {lastManualRun.status}
              {lastManualRun.completed_at ? ` · ${fmtDate(lastManualRun.completed_at)}` : ""}
            </strong>
            <p>
              {typeof lastManualRun.stats.applied === "number" ? `${lastManualRun.stats.applied} applied` : "No submissions"}
              {typeof lastManualRun.stats.skipped === "number" ? ` · ${lastManualRun.stats.skipped} skipped` : ""}
              {/* E5-R31: failures were previously invisible here (the failed
                  counter was never rendered), so a 61-job run that failed 59
                  jobs displayed only "1 applied · 1 skipped". */}
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
            </p>
          </div>
        </div>
      )}

      <div className="manual-queue-actions">
        <button
          className="btn btn-primary"
          onClick={() => handleStart(selectedEligibleIds)}
          disabled={startButtonsDisabled || selectedEligibleIds.length === 0}
        >
          <Play size={16} />
          {starting ? "Starting…" : `Apply to Selected (${selectedEligibleIds.length})`}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => handleStart(allEligibleIds)}
          disabled={startButtonsDisabled || allEligibleIds.length === 0}
        >
          <ListChecks size={16} />
          Apply to All Eligible ({allEligibleIds.length})
        </button>
        <button className="btn btn-secondary" onClick={selectAllVisible} disabled={eligibleItems.length === 0}>
          Select all visible
        </button>
        <button className="btn btn-secondary" onClick={() => setSelected(new Set())} disabled={selected.size === 0}>
          Clear selection
        </button>
      </div>

      {loading ? (
        <p className="text-[var(--color-text-secondary)]">Loading apply queue…</p>
      ) : loadError ? (
        <div className="manual-queue-load-error">
          <p className="error-text">{loadError}</p>
          <button className="btn btn-secondary" onClick={() => void loadEligible(true)} aria-label="Retry loading apply queue">
            Retry
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <p>{search ? `No jobs match “${search}”.` : "No jobs match the current filter."}</p>
      ) : (
        <>
          <ul className="manual-queue-list">
            {filtered.map((item) => {
            const isSelected = selected.has(item.job_id);
            return (
              <li key={item.job_id} className={`manual-queue-item ${item.eligible ? "" : "ineligible"}`}>
                <input
                  type="checkbox"
                  className="manual-queue-check"
                  checked={isSelected}
                  disabled={!item.eligible || runActive}
                  onChange={() => toggleSelect(item.job_id)}
                  aria-label={`Select ${item.title} at ${item.company}`}
                />
                <div className="manual-queue-item-main">
                  <strong>{item.title}</strong>
                  <span className="data-item-company">at {item.company}</span>
                  <div className="manual-queue-meta">
                    {item.location && (
                      <span className="data-item-detail">
                        <MapPin size={14} />
                        {item.location}
                      </span>
                    )}
                    {item.experience && (
                      <span className="data-item-detail">
                        <Briefcase size={14} />
                        {item.experience}
                      </span>
                    )}
                    {item.application_mode && (
                      <span className="data-item-detail">{item.application_mode.toLowerCase()}</span>
                    )}
                    <span className="data-item-date">Discovered {fmtDate(item.discovered_at)}</span>
                    {item.application_status && (
                      <span
                        className="status-badge"
                        title={item.skip_reason ?? undefined}
                      >
                        {/* E5-R32: distinguish operator skips from automated ones. */}
                        {item.application_status === "SKIPPED" &&
                        (item.skip_reason ?? "").startsWith("USER_SKIPPED")
                          ? "Skipped by you"
                          : item.application_status.replace(/_/g, " ")}
                      </span>
                    )}
                    {item.eligible ? (
                      <span className="manual-queue-badge eligible">Eligible</span>
                    ) : (
                      <span className="manual-queue-badge excluded" title={item.exclusion_reason ?? undefined}>
                        {exclusionLabel(item.exclusion_reason)}
                      </span>
                    )}
                  </div>
                  {/* E5-R32: per-job Skip This Job — two-step confirm. During
                      a live batch the backend queues the skip for the next
                      job boundary (never interrupts a submission). */}
                  {item.eligible && (
                    <div className="control-buttons" style={{ marginTop: "0.4rem" }}>
                      <button
                        className={`btn ${confirmSkipId === item.job_id ? "btn-danger" : "btn-secondary"}`}
                        onClick={() => void handleSkipJob(item.job_id)}
                        disabled={skipBusy}
                        aria-label={
                          confirmSkipId === item.job_id
                            ? `Confirm skipping ${item.title}`
                            : `Skip ${item.title}`
                        }
                      >
                        {skipBusy && confirmSkipId === item.job_id
                          ? "Skipping…"
                          : confirmSkipId === item.job_id
                            ? "Confirm skip"
                            : "Skip this job"}
                      </button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
          </ul>
          {remainingCount > 0 && (
            <div className="manual-queue-load-more">
              <button
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
    </section>
  );
}
