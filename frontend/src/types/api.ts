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
  max_applications?: number | null;
}

export interface AutonomousCycleStartResponse {
  run_id: number | null;
  run_token?: string | null;
  status: string;
  max_applications: number | null;
  message: string;
}

export interface AutonomousCycleStopRequest {
  run_token?: string | null;
}

export interface AutonomousCycleStopResponse {
  cancel_requested: boolean;
  active_state: string;
  message: string;
  run_id: number | null;
  run_token: string | null;
  status: string | null;
}

export interface AutonomousCycleStatusResponse {
  active_state: "IDLE" | "RUNNING";
  lock_held: boolean;
  active_run: AutonomousCycleRun | null;
  last_run: AutonomousCycleRun | null;
}

export interface AutonomousCycleRun {
  run_id: number | null;
  run_token?: string | null;
  status: "RUNNING" | "CANCELLING" | "COMPLETED" | "FAILED" | "CANCELLED" | "LOGIN_REQUIRED";
  // E5-R21: WAITING_FOR_USER while the run is blocked on a screening answer.
  display_status?: string | null;
  started_at: string | null;
  completed_at: string | null;
  max_applications: number | null;
  stats: Record<string, unknown>;
  error: string | null;
  cancel_requested?: boolean;
  // E5-R21: live multi-job progress counters + current job/step.
  progress?: CycleProgress | null;
  waiting_for_user?: boolean;
  waiting_for_question_id?: number | null;
}

// ── E5-R21: multi-job observability + screening-answer memory ────────────────

export interface CycleProgress {
  candidates_total?: number;
  processed?: number;
  applied?: number;
  submitted_unconfirmed?: number;
  skipped?: number;
  external?: number;
  needs_attention?: number;
  failed?: number;
  remaining?: number;
  current_job_id?: number | null;
  current_job_title?: string | null;
  current_step?: string | null;
  waiting_for_user?: boolean;
  current_question?: string | null;
  pending_question_id?: number | null;
  // E5-R23: discovery-sweep progress (set during the discovery phase, before
  // any application candidates exist).
  phase?: string | null;
  search_index?: number;
  search_total?: number;
  current_search?: string | null;
  jobs_new?: number;
  jobs_duplicate?: number;
  status?: string | null;
  // E5-R29: heartbeat stamped server-side on every progress write so the UI
  // can detect a running-but-stalled cycle (no heartbeat movement).
  progress_updated_at?: string | null;
}

export interface PendingQuestion {
  found: boolean;
  pending_question_id?: number | null;
  run_token?: string | null;
  question_text?: string | null;
  question_type?: string | null;
  options?: string[] | null;
  employer?: string | null;
  job_title?: string | null;
  job_id?: number | null;
  application_id?: number | null;
  status?: string | null;
  created_at?: string | null;
}

export interface AnswerQuestionRequest {
  pending_question_id: number;
  run_token?: string | null;
  answer?: string | null;
  skip?: boolean;
  scope?: "JOB" | "EMPLOYER" | "GLOBAL";
  remember?: boolean;
  allow_global_reuse?: boolean;
}

export interface AnswerQuestionResponse {
  status: "ANSWERED" | "SKIPPED";
  pending_question_id: number;
  saved_to_memory: boolean;
  answer_scope?: string | null;
  message: string;
}

export interface ScreeningAnswer {
  id: number;
  question_text: string;
  answer: string;
  answer_type: string;
  scope: string;
  employer?: string | null;
  job_id?: number | null;
  source: string;
  verification_status: string;
  context_sensitive: boolean;
  reuse_count: number;
  last_used_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
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

// ── Manual Apply Queue types (Checkpoint E5-R29) ─────────────────────────────

export interface ManualApplyEligibleItem {
  job_id: number;
  title: string;
  company: string;
  location: string | null;
  experience: string | null;
  application_mode: string | null;
  discovered_at: string | null;
  application_status: string | null;
  eligible: boolean;
  exclusion_reason: string | null;
}

export interface ManualApplyEligibleResponse {
  items: ManualApplyEligibleItem[];
  total: number;
  eligible_count: number;
  profile_confirmed: boolean;
  preferences_present: boolean;
}

export interface ManualApplyStartRequest {
  job_ids: number[];
  dry_run?: boolean;
}

export interface ManualApplyStartResponse {
  status: string;
  run_token: string | null;
  accepted_job_ids: number[];
  dropped_job_ids: number[];
  message: string;
}

export interface ManualApplyStopRequest {
  run_token?: string | null;
}

export interface ManualApplyStopResponse {
  cancel_requested: boolean;
  active_state: string;
  message: string;
}

export interface ManualApplyRunSummary {
  run_token: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  stats: Record<string, unknown>;
  error: string | null;
  progress: Record<string, unknown> | null;
  waiting_for_user: boolean;
  waiting_for_question_id: number | null;
  cancel_requested: boolean;
}

export interface ManualApplyStatusResponse {
  active_state: string;
  lock_held: boolean;
  active_run: ManualApplyRunSummary | null;
  last_manual_run: ManualApplyRunSummary | null;
  pending_question_available: boolean;
}
