import type { ReactNode } from "react";

interface ProgressPanelProps {
  eyebrow: string;
  stateLabel: string;
  stateTone?: "green" | "amber" | "red" | "gray" | "blue";
  description?: ReactNode;
  stats?: Array<{ label: string; value: ReactNode }>;
  footer?: ReactNode;
  actions?: ReactNode;
  variant?: "run" | "muted";
}

export function ProgressPanel({
  eyebrow,
  stateLabel,
  stateTone = "green",
  description,
  stats,
  footer,
  actions,
  variant = "run",
}: ProgressPanelProps) {
  return (
    <section className={`progress-panel variant-${variant}`} role="status">
      <div className="progress-head">
        <div className="progress-head-text">
          <p className="eyebrow">{eyebrow}</p>
          <strong className={`progress-state tone-${stateTone}`}>{stateLabel}</strong>
          {description && <p className="progress-description">{description}</p>}
        </div>
        {actions && <div className="progress-actions">{actions}</div>}
      </div>
      {stats && stats.length > 0 && (
        <dl className="progress-stats">
          {stats.map((stat) => (
            <div key={stat.label} className="progress-stat">
              <dt>{stat.label}</dt>
              <dd>{stat.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {footer && <div className="progress-footer">{footer}</div>}
    </section>
  );
}
