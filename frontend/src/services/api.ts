import type { HealthResponse, ProfileData, ProfileResponse, ResumeUploadResponse } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api";

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) throw new Error("Health check failed");
  return response.json() as Promise<HealthResponse>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: string } | null; throw new Error(body?.detail ?? "Request failed"); }
  return response.json() as Promise<T>;
}

export const getProfile = () => request<ProfileResponse>("/profile");
export const uploadResume = (file: File) => { const form = new FormData(); form.append("resume", file); return request<ResumeUploadResponse>("/profile/resume", { method: "POST", body: form }); };
export const updateProfile = (data: ProfileData) => request<ProfileResponse>("/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data }) });
export const confirmProfile = () => request<ProfileResponse>("/profile/confirm", { method: "POST" });
