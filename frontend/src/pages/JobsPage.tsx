import { useEffect, useMemo, useState } from "react";
import { getManualEligible } from "../services/api";
import type { ManualApplyEligibleItem } from "../types/api";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { PageHeader } from "../ui/PageHeader";
import { Pagination } from "../ui/Pagination";
import { SearchFilterBar } from "../ui/SearchFilterBar";
import { StatusBadge } from "../ui/StatusBadge";
import { exclusionLabel, fmtDateTime, statusLabel } from "../ui/status";

const PAGE_SIZE = 25;
const FETCH_PAGE = 600;

type SortKey = "discovered_desc" | "discovered_asc" | "title_asc" | "company_asc" | "status";

interface JobsPageProps {
  initialQuery?: string;
}

export function JobsPage({ initialQuery }: JobsPageProps) {
  const [rows, setRows] = useState<ManualApplyEligibleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [eligibleTotal, setEligibleTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState(initialQuery ?? "");
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [locationFilter, setLocationFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sort, setSort] = useState<SortKey>("discovered_desc");
  const [offset, setOffset] = useState(0);

  const loadAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const collected: ManualApplyEligibleItem[] = [];
      let nextOffset = 0;
      let totalSeen = 0;
      let eligibleCount = 0;
      for (;;) {
        const page = await getManualEligible(FETCH_PAGE, nextOffset, false, "");
        if (collected.length === 0) {
          totalSeen = page.total;
          eligibleCount = page.eligible_count;
        }
        collected.push(...page.items);
        nextOffset += page.items.length;
        if (page.items.length === 0 || nextOffset >= page.total || collected.length >= 2000) break;
      }
      setRows(collected);
      setTotal(totalSeen || collected.length);
      setEligibleTotal(eligibleCount);
    } catch (err: unknown) {
      setError((err as { message?: string } | null)?.message ?? "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  useEffect(() => {
    setOffset(0);
  }, [query, eligibleOnly, locationFilter, modeFilter, statusFilter, sort]);

  const locations = useMemo(
    () => Array.from(new Set(rows.map((row) => row.location).filter((v): v is string => Boolean(v)))).sort(),
    [rows],
  );
  const modes = useMemo(
    () => Array.from(new Set(rows.map((row) => row.application_mode).filter((v): v is string => Boolean(v)))).sort(),
    [rows],
  );
  const statuses = useMemo(
    () =>
      Array.from(
        new Set(rows.map((row) => row.application_status).filter((v): v is string => Boolean(v))),
      ).sort(),
    [rows],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const result = rows.filter((row) => {
      if (q && !row.title.toLowerCase().includes(q) && !row.company.toLowerCase().includes(q)) return false;
      if (eligibleOnly && !row.eligible) return false;
      if (locationFilter && row.location !== locationFilter) return false;
      if (modeFilter && row.application_mode !== modeFilter) return false;
      if (statusFilter && row.application_status !== statusFilter) return false;
      return true;
    });
    const sorted = [...result];
    sorted.sort((a, b) => {
      switch (sort) {
        case "title_asc":
          return a.title.localeCompare(b.title);
        case "company_asc":
          return a.company.localeCompare(b.company);
        case "discovered_asc":
          return (a.discovered_at ?? "").localeCompare(b.discovered_at ?? "");
        case "status":
          return (a.application_status ?? "").localeCompare(b.application_status ?? "");
        default:
          return (b.discovered_at ?? "").localeCompare(a.discovered_at ?? "");
      }
    });
    return sorted;
  }, [rows, query, eligibleOnly, locationFilter, modeFilter, statusFilter, sort]);

  const pageRows = filtered.slice(offset, offset + PAGE_SIZE);
  const hasFilters =
    Boolean(query || locationFilter || modeFilter || statusFilter) || eligibleOnly;

  const clearFilters = () => {
    setQuery("");
    setEligibleOnly(false);
    setLocationFilter("");
    setModeFilter("");
    setStatusFilter("");
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="Discovery"
        title="Jobs"
        description={
          loading
            ? "Loading discovered jobs…"
            : `${filtered.length === rows.length ? total : filtered.length} job${(filtered.length === rows.length ? total : filtered.length) === 1 ? "" : "s"}${
                filtered.length === rows.length ? " discovered" : " matching filters"
              } · ${eligibleTotal} eligible · salary is not exposed by the jobs API`
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
        searchPlaceholder="Search title or company"
        searchLabel="Search jobs by title or company"
        onRefresh={() => void loadAll()}
        refreshDisabled={loading}
      >
        <label className="toggle-field">
          <input type="checkbox" checked={eligibleOnly} onChange={(e) => setEligibleOnly(e.target.checked)} />
          Eligible only
        </label>
        <select
          className="select-field"
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value)}
          aria-label="Filter by location"
        >
          <option value="">All locations</option>
          {locations.map((location) => (
            <option key={location} value={location}>
              {location}
            </option>
          ))}
        </select>
        <select
          className="select-field"
          value={modeFilter}
          onChange={(e) => setModeFilter(e.target.value)}
          aria-label="Filter by application mode"
        >
          <option value="">All modes</option>
          {modes.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
        <select
          className="select-field"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by application status"
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
          aria-label="Sort jobs"
        >
          <option value="discovered_desc">Newest first</option>
          <option value="discovered_asc">Oldest first</option>
          <option value="title_asc">Title A–Z</option>
          <option value="company_asc">Company A–Z</option>
          <option value="status">Application status</option>
        </select>
        {hasFilters && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </SearchFilterBar>

      {loading ? (
        <LoadingState title="Loading discovered jobs…" />
      ) : error ? (
        <ErrorState title="Unable to load jobs" message={error} action={{ label: "Retry", onClick: () => void loadAll() }} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={hasFilters ? "No jobs match the current filters" : "No jobs discovered yet"}
          message={hasFilters ? "Adjust or clear the filters to see more jobs." : "Run the agent to begin discovering jobs."}
          action={hasFilters ? { label: "Clear filters", onClick: clearFilters } : undefined}
        />
      ) : (
        <>
          <div className="table-card">
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Location</th>
                    <th>Experience</th>
                    <th>Mode</th>
                    <th>Discovered</th>
                    <th>Status</th>
                    <th>Eligibility</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => (
                    <tr key={row.job_id}>
                      <td data-label="Job">
                        <div className="cell-title">
                          <strong title={row.title}>{row.title}</strong>
                          <span>{row.company}</span>
                        </div>
                      </td>
                      <td data-label="Location">{row.location ?? "—"}</td>
                      <td data-label="Experience">{row.experience ?? "—"}</td>
                      <td data-label="Mode">
                        {row.application_mode ? (
                          <span className="chip chip-quiet">
                            {row.application_mode.replaceAll("_", " ").toLowerCase()}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td data-label="Discovered">{fmtDateTime(row.discovered_at)}</td>
                      <td data-label="Status">
                        {row.application_status ? (
                          <StatusBadge
                            status={row.application_status}
                            label={
                              row.application_status === "SKIPPED" &&
                              (row.skip_reason ?? "").startsWith("USER_SKIPPED")
                                ? "Skipped by you"
                                : undefined
                            }
                            title={row.skip_reason ?? undefined}
                          />
                        ) : (
                          <span className="muted-text">—</span>
                        )}
                      </td>
                      <td data-label="Eligibility">
                        {row.eligible ? (
                          <span className="badge tone-green">Eligible</span>
                        ) : (
                          <span className="badge tone-red" title={row.exclusion_reason ?? undefined}>
                            {exclusionLabel(row.exclusion_reason)}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <Pagination offset={offset} limit={PAGE_SIZE} total={filtered.length} onChange={setOffset} />
        </>
      )}
    </div>
  );
}
