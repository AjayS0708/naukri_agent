import { createContext, useContext } from "react";

export type PageId =
  | "overview"
  | "jobs"
  | "apply"
  | "applications"
  | "attention"
  | "ai-queue"
  | "analytics"
  | "activity"
  | "notifications"
  | "profile"
  | "preferences";

export interface NavigateOptions {
  query?: string;
  statusFilter?: string | null;
}

interface ShellValue {
  navigate: (page: PageId, options?: NavigateOptions) => void;
  waitingForAnswer: boolean;
}

export const ShellContext = createContext<ShellValue>({
  navigate: () => undefined,
  waitingForAnswer: false,
});

export function useShell(): ShellValue {
  return useContext(ShellContext);
}
