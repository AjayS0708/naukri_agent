import type { HealthResponse, ProfileData, ProfileResponse, ResumeUploadResponse } from "../types/api";

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
    if (!response.ok) throw new ApiRequestError(messageForResponse(response.status));
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
