import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { getNeedsAttention } from "../services/api";
import type { NeedsAttentionItem } from "../types/api";
import { ScreeningQuestionPanel } from "../components/ScreeningQuestionPanel";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { useShell } from "../app/shell";
import { PageHeader } from "../ui/PageHeader";
import { ReasonSummary } from "../ui/ReasonSummary";
import { SearchFilterBar } from "../ui/SearchFilterBar";
import { StatusBadge } from "../ui/StatusBadge";
import { REASON_CATEGORY_LABEL, fmtDateTime, reasonCategory, type ReasonCategory } from "../ui/status";

interface NeedsAttentionPageProps {
  /**
   * Authoritative unresolved total from /dashboard/summary. The list
   * endpoint caps its page size, so its own `total` can understate the
   * real open workload.
   */
  unresolvedTotal?: number | null;
}

export function NeedsAttentionPage({ unresolvedTotal = null }: NeedsAttentionPageProps) {
  const { navigate, waitingForAnswer } = useShell();
  const [items, setItems] = useState<NeedsAttentionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<ReasonCategory | "all">("all");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getNeedsAttention(50);
      setItems(data.applications);
      setTotal(data.total);
    } catch (err: unknown) {
      setError((err as { message?: string } | null)?.message ?? "Unable to load the review queue.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const categorized = useMemo(
    () =>
      items.map((item) => ({
        item,
        category: reasonCategory(item.failure_reason, item.skip_reason),
      })),
    [items],
  );

  const categoryCounts = useMemo(() => {
    const counts = new Map<ReasonCategory, number>();
    categorized.forEach((entry) => counts.set(entry.category, (counts.get(entry.category) ?? 0) + 1));
    return counts;
  }, [categorized]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return categorized.filter(({ item }) => {
      if (category !== "all" && !(
        category === "other"
          ? reasonCategory(item.failure_reason, item.skip_reason) === "other"
          : reasonCategory(item.failure_reason, item.skip_reason) === category
      )) return false;
      if (
        q &&
        !item.job_title.toLowerCase().includes(q) &&
        !item.company.toLowerCase().includes(q) &&
        !(item.failure_reason ?? "").toLowerCase().includes(q) &&
        !(item.skip_reason ?? "").toLowerCase().includes(q)
      ) {
        return false;
      }
      return true;
    });
  }, [categorized, query, category]);

  const categoriesPresent = (Array.from(categoryCounts.keys()) as ReasonCategory[]).sort();
  const unfiltered = !query.trim() && category === "all";
  const openCount = unfiltered ? Math.max(unresolvedTotal ?? 0, filtered.length) : filtered.length;

  return (
    <div className="page">
      <PageHeader
        eyebrow="Review queue"
        title="Needs Attention"
        description={
          loading
            ? "Loading unresolved items…"
            : `${openCount} open item${openCount === 1 ? "" : "s"} requiring a human decision. Ambiguous submissions stay protected until reviewed.`
        }
        actions={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigate("applications", { statusFilter: "NEEDS_ATTENTION" })}
            >
              Full history
              <ArrowUpRight size={14} />
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => void load()} disabled={loading}>
              Refresh
            </button>
          </>
        }
      />

      {waitingForAnswer && (
        <ScreeningQuestionPanel
          active
          onAnswered={() => void load()}
          heading="Screening question"
        />
      )}

      <SearchFilterBar
        query={query}
        onQueryChange={setQuery}
        searchPlaceholder="Search job, company, or reason"
        searchLabel="Search review queue"
        onRefresh={() => void load()}
        refreshDisabled={loading}
      >
        <div className="chip-row" role="tablist" aria-label="Filter by reason category">
          <button
            type="button"
            role="tab"
            aria-selected={category === "all"}
            className={`chip chip-button${category === "all" ? " active" : ""}`}
            onClick={() => setCategory("all")}
          >
            All ({items.length})
          </button>
          {categoriesPresent.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={category === value}
              className={`chip chip-button${category === value ? " active" : ""}`}
              onClick={() => setCategory(value)}
            >
              {REASON_CATEGORY_LABEL[value]} ({categoryCounts.get(value) ?? 0})
            </button>
          ))}
        </div>
      </SearchFilterBar>

      {loading ? (
        <LoadingState title="Loading review queue…" />
      ) : error ? (
        <ErrorState title="Unable to load the review queue" message={error} action={{ label: "Retry", onClick: () => void load() }} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title={items.length === 0 ? "Nothing needs attention" : "No items match this filter"}
          message={
            items.length === 0
              ? "Unresolved application issues and pending decisions will appear here."
              : "Adjust the search or category filter to see other items."
          }
        />
      ) : (
        <ul className="review-list">
          {filtered.map(({ item, category: itemCategory }) => (
            <li key={item.application_id} className="review-card">
              <div className="review-main">
                <div className="review-title-row">
                  <div className="cell-title">
                    <strong>{item.job_title}</strong>
                    <span>{item.company}</span>
                  </div>
                  <div className="cell-badges">
                    <StatusBadge status={item.status} />
                    <span className="badge tone-gray" title="Submission is not confirmed; protected from automatic retry">
                      <ShieldCheck size={12} /> Protected
                    </span>
                  </div>
                </div>
                <div className="review-reason">
                  <ReasonSummary reason={item.failure_reason ?? item.skip_reason} />
                </div>
                <div className="review-meta">
                  <span className="chip chip-quiet">{REASON_CATEGORY_LABEL[itemCategory]}</span>
                  <span className="meta-item quiet">{fmtDateTime(item.created_at)}</span>
                  <span className="meta-item quiet">Job #{item.job_id}</span>
                </div>
              </div>
              <div className="review-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate("apply", { query: item.job_title })}
                >
                  Open in Apply Queue
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => navigate("applications", { statusFilter: "NEEDS_ATTENTION" })}
                >
                  History
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!loading && Math.max(total, unresolvedTotal ?? 0) > items.length && (
        <p className="result-line">
          Showing the {items.length} most recent of {Math.max(total, unresolvedTotal ?? 0)} unresolved items (server
          page limit).
        </p>
      )}
    </div>
  );
}
