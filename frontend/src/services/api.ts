import type { ApplicationsListResponse, AutonomousCycleStartRequest, AutonomousCycleStartResponse, AutonomousCycleStatusResponse, DashboardSummary, HealthResponse, JobsListResponse, NeedsAttentionResponse, NotificationHistoryResponse, ProfileData, ProfileResponse, RecentApplicationsResponse, ResumeUploadResponse } from "../types/api";

const LOCAL_API_BASE_URL = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 15_000;

export class ApiRequestError extends Error {}

export function resolveApiBaseUrl(value: string | undefined, isDevelopment: boolean): string | null {
  const configuredValue = value?.trim() || (isDevelopment ? LOCAL_API_BASE_URL : undefined);
  if (!configuredValue) return null;

  try {
    const url = new URL(configuredValue);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    const path = url.pathname.replace(/\/+$/, "");
    url.pathname = path.endsWith("/api") ? path : `${path}/api`;
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

export const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, import.meta.env.DEV);

function getApiUrl(path: string): string {
  if (!API_BASE_URL) {
    throw new ApiRequestError("The API endpoint is not configured.");
  }
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function messageForResponse(status: number): string {
  if (status >= 500) return "The service is temporarily unavailable. Please try again.";
  if (status === 401 || status === 403) return "You are not authorized to perform this action.";
  if (status >= 400) return "The request could not be completed. Please check your input and try again.";
  return "The request could not be completed.";
}

export async function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health");
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(getApiUrl(path), { ...init, signal: controller.signal });
    if (!response.ok) {
      const error = new ApiRequestError(messageForResponse(response.status));
      (error as any).status = response.status;
      throw error;
    }
    try {
      return await response.json() as T;
    } catch {
      throw new ApiRequestError("The service returned an invalid response. Please try again.");
    }
  } catch (error) {
    if (error instanceof ApiRequestError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiRequestError("The request timed out. Please try again.");
    }
    throw new ApiRequestError("Unable to reach the service. Please try again.");
  } finally {
    window.clearTimeout(timeout);
  }
}

export const getProfile = () => apiRequest<ProfileResponse>("/profile");
export const uploadResume = (file: File) => { const form = new FormData(); form.append("resume", file); return apiRequest<ResumeUploadResponse>("/profile/resume", { method: "POST", body: form }); };
export const updateProfile = (data: ProfileData) => apiRequest<ProfileResponse>("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data }) });
export const confirmProfile = () => apiRequest<ProfileResponse>("/profile/confirm", { method: "POST" });
export const getNotifications = () => apiRequest<NotificationHistoryResponse>("/notifications?limit=20");

// ── Dashboard endpoints (Checkpoint E1) ──────────────────────────────────────
export const getDashboardSummary = () => apiRequest<DashboardSummary>("/dashboard/summary");
export const getRecentApplications = (limit = 10) =>
  apiRequest<RecentApplicationsResponse>(`/dashboard/recent-applications?limit=${limit}`);

// ── Needs Attention endpoint (Checkpoint E2) ───────────────────────────────
export const getNeedsAttention = (limit = 10) =>
  apiRequest<NeedsAttentionResponse>(`/dashboard/needs-attention?limit=${limit}`);

// ── Autonomous Cycle endpoints (Checkpoint E3) ─────────────────────────────
export const startAutonomousCycle = (request: AutonomousCycleStartRequest) =>
  apiRequest<AutonomousCycleStartResponse>("/autonomous-cycle/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

export const getAutonomousCycleStatus = () =>
  apiRequest<AutonomousCycleStatusResponse>("/autonomous-cycle/status");

// ── Drill-down endpoints (Checkpoint E5) ─────────────────────────────
export const getApplicationsList = (status: string | null = null, limit = 50, offset = 0) => {
  const params = new URLSearchParams();
  if (status) params.append("status", status);
  params.append("limit", limit.toString());
  params.append("offset", offset.toString());
  return apiRequest<ApplicationsListResponse>(`/dashboard/applications?${params.toString()}`);
};

export const getJobsList = (limit = 50, offset = 0) => {
  const params = new URLSearchParams();
  params.append("limit", limit.toString());
  params.append("offset", offset.toString());
  return apiRequest<JobsListResponse>(`/dashboard/jobs?${params.toString()}`);
};
