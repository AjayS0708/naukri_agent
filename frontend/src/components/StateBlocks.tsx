import type { LucideIcon } from "lucide-react";
import { AlertCircle, Inbox, LoaderCircle, RefreshCw } from "lucide-react";

interface StateProps {
  icon?: LucideIcon;
  title: string;
  message?: string;
  action?: { label: string; onClick: () => void };
  compact?: boolean;
}

export function LoadingState({ title = "Loading…", message, compact }: StateProps) {
  return (
    <div className={`state-block${compact ? " compact" : ""}`} role="status" aria-live="polite">
      <LoaderCircle className="state-icon spin" size={24} />
      <div className="state-text">
        <h3>{title}</h3>
        {message && <p>{message}</p>}
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, message, action, compact }: StateProps) {
  return (
    <div className={`state-block${compact ? " compact" : ""}`}>
      <Icon className="state-icon muted" size={24} strokeWidth={1.6} />
      <div className="state-text">
        <h3>{title}</h3>
        {message && <p>{message}</p>}
      </div>
      {action && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", message, action, compact }: StateProps) {
  return (
    <div className={`state-block error${compact ? " compact" : ""}`} role="alert">
      <AlertCircle className="state-icon error" size={24} />
      <div className="state-text">
        <h3>{title}</h3>
        {message && <p>{message}</p>}
      </div>
      {action && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={action.onClick}>
          <RefreshCw size={14} />
          {action.label}
        </button>
      )}
    </div>
  );
}
