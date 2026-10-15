import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Briefcase, ListChecks, MapPin, Play, RefreshCw, Search, Square } from "lucide-react";
import { getManualEligible, getManualApplyStatus, startManualApply, stopManualApply } from "../services/api";
import type { ManualApplyEligibleItem, ManualApplyStatusResponse } from "../types/api";

interface ManualApplyQueueProps {
  onBack: () => void;
}

const POLL_MS = 4000;

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

function exclusionLabel(reason: string | null): string {
  if (!reason) return "Not eligible";
  if (reason === "external_application") return "External application — not selectable here";
  if (reason === "application_history") return "Already applied — protected by application history";
  if (reason === "profile_not_confirmed") return "Profile not confirmed";
  if (reason === "preferences_missing") return "Job preferences missing";
  if (reason.startsWith("not_relevant:")) return `Not relevant — ${reason.slice("not_relevant:".length).trim()}`;
  if (reason.startsWith("hard_filtered:")) return `Filtered — ${reason.slice("hard_filtered:".length).trim()}`;
  return reason;
}

export function ManualApplyQueue({ onBack }: ManualApplyQueueProps) {
  const [items, setItems] = useState<ManualApplyEligibleItem[]>([]);
  const [meta, setMeta] = useState<{ total: number; eligible_count: number; profile_confirmed: boolean; preferences_present: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<ManualApplyStatusResponse | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [query, setQuery] = useState("");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const statusRef = useRef<ManualApplyStatusResponse | null>(null);

  const loadEligible = useCallback(async (showLoading: boolean) => {
    if (showLoading) setLoading(true);
    try {
      const data = await getManualEligible(200, 0, false);
      setItems(data.items);
      setMeta({
        total: data.total,
        eligible_count: data.eligible_count,
        profile_confirmed: data.profile_confirmed,
        preferences_present: data.preferences_present,
      });
      setLoadError(null);
    } catch (err: any) {
      setLoadError(err?.message ?? "Unable to load the apply queue.");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

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
    void refreshStatus();
  }, [loadEligible, refreshStatus]);

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
            void loadEligible(false);
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

  const filtered = items.filter((item) => {
    if (eligibleOnly && !item.eligible) return false;
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return item.title.toLowerCase().includes(q) || item.company.toLowerCase().includes(q);
  });
  const eligibleItems = filtered.filter((item) => item.eligible);
  const selectedEligibleIds = items.filter((item) => item.eligible && selected.has(item.job_id)).map((item) => item.job_id);

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
        await loadEligible(false);
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
    ? `Showing ${filtered.length} of ${meta.total} discovered job(s) · ${meta.eligible_count} eligible`
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
                ? "A screening question is waiting. Answer it from the Overview page to resume."
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
              {typeof lastManualRun.stats.needs_attention === "number" && lastManualRun.stats.needs_attention > 0
                ? ` · ${lastManualRun.stats.needs_attention} needs attention`
                : ""}
              {typeof lastManualRun.stats.external === "number" && lastManualRun.stats.external > 0
                ? ` · ${lastManualRun.stats.external} external`
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
          onClick={() => handleStart(eligibleItems.map((i) => i.job_id))}
          disabled={startButtonsDisabled || eligibleItems.length === 0}
        >
          <ListChecks size={16} />
          Apply to All Eligible ({eligibleItems.length})
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
        <p className="error-text">{loadError}</p>
      ) : filtered.length === 0 ? (
        <p>No jobs match the current filter.</p>
      ) : (
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
                      <span className="status-badge">
                        {item.application_status.replace(/_/g, " ")}
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
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
