export type BadgeTone =
  | "blue"
  | "green"
  | "amber"
  | "red"
  | "gray"
  | "violet"
  | "orange";

export const STATUS_LABEL: Record<string, string> = {
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
  AI_ANALYZED: "AI analyzed",
  APPROVED_BY_RULES: "Approved",
};

const STATUS_TONE: Record<string, BadgeTone> = {
  APPLIED: "green",
  SUBMITTED: "blue",
  NEEDS_ATTENTION: "amber",
  SKIPPED: "gray",
  EXTERNAL_APPLICATION: "violet",
  FAILED: "red",
  APPLICATION_STARTED: "blue",
  PRE_APPLY: "blue",
  DISCOVERED: "blue",
  FILTERED: "gray",
  AI_ANALYZED: "blue",
  APPROVED_BY_RULES: "green",
  // AI queue statuses
  QUEUED: "blue",
  PROCESSING: "violet",
  COMPLETED: "green",
  RETRY_PENDING: "orange",
  QUOTA_BLOCKED: "orange",
  // Agent / run states
  IDLE: "gray",
  RUNNING: "green",
  STOPPING: "amber",
  CANCELLING: "amber",
    CANCELLED: "gray",
    LOGIN_REQUIRED: "red",
  AUTH_REQUIRED: "red",
  SECURITY_REQUIRED: "red",
  AI_QUOTA_EXHAUSTED: "orange",
  STOPPED: "red",
  CRITICAL_ERROR: "red",
  PAUSED: "amber",
  CONFIRMED: "green",
  REVIEW_REQUIRED: "amber",
  EMPTY: "gray",
  ERROR: "red",
  AVAILABLE: "green",
  NOT_CONFIGURED: "amber",
  AUTH_ERROR: "red",
  QUOTA_EXHAUSTED: "orange",
  UNAVAILABLE: "red",
  // Job statuses
  ACTIVE: "green",
  EXPIRED: "gray",
  EXTERNAL: "violet",
};

export function statusLabel(value: string): string {
  return STATUS_LABEL[value] ?? value.replaceAll("_", " ");
}

export function statusTone(value: string): BadgeTone {
  return STATUS_TONE[value] ?? "gray";
}

export function agentStateTone(value: string): BadgeTone {
  if (value === "RUNNING" || value === "SEARCHING" || value === "FILTERING" || value === "ANALYZING" || value === "APPLYING") return "green";
  if (value === "PAUSED" || value === "NEEDS_ATTENTION") return "amber";
  if (value === "IDLE") return "gray";
  return "red";
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  } catch {
    return iso;
  }
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const delta = Date.now() - then;
  if (delta < 0) return fmtDateTime(iso);
  const seconds = Math.floor(delta / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return fmtDate(iso);
}

export function fmtElapsed(from: unknown): string | null {
  if (typeof from !== "string" || !from) return null;
  const started = new Date(from).getTime();
  if (!Number.isFinite(started)) return null;
  const deltaMs = Date.now() - started;
  if (deltaMs < 0) return null;
  const totalSeconds = Math.floor(deltaMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) return `${minutes}m ${totalSeconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function exclusionLabel(reason: string | null): string {
  if (!reason) return "Not eligible";
  if (reason === "external_application") return "External application — not selectable here";
  if (reason === "application_history") return "Already applied — protected by application history";
  if (reason === "listing_expired") return "Listing expired — removed from the queue";
  if (reason === "profile_not_confirmed") return "Profile not confirmed";
  if (reason === "preferences_missing") return "Job preferences missing";
  if (reason === "user_skipped") return "Skipped by you — excluded from the queue";
  if (reason.startsWith("not_relevant:")) return `Not relevant — ${reason.slice("not_relevant:".length).trim()}`;
  if (reason.startsWith("hard_filtered:")) return `Filtered — ${reason.slice("hard_filtered:".length).trim()}`;
  return reason;
}

export type ReasonCategory = "screening" | "confirmation" | "navigation" | "form" | "other";

const CATEGORY_TESTS: Array<{ category: ReasonCategory; pattern: RegExp }> = [
  { category: "screening", pattern: /screening|question|answer|timed out - no answer/i },
  { category: "confirmation", pattern: /confirm|unconfirm|ambiguous|evidence|verification/i },
  { category: "navigation", pattern: /navigat|open(ed)? (the )?(job|page)|page load|timeout|stale|redirect/i },
  { category: "form", pattern: /form|field|input|submit|validation|captcha|security challenge/i },
];

export function reasonCategory(...texts: Array<string | null | undefined>): ReasonCategory {
  const joined = texts.filter(Boolean).join(" ");
  if (!joined.trim()) return "other";
  for (const test of CATEGORY_TESTS) {
    if (test.pattern.test(joined)) return test.category;
  }
  return "other";
}

export const REASON_CATEGORY_LABEL: Record<ReasonCategory, string> = {
  screening: "Screening questions",
  confirmation: "Confirmation uncertainty",
  navigation: "Navigation failures",
  form: "Form errors",
  other: "Other",
};

export function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}
