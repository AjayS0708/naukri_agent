import type { BadgeTone } from "./status";
import { statusLabel, statusTone } from "./status";

interface StatusBadgeProps {
  status: string;
  label?: string;
  tone?: BadgeTone;
  title?: string;
  size?: "sm" | "md";
}

export function StatusBadge({ status, label, tone, title, size = "sm" }: StatusBadgeProps) {
  const resolvedTone = tone ?? statusTone(status);
  return (
    <span className={`badge tone-${resolvedTone} badge-${size}`} title={title}>
      {label ?? statusLabel(status)}
    </span>
  );
}
