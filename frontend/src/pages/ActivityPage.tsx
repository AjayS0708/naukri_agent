import { useEffect, useState } from "react";
import { getRecentApplications } from "../services/api";
import type { RecentApplicationItem } from "../types/api";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { PageHeader } from "../ui/PageHeader";
import { StatusBadge } from "../ui/StatusBadge";
import { fmtDateTime } from "../ui/status";

export function ActivityPage() {
  const [items, setItems] = useState<RecentApplicationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getRecentApplications(50);
      setItems(data.applications);
    } catch (err: unknown) {
      setError((err as { message?: string } | null)?.message ?? "Activity data unavailable.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Activity"
        title="Application History"
        description={loading ? "Loading activity…" : `Latest ${items.length} application events from the agent`}
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
        }
      />

      {loading ? (
        <LoadingState title="Loading activity…" />
      ) : error ? (
        <ErrorState title="Activity data unavailable" message={error} action={{ label: "Retry", onClick: () => void load() }} />
      ) : items.length === 0 ? (
        <EmptyState title="No activity recorded yet" message="Application events will appear here once the agent runs." />
      ) : (
        <ul className="activity-list">
          {items.map((app) => (
            <li key={app.application_id} className="activity-row">
              <div className="activity-main">
                <div className="cell-title">
                  <strong title={app.job_title}>{app.job_title}</strong>
                  <span>{app.company}</span>
                </div>
                <div className="cell-badges">
                  <StatusBadge status={app.status} />
                  {app.needs_attention && <span className="badge tone-amber">Review</span>}
                  {app.is_dry_run && <span className="badge tone-gray">Dry run</span>}
                  {app.job_confirmed && <span className="badge tone-green">Job confirmed</span>}
                </div>
              </div>
              <div className="activity-meta">
                <span className="meta-item quiet">{fmtDateTime(app.applied_at ?? app.created_at)}</span>
                {app.application_method && (
                  <span className="chip chip-quiet">
                    {app.application_method.replaceAll("_", " ").toLowerCase()}
                  </span>
                )}
                {app.skip_reason && (
                  <span className="reason-text" title={app.skip_reason}>
                    {app.skip_reason}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
