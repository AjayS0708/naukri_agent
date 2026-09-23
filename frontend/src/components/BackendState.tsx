import { AlertCircle, RefreshCw, Monitor } from "lucide-react";

interface BackendStateProps {
  status: "connected" | "local_offline" | "cloud_unavailable" | "checking";
  onRetry?: () => void;
}

export function BackendState({ status, onRetry }: BackendStateProps) {
  const states = {
    connected: {
      icon: null,
      title: "Connected",
      description: "Agent backend is running",
      className: "text-[var(--color-success)]"
    },
    checking: {
      icon: null,
      title: "Checking connection",
      description: "Verifying backend status",
      className: "text-[var(--color-text-secondary)]"
    },
    local_offline: {
      icon: Monitor,
      title: "Local agent offline",
      description: "Start the Naukri Agent on your Windows PC to connect",
      className: "text-[var(--color-warning)]"
    },
    cloud_unavailable: {
      icon: AlertCircle,
      title: "Cloud backend unavailable",
      description: "Backend service is temporarily unavailable",
      className: "text-[var(--color-error)]"
    }
  };

  const state = states[status];

  return (
    <div className="flex items-center gap-3 p-4 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg">
      {state.icon && <state.icon size={20} className={state.className} />}
      <div className="flex-1">
        <p className="text-sm font-medium text-[var(--color-text)]">{state.title}</p>
        <p className="text-xs text-[var(--color-text-secondary)]">{state.description}</p>
      </div>
      {status !== "connected" && onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-[var(--color-white)] bg-[var(--color-primary-blue)] rounded-md hover:bg-[var(--color-deep-blue)] transition-colors"
        >
          <RefreshCw size={14} />
          Retry
        </button>
      )}
    </div>
  );
}
