import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Brain, ExternalLink, Hourglass, ListRestart, RotateCcw, SearchX } from "lucide-react";
import {
  getAIProviderStatus,
  getAIQueueItems,
  getAIQueueStatus,
  getJobsList,
  recoverStaleAIQueueItems,
  retryAIQueueItem,
} from "../services/api";
import type { AIProviderStatusResponse, AIQueueCounts, AIQueueItem, AIQueueStatus, JobListItem } from "../types/api";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { useShell } from "../app/shell";
import { DetailDrawer } from "../ui/DetailDrawer";
import { PageHeader } from "../ui/PageHeader";
import { QueueSummary } from "../ui/QueueSummary";
import { SearchFilterBar } from "../ui/SearchFilterBar";
import { StatusBadge } from "../ui/StatusBadge";
import { fmtDateTime, fmtRelative, statusLabel } from "../ui/status";

const PAGE_SIZE = 50;
const JOB_PAGE = 100;

const STATUS_FILTERS: Array<AIQueueStatus | ""> = [
  "",
  "QUEUED",
  "PROCESSING",
  "RETRY_PENDING",
  "QUOTA_BLOCKED",
  "NEEDS_ATTENTION",
  "FAILED",
  "COMPLETED",
];

function providerExplanation(status: AIProviderStatusResponse | null): string | null {
  if (!status) return null;
  switch (status.status) {
    case "AVAILABLE":
      return "AI provider configured and reachable. Queued jobs are analyzed in order.";
    case "NOT_CONFIGURED":
      return "No AI provider configured — the deterministic fallback decides matching instead. Add provider credentials in the backend .env to enable AI analysis.";
    case "QUOTA_EXHAUSTED":
      return "The provider quota is exhausted. Queued items are held (quota-blocked) until the quota resets; no credentials are stored or displayed here.";
    case "AUTH_ERROR":
      return "The provider rejected the configured credentials. Update the backend configuration; queued items are not lost.";
    default:
      return "The provider is currently unavailable. Queued items wait safely and use the deterministic fallback in the meantime.";
  }
}

