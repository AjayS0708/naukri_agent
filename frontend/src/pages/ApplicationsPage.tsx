import { useEffect, useMemo, useState } from "react";
import { getApplicationsList } from "../services/api";
import type { ApplicationListItem } from "../types/api";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { PageHeader } from "../ui/PageHeader";
import { Pagination } from "../ui/Pagination";
import { SearchFilterBar } from "../ui/SearchFilterBar";
import { StatusBadge } from "../ui/StatusBadge";
import { fmtDateTime, statusLabel } from "../ui/status";

const PAGE_SIZE = 25;
const FETCH_PAGE = 100;

type SortKey = "created_desc" | "created_asc" | "status" | "title";

interface ApplicationsPageProps {
  statusFilter: string | null;
  onStatusFilterChange: (status: string | null) => void;
}

export function ApplicationsPage({ statusFilter, onStatusFilterChange }: ApplicationsPageProps) {
  const [rows, setRows] = useState<ApplicationListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("created_desc");
  const [offset, setOffset] = useState(0);

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const collected: ApplicationListItem[] = [];
      let nextOffset = 0;
      let totalSeen = 0;
      for (;;) {
        const page = await getApplicationsList(null, FETCH_PAGE, nextOffset);
        if (collected.length === 0) totalSeen = page.total;
        collected.push(...page.applications);
        nextOffset += page.applications.length;
        if (page.applications.length === 0 || nextOffset >= page.total) break;
      }
      setRows(collected);
      setTotal(totalSeen || collected.length);
    } catch (err: unknown) {
      setError((err as { message?: string } | null)?.message ?? "Failed to load applications");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  useEffect(() => {
    setOffset(0);
  }, [query, statusFilter, sort]);

  const statuses = useMemo(
    () => Array.from(new Set(rows.map((row) => row.status))).sort(),
    [rows],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const result = rows.filter((row) => {
      if (statusFilter && row.status !== statusFilter) return false;
      if (
        q &&
        !row.job_title.toLowerCase().includes(q) &&
        !row.company.toLowerCase().includes(q) &&
        !(row.skip_reason ?? "").toLowerCase().includes(q) &&
        !(row.failure_reason ?? "").toLowerCase().includes(q)
      ) {
        return false;
      }
      return true;
    });
    const sorted = [...result];
    sorted.sort((a, b) => {
      switch (sort) {
        case "created_asc":
          return a.created_at.localeCompare(b.created_at);
        case "status":
          return a.status.localeCompare(b.status) || b.created_at.localeCompare(a.created_at);
        case "title":
          return a.job_title.localeCompare(b.job_title);
        default:
          return b.created_at.localeCompare(a.created_at);
      }
    });
    return sorted;
  }, [rows, query, statusFilter, sort]);

  const pageRows = filtered.slice(offset, offset + PAGE_SIZE);
  const hasFilters = Boolean(query || statusFilter);

  return (
    <div className="page">
      <PageHeader
        eyebrow="History"
        title={statusFilter ? statusLabel(statusFilter) : "Applications"}
        description={
          loading
            ? "Loading application history…"
            : `Showing ${filtered.length} of ${total} application record${total === 1 ? "" : "s"}` +
              (hasFilters ? " (filtered)" : "")
        }
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => void loadAll()} disabled={loading}>
            Refresh
          </button>
        }
      />

      <SearchFilterBar
        query={query}
        onQueryChange={setQuery}
        searchPlaceholder="Search title, company, or reason"
        searchLabel="Search applications"
        onRefresh={() => void loadAll()}
        refreshDisabled={loading}
      >
        <select
          className="select-field"
          value={statusFilter ?? ""}
          onChange={(e) => onStatusFilterChange(e.target.value || null)}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          {statuses.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>
        <select
          className="select-field"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          aria-label="Sort applications"
        >
          <option value="created_desc">Newest first</option>
          <option value="created_asc">Oldest first</option>
          <option value="status">Status</option>
          <option value="title">Title A–Z</option>
        </select>
        {hasFilters && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setQuery(""); onStatusFilterChange(null); }}>
            Clear filters
          </button>
        )}
      </SearchFilterBar>

      {loading ? (
        <LoadingState title="Loading applications…" />
      ) : error ? (
        <ErrorState
          title="Unable to load application history"
          message={error}
          action={{ label: "Retry", onClick: () => void loadAll() }}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={hasFilters ? "No applications match the current filters" : "No applications recorded yet"}
          message={hasFilters ? "Adjust or clear the filters to see more records." : "Run the agent to begin tracking applications."}
          action={hasFilters ? { label: "Clear filters", onClick: () => { setQuery(""); onStatusFilterChange(null); } } : undefined}
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
                    <th>Mode</th>
                    <th className="col-when">When</th>
                    <th>Reason / next action</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => (
                    <tr key={row.application_id}>
                      <td data-label="Job">
                        <div className="cell-title">
                          <strong title={row.job_title}>{row.job_title}</strong>
                          <span>{row.company}</span>
                        </div>
                      </td>
                      <td data-label="Status">
                        <div className="cell-badges">
                          <StatusBadge status={row.status} />
                          {row.needs_attention && <span className="badge tone-amber">Review</span>}
                          {row.is_dry_run && <span className="badge tone-gray">Dry run</span>}
                        </div>
                      </td>
                      <td data-label="Mode">
                        {row.application_method ? (
                          <span className="chip chip-quiet">
                            {row.application_method.replaceAll("_", " ").toLowerCase()}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td data-label="When" className="col-when">
                        {fmtDateTime(row.applied_at ?? row.created_at)}
                      </td>
                      <td data-label="Reason" className="cell-reason">
                        {row.skip_reason ?? row.failure_reason ? (
                          <span className="reason-text" title={row.skip_reason ?? row.failure_reason ?? undefined}>
                            {row.skip_reason ?? row.failure_reason}
                          </span>
                        ) : (
                          <span className="muted-text">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="table-footnote">
            Ambiguous submissions stay in <b>Needs attention</b> until confirmed; external applications are never
            shown as confirmed submissions.
          </div>
          <Pagination offset={offset} limit={PAGE_SIZE} total={filtered.length} onChange={setOffset} loading={loading} />
        </>
      )}
    </div>
  );
}
