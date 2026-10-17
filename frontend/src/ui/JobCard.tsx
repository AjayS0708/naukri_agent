import type { ReactNode } from "react";
import { Briefcase, MapPin } from "lucide-react";
import { fmtDate } from "./status";

export interface JobCardData {
  job_id: number;
  title: string;
  company: string;
  location?: string | null;
  experience?: string | null;
  discovered_at?: string | null;
}

interface JobCardProps {
  job: JobCardData;
  badges?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  selected?: boolean;
  dimmed?: boolean;
  checkbox?: ReactNode;
}

export function JobCard({ job, badges, meta, actions, selected, dimmed, checkbox }: JobCardProps) {
  return (
    <article
      className={`job-card${selected ? " selected" : ""}${dimmed ? " dimmed" : ""}`}
    >
      {checkbox && <div className="job-card-check">{checkbox}</div>}
      <div className="job-card-main">
        <div className="job-card-title-row">
          <div className="job-card-titles">
            <strong className="job-card-title" title={job.title}>
              {job.title}
            </strong>
            <span className="job-card-company">{job.company}</span>
          </div>
          {badges && <div className="job-card-badges">{badges}</div>}
        </div>
        <div className="job-card-meta">
          {job.location && (
            <span className="meta-item">
              <MapPin size={13} />
              {job.location}
            </span>
          )}
          {job.experience && (
            <span className="meta-item">
              <Briefcase size={13} />
              {job.experience}
            </span>
          )}
          {job.discovered_at && (
            <span className="meta-item quiet">Discovered {fmtDate(job.discovered_at)}</span>
          )}
          {meta}
        </div>
        {actions && <div className="job-card-actions">{actions}</div>}
      </div>
    </article>
  );
}
