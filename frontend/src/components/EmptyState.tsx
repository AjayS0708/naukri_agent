import { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon?: any;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
      {Icon && <Icon size={48} strokeWidth={1.5} className="text-[var(--color-text-secondary)]" />}
      <div className="flex flex-col gap-2">
        <h3 className="text-base font-semibold text-[var(--color-text)]">{title}</h3>
        {description && <p className="text-sm text-[var(--color-text-secondary)]">{description}</p>}
      </div>
      {action && (
        <button
          onClick={action.onClick}
          className="mt-2 px-4 py-2 text-sm font-medium text-[var(--color-white)] bg-[var(--color-primary-blue)] rounded-md hover:bg-[var(--color-deep-blue)] transition-colors"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
