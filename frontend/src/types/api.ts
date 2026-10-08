export type AgentState = "IDLE" | "RUNNING" | "SEARCHING" | "FILTERING" | "ANALYZING" | "APPLYING" | "PAUSED" | "AUTH_REQUIRED" | "SECURITY_REQUIRED" | "AI_QUOTA_EXHAUSTED" | "NEEDS_ATTENTION" | "STOPPED" | "CRITICAL_ERROR";
export interface HealthResponse { status: "ok"; service: string; version: string; agent_state: AgentState; }
export type ProfileStatus = "EMPTY" | "RESUME_UPLOADED" | "EXTRACTING" | "REVIEW_REQUIRED" | "CONFIRMED" | "ERROR";
export interface Education { degree?: string | null; field?: string | null; institution?: string | null; graduation_year?: number | null; }
export interface Experience { title?: string | null; company?: string | null; start_date?: string | null; end_date?: string | null; responsibilities: string[]; technologies: string[]; }
export interface Project { name: string; description?: string | null; technologies: string[]; }
export interface ProfileData { name?: string | null; education: Education[]; skills: string[]; programming_languages: string[]; frameworks: string[]; tools: string[]; projects: Project[]; certifications: string[]; experience: Experience[]; current_role?: string | null; location?: string | null; current_ctc?: string | null; notice_period?: string | null; }
export interface ProfileResponse { id?: number | null; status: ProfileStatus; confirmed: boolean; data?: ProfileData | null; resume_hash?: string | null; original_filename?: string | null; file_size?: number | null; }
export interface ResumeUploadResponse { profile_id: number; status: ProfileStatus; resume_hash: string; duplicate: boolean; }
export interface Notification {
  id: number;
  notification_type: string;
  severity: string;
  title: string;
  message: string;
  status: string;
  created_at: string;
}
export interface NotificationHistoryResponse { notifications: Notification[]; total: number; }

// ── Dashboard types (Checkpoint E1) ──────────────────────────────────────────

export interface DiscoverySummary {
  run_id: number | null;
  status: string | null;
  started_at: string | null;
  completed_at: string | null;
  jobs_discovered: number;
  new_jobs: number;
  pages_processed: number;
  total_runs: number;
}

export interface ApplicationCounts {
  total: number;
  applied: number;
  needs_attention: number;
  skipped: number;
  external_application: number;
  failed: number;
}

export interface DashboardProfileSummary {
  status: string;
  confirmed: boolean;
  original_filename: string | null;
}

export interface DashboardSummary {
  discovery: DiscoverySummary;
  applications: ApplicationCounts;
  profile: DashboardProfileSummary;
}

export interface RecentApplicationItem {
  application_id: number;
  job_id: number;
  job_title: string;
  company: string;
  status: string;
  application_method: string | null;
  applied_at: string | null;
  skip_reason: string | null;
  needs_attention: boolean;
  is_dry_run: boolean;
  created_at: string;
}

export interface RecentApplicationsResponse {
  applications: RecentApplicationItem[];
  total: number;
}

// ── Needs Attention types (Checkpoint E2) ─────────────────────────────────────

export interface NeedsAttentionItem {
  application_id: number;
  job_id: number;
  job_title: string;
  company: string;
  status: string;
  skip_reason: string | null;
  failure_reason: string | null;
  needs_attention: boolean;
  created_at: string;
}

export interface NeedsAttentionResponse {
  applications: NeedsAttentionItem[];
  total: number;
}

// ── Autonomous Cycle types (Checkpoint E3) ───────────────────────────────

export interface AutonomousCycleStartRequest {
  max_applications: number;
}

export interface AutonomousCycleStartResponse {
  run_id: number | null;
  status: string;
  max_applications: number;
  message: string;
}

export interface AutonomousCycleStatusResponse {
  status: string; // IDLE, RUNNING, COMPLETED, FAILED
  run_id: number | null;
  started_at: string | null;
  completed_at: string | null;
  max_applications: number | null;
  stats: Record<string, unknown>;
}

// ── Applications List types (Drill-down) ─────────────────────────────

export interface ApplicationListItem {
  application_id: number;
  job_id: number;
  job_title: string;
  company: string;
  status: string;
  application_method: string | null;
  applied_at: string | null;
  skip_reason: string | null;
  failure_reason: string | null;
  needs_attention: boolean;
  is_dry_run: boolean;
  created_at: string;
}

export interface ApplicationsListResponse {
  applications: ApplicationListItem[];
  total: number;
  status_filter: string | null;
}

// ── Jobs List types (Drill-down) ─────────────────────────────────────

export interface JobListItem {
  job_id: number;
  title: string;
  company: string;
  location: string | null;
  experience: string | null;
  platform: string;
  source: string | null;
  discovered_at: string;
  status: string;
}

export interface JobsListResponse {
  jobs: JobListItem[];
  total: number;
}
