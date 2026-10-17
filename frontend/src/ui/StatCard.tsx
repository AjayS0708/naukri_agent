import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "blue" | "green" | "amber" | "red" | "gray" | "violet";
  onClick?: () => void;
}

export function StatCard({ icon: Icon, label, value, sub, tone = "blue", onClick }: StatCardProps) {
  const body = (
    <>
      <div className={`stat-icon tone-${tone}`}>
        <Icon size={18} strokeWidth={2} />
      </div>
      <div className="stat-text">
        <p className="stat-label">{label}</p>
        <strong className="stat-value">{value}</strong>
        {sub && <span className="stat-sub">{sub}</span>}
      </div>
    </>
  );
  if (onClick) {
    return (
      <button type="button" className="stat-card clickable" onClick={onClick}>
        {body}
      </button>
    );
  }
  return <div className="stat-card">{body}</div>;
}