export function AIQueuePage() {
  const { navigate } = useShell();
  const [counts, setCounts] = useState<AIQueueCounts | null>(null);
  const [provider, setProvider] = useState<AIProviderStatusResponse | null>(null);
  const [items, setItems] = useState<AIQueueItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<AIQueueStatus | "">("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [jobMap, setJobMap] = useState<Map<number, JobListItem>>(new Map());
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [recovering, setRecovering] = useState(false);
  const [detail, setDetail] = useState<AIQueueItem | null>(null);
  const requestSeq = useRef(0);
  const itemsRef = useRef<AIQueueItem[]>([]);

  const loadCounts = useCallback(async () => {
    try {
      const [queueCounts, providerStatus] = await Promise.all([getAIQueueStatus(), getAIProviderStatus()]);
      setCounts(queueCounts);
      setProvider(providerStatus);
    } catch {
      // The status cards render their own empty state.
    }
  }, []);

  const loadItems = useCallback(
    async (reset: boolean) => {
      const seq = ++requestSeq.current;
      if (reset) setLoading(true);
      else setLoadingMore(true);
      try {
        const data = await getAIQueueItems(statusFilter || null, PAGE_SIZE, reset ? 0 : itemsRef.current.length);
        if (seq !== requestSeq.current) return;
        const next = reset
          ? data
          : [...itemsRef.current, ...data.filter((row) => !itemsRef.current.some((p) => p.id === row.id))];
        itemsRef.current = next;
        setItems(next);
        setLoadError(null);
      } catch (err: unknown) {
        if (seq === requestSeq.current) {
          setLoadError((err as { message?: string } | null)?.message ?? "Unable to load the AI queue.");
        }
      } finally {
        if (seq === requestSeq.current) {
          if (reset) setLoading(false);
          else setLoadingMore(false);
        }
      }
    },
    [statusFilter],
  );

  useEffect(() => {
    void loadCounts();
    void loadItems(true);
  }, [loadCounts, loadItems]);

  useEffect(() => {
    let cancelled = false;
    const loadJobs = async () => {
      const map = new Map<number, JobListItem>();
      let offset = 0;
      for (;;) {
        try {
          const page = await getJobsList(JOB_PAGE, offset);
          if (cancelled) return;
          page.jobs.forEach((job) => map.set(job.job_id, job));
          offset += page.jobs.length;
          if (page.jobs.length === 0 || offset >= page.total) break;
        } catch {
          return;
        }
      }
      if (!cancelled) setJobMap(map);
    };
    void loadJobs();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => {
      const job = jobMap.get(item.job_id);
      const haystack = [
        job?.title ?? "",
        job?.company ?? "",
        item.failure_reason ?? "",
        item.last_error ?? "",
        `#${item.job_id}`,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [items, query, jobMap]);

  const filteredTotal = statusFilter
    ? counts
      ? counts[
          statusFilter === "QUEUED"
            ? "total_queued"
            : statusFilter === "PROCESSING"
              ? "total_processing"
              : statusFilter === "COMPLETED"
                ? "total_completed"
                : statusFilter === "RETRY_PENDING"
                  ? "total_retry_pending"
                  : statusFilter === "QUOTA_BLOCKED"
                    ? "total_quota_blocked"
                    : statusFilter === "NEEDS_ATTENTION"
                      ? "total_needs_attention"
                      : "total_failed"
        ]
      : null
    : counts?.total_items ?? null;

  const handleRetry = async (item: AIQueueItem) => {
    if (busyId) return;
    setBusyId(item.id);
    setActionError(null);
    setNotice(null);
    try {
      const updated = await retryAIQueueItem(
        item.id,
        item.failure_reason ?? "Manual retry requested from the AI Queue",
        item.last_error ?? "",
      );
      const next = itemsRef.current.map((row) => (row.id === updated.id ? updated : row));
      itemsRef.current = next;
      setItems(next);
      setNotice(`Retry scheduled for job #${item.job_id} — the item returns to the queue with backoff.`);
      await loadCounts();
    } catch (err: unknown) {
      setActionError((err as { message?: string } | null)?.message ?? "The retry could not be scheduled.");
    } finally {
      setBusyId(null);
    }
  };

  const handleRecoverStale = async () => {
    if (recovering) return;
    setRecovering(true);
    setActionError(null);
    setNotice(null);
    try {
      const result = await recoverStaleAIQueueItems();
      setNotice(
        result.recovered_count > 0
          ? `${result.recovered_count} stale item(s) returned to the queue.`
          : "No stale processing items were found.",
      );
      await loadCounts();
      await loadItems(true);
    } catch (err: unknown) {
      setActionError((err as { message?: string } | null)?.message ?? "Stale recovery failed.");
    } finally {
      setRecovering(false);
    }
  };

  const remainingForFilter = filteredTotal !== null ? Math.max(0, filteredTotal - items.length) : 0;

  return (
    <div className="page">
      <PageHeader
        eyebrow="AI processing"
        title="AI Queue"
        description="Workbench for AI-analyzed jobs: queued, processing, completed, quota-blocked, and failed items. Analysis happens on the backend — nothing here triggers new AI requests."
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => handleRecoverStale()} disabled={recovering}>
            <ListRestart size={15} />
            {recovering ? "Recovering…" : "Recover stale"}
          </button>
        }
      />

      {notice && <div className="banner banner-success" role="status">{notice}</div>}
      {actionError && <div className="banner banner-danger">{actionError}</div>}

      <div className="split-top">
        <QueueSummary
          ariaLabel="AI queue summary"
          stats={[
            { label: "Queued", value: counts ? counts.total_queued : "…", tone: "blue" },
            { label: "Processing", value: counts ? counts.total_processing : "…", tone: "violet" },
            { label: "Completed", value: counts ? counts.total_completed : "…", tone: "green" },
            { label: "Retry pending", value: counts ? counts.total_retry_pending : "…", tone: "orange" },
            { label: "Quota blocked", value: counts ? counts.total_quota_blocked : "…", tone: "amber" },
            { label: "Needs attention", value: counts ? counts.total_needs_attention : "…", tone: "amber" },
            { label: "Failed", value: counts ? counts.total_failed : "…", tone: "red" },
            { label: "Total items", value: counts ? counts.total_items : "…", tone: "gray" },
          ]}
        />

        <section className="card provider-card">
          <div className="card-head">
            <span className="card-head-icon">
              <Brain size={16} />
            </span>
            <div>
              <h2 className="card-title">AI provider</h2>
              <p className="card-subtitle">
                {provider ? `${provider.provider} · ${provider.model ?? "model not set"}` : "Status unavailable"}
              </p>
            </div>
            {provider && <StatusBadge status={provider.status} label={provider.status.replaceAll("_", " ")} size="md" />}
          </div>
          <div className="provider-stats">
            <span>
              <b>{provider?.requests ?? 0}</b> requests
            </span>
            <span>
              <b>{provider?.cached ?? 0}</b> cached
            </span>
            <span>
              <b>{provider?.errors ?? 0}</b> errors
            </span>
            {provider?.updated_at && <span className="quiet">updated {fmtRelative(provider.updated_at)}</span>}
          </div>
          {providerExplanation(provider) && <p className="provider-note">{providerExplanation(provider)}</p>}
        </section>
      </div>

      <SearchFilterBar
        query={query}
        onQueryChange={setQuery}
        searchPlaceholder="Search by job, error, or id"
        searchLabel="Search AI queue"
        onRefresh={() => { void loadCounts(); void loadItems(true); }}
        refreshDisabled={loading}
      >
        <select
          className="select-field"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as AIQueueStatus | "");
          }}
          aria-label="Filter by queue status"
        >
          {STATUS_FILTERS.map((value) => (
            <option key={value || "all"} value={value}>
              {value ? statusLabel(value) : "All statuses"}
            </option>
          ))}
        </select>
      </SearchFilterBar>

      {loading ? (
        <LoadingState title="Loading AI queue…" />
      ) : loadError ? (
        <ErrorState title="Unable to load the AI queue" message={loadError} action={{ label: "Retry", onClick: () => void loadItems(true) }} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={statusFilter === "" && !query ? Hourglass : SearchX}
          title={
            statusFilter === "" && !query
              ? "The AI queue is empty"
              : query
                ? `No queue items match “${query}”.`
                : `No ${statusLabel(statusFilter).toLowerCase()} items right now.`
          }
          message="Queued jobs appear here when the backend enqueues them for analysis."
        />
      ) : (
        <>
          <div className="table-card">
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Priority</th>
                    <th>Last attempt</th>
                    <th>Next retry</th>
                    <th className="align-end">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((item) => {
                    const job = jobMap.get(item.job_id);
                    const retryable = item.status === "FAILED" && item.attempt_count < item.max_attempts;
                    return (
                      <tr key={item.id}>
                        <td data-label="Job">
                          <div className="cell-title">
                            <strong title={job?.title ?? `Job #${item.job_id}`}>{job?.title ?? `Job #${item.job_id}`}</strong>
                            <span>{job?.company ?? "—"}</span>
                          </div>
                        </td>
                        <td data-label="Status">
                          <StatusBadge status={item.status} />
                        </td>
                        <td data-label="Attempts">
                          {item.attempt_count} / {item.max_attempts}
                        </td>
                        <td data-label="Priority">{item.priority}</td>
                        <td data-label="Last attempt">{item.last_attempt_at ? fmtRelative(item.last_attempt_at) : "—"}</td>
                        <td data-label="Next retry">{item.next_retry_at ? fmtDateTime(item.next_retry_at) : "—"}</td>
                        <td data-label="Actions" className="align-end">
                          <div className="row-actions">
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={() => setDetail(item)}
                            >
                              Details
                            </button>
                            {job && (
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => navigate("jobs", { query: job.title })}
                                title="Find this job on the Jobs page"
                              >
                                <ExternalLink size={13} />
                                Job
                              </button>
                            )}
                            {retryable && (
                              <button
                                type="button"
                                className="btn btn-outline btn-sm"
                                onClick={() => void handleRetry(item)}
                                disabled={busyId === item.id}
                                title="Backend-scheduled retry with backoff"
                              >
                                <RotateCcw size={13} />
                                {busyId === item.id ? "Scheduling…" : "Retry"}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          {remainingForFilter > 0 && (
            <div className="load-more">
              <button type="button" className="btn btn-secondary" onClick={() => void loadItems(false)} disabled={loadingMore}>
                {loadingMore ? "Loading…" : `Load more (${remainingForFilter} remaining)`}
              </button>
            </div>
          )}
        </>
      )}

      <DetailDrawer
        open={detail !== null}
        title={detail ? jobMap.get(detail.job_id)?.title ?? `Job #${detail.job_id}` : ""}
        subtitle={detail ? <StatusBadge status={detail.status} size="md" /> : undefined}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <dl className="detail-list">
            <div>
              <dt>Status</dt>
              <dd>
                <StatusBadge status={detail.status} />
              </dd>
            </div>
            <div>
              <dt>Job id</dt>
              <dd>#{detail.job_id}</dd>
            </div>
            <div>
              <dt>Attempts</dt>
              <dd>
                {detail.attempt_count} of {detail.max_attempts} max
              </dd>
            </div>
            <div>
              <dt>Priority</dt>
              <dd>
                {detail.priority}
                {detail.priority_reason ? ` — ${detail.priority_reason}` : ""}
              </dd>
            </div>
            <div>
              <dt>Queue source</dt>
              <dd>{detail.queue_source ?? "—"}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{fmtDateTime(detail.created_at)}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{fmtDateTime(detail.updated_at)}</dd>
            </div>
            <div>
              <dt>Last attempt</dt>
              <dd>{fmtDateTime(detail.last_attempt_at)}</dd>
            </div>
            <div>
              <dt>Next retry</dt>
              <dd>{fmtDateTime(detail.next_retry_at)}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd>{fmtDateTime(detail.completed_at)}</dd>
            </div>
            <div>
              <dt>Analysis id</dt>
              <dd>{detail.analysis_id ? `#${detail.analysis_id}` : "Not analyzed yet"}</dd>
            </div>
            <div>
              <dt>Failure reason</dt>
              <dd className="pre-wrap">{detail.failure_reason ?? "—"}</dd>
            </div>
            <div>
              <dt>Last error</dt>
              <dd className="pre-wrap">{detail.last_error ?? "—"}</dd>
            </div>
          </dl>
        )}
      </DetailDrawer>
    </div>
  );
}
