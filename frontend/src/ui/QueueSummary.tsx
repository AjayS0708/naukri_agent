import type { ReactNode } from "react";

interface QueueStat {
  label: string;
  value: ReactNode;
  tone?: "blue" | "green" | "amber" | "red" | "gray" | "violet" | "orange";
}

interface QueueSummaryProps {
  stats: QueueStat[];
  ariaLabel?: string;
}

export function QueueSummary({ stats, ariaLabel }: QueueSummaryProps) {
  return (
    <div className="queue-summary" role="group" aria-label={ariaLabel ?? "Queue summary"}>
      {stats.map((stat) => (
        <div key={stat.label} className="queue-stat">
          <span className={`queue-stat-value tone-${stat.tone ?? "gray"}`}>{stat.value}</span>
          <span className="queue-stat-label">{stat.label}</span>
        </div>
      ))}
    </div>
  );
}
