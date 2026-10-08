import { useEffect, useState } from "react";
import { ArrowLeft, Globe, MapPin, Briefcase } from "lucide-react";
import { getJobsList } from "../services/api";
import type { JobListItem } from "../types/api";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

interface JobsListProps {
  onBack: () => void;
}

export function JobsList({ onBack }: JobsListProps) {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const fetchJobs = async () => {
      try {
        setLoading(true);
        const response = await getJobsList(100, 0);
        setJobs(response.jobs);
        setTotal(response.total);
        setError(null);
      } catch (err: any) {
        setError(err.message || "Failed to load jobs");
      } finally {
        setLoading(false);
      }
    };

    fetchJobs();
  }, []);

  return (
    <section className="activity">
      <div className="section-header-with-back">
        <button onClick={onBack} className="back-button" aria-label="Back to dashboard">
          <ArrowLeft size={20} />
          Back
        </button>
        <div>
          <p className="eyebrow">JOBS</p>
          <h2>Discovered Jobs</h2>
          <p className="page-description">
            Showing {jobs.length} of {total} total discovered jobs
          </p>
        </div>
      </div>

      {loading ? (
        <p className="text-[var(--color-text-secondary)]">Loading jobs…</p>
      ) : error ? (
        <p className="error-text">{error}</p>
      ) : jobs.length === 0 ? (
        <p>No jobs discovered yet. Run the agent to begin discovering jobs.</p>
      ) : (
        <ul className="data-list">
          {jobs.map((job) => (
            <li key={job.job_id} className="data-item">
              <div className="data-item-main">
                <strong>{job.title}</strong>
                <span className="data-item-company">at {job.company}</span>
              </div>
              <div className="data-item-meta">
                {job.location && (
                  <span className="data-item-detail">
                    <MapPin size={14} />
                    {job.location}
                  </span>
                )}
                {job.experience && (
                  <span className="data-item-detail">
                    <Briefcase size={14} />
                    {job.experience}
                  </span>
                )}
                <span className="data-item-detail">
                  <Globe size={14} />
                  {job.platform}
                </span>
                {job.source && (
                  <span className="data-item-source">Source: {job.source}</span>
                )}
                <span className="data-item-date">Discovered {fmtDate(job.discovered_at)}</span>
                <span className={`status-badge status-${job.status.toLowerCase().replace(" ", "_")}`}>
                  {job.status.replace(/_/g, " ")}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
