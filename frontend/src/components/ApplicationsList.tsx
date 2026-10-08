import { useEffect, useState } from "react";
import { ArrowLeft, Filter } from "lucide-react";
import { getApplicationsList } from "../services/api";
import type { ApplicationListItem } from "../types/api";

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

interface ApplicationsListProps {
  statusFilter?: string | null;
  onBack: () => void;
}

export function ApplicationsList({ statusFilter, onBack }: ApplicationsListProps) {
  const [applications, setApplications] = useState<ApplicationListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const fetchApplications = async () => {
      try {
        setLoading(true);
        const response = await getApplicationsList(statusFilter || null, 100, 0);
        setApplications(response.applications);
        setTotal(response.total);
        setError(null);
      } catch (err: any) {
        setError(err.message || "Failed to load applications");
      } finally {
        setLoading(false);
      }
    };

    fetchApplications();
  }, [statusFilter]);

  const statusLabel = statusFilter ? fmtStatus(statusFilter) : "All Applications";

  return (
    <section className="activity">
      <div className="section-header-with-back">
        <button onClick={onBack} className="back-button" aria-label="Back to dashboard">
          <ArrowLeft size={20} />
          Back
        </button>
        <div>
          <p className="eyebrow">APPLICATIONS</p>
          <h2>{statusLabel}</h2>
          <p className="page-description">
            {statusFilter
              ? `Showing ${applications.length} of ${total} applications with status "${statusLabel}"`
              : `Showing ${applications.length} of ${total} total applications`}
          </p>
        </div>
      </div>

      {loading ? (
        <p className="text-[var(--color-text-secondary)]">Loading applications…</p>
      ) : error ? (
        <p className="error-text">{error}</p>
      ) : applications.length === 0 ? (
        <p>No applications found{statusFilter ? ` with status "${statusLabel}"` : ""}.</p>
      ) : (
        <ul className="data-list">
          {applications.map((app) => (
            <li key={app.application_id} className="data-item">
              <div className="data-item-main">
                <strong>{app.job_title}</strong>
                <span className="data-item-company">at {app.company}</span>
              </div>
              <div className="data-item-meta">
                <span className={`status-badge status-${app.status.toLowerCase().replace(" ", "_")}`}>
                  {fmtStatus(app.status)}
                </span>
                {app.applied_at && (
                  <span className="data-item-date">Applied {fmtDate(app.applied_at)}</span>
                )}
                {!app.applied_at && (
                  <span className="data-item-date">Created {fmtDate(app.created_at)}</span>
                )}
                {app.application_method && (
                  <span className="data-item-method">{app.application_method.replace("_", " ")}</span>
                )}
                {app.is_dry_run && <span className="data-item-tag">dry run</span>}
                {app.needs_attention && <span className="data-item-tag warning">⚠ Needs attention</span>}
                {app.skip_reason && <span className="data-item-reason">{app.skip_reason}</span>}
                {app.failure_reason && <span className="data-item-reason error">{app.failure_reason}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
