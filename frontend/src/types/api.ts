export type AgentState = "IDLE" | "RUNNING" | "SEARCHING" | "FILTERING" | "ANALYZING" | "APPLYING" | "PAUSED" | "AUTH_REQUIRED" | "SECURITY_REQUIRED" | "AI_QUOTA_EXHAUSTED" | "NEEDS_ATTENTION" | "STOPPED" | "CRITICAL_ERROR";
export interface HealthResponse { status: "ok"; service: string; version: string; agent_state: AgentState; }
export type ProfileStatus = "EMPTY" | "RESUME_UPLOADED" | "EXTRACTING" | "REVIEW_REQUIRED" | "CONFIRMED" | "ERROR";
export interface ProfileData { name?: string | null; education: unknown[]; skills: string[]; programming_languages: string[]; frameworks: string[]; tools: string[]; projects: unknown[]; certifications: string[]; experience: unknown[]; current_role?: string | null; location?: string | null; current_ctc?: string | null; notice_period?: string | null; }
export interface ProfileResponse { id?: number | null; status: ProfileStatus; confirmed: boolean; data?: ProfileData | null; resume_hash?: string | null; original_filename?: string | null; }
export interface ResumeUploadResponse { profile_id: number; status: ProfileStatus; resume_hash: string; duplicate: boolean; }
