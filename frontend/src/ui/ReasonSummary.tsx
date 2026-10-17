import { REASON_CATEGORY_LABEL, reasonCategory } from "./status";

interface ReasonSummaryProps {
  reason: string | null | undefined;
  fallback?: string;
  showCategory?: boolean;
}

export function ReasonSummary({ reason, fallback = "No reason recorded", showCategory = true }: ReasonSummaryProps) {
  if (!reason) {
    return <span className="reason-muted">{fallback}</span>;
  }
  const category = reasonCategory(reason);
  return (
    <span className="reason-line">
      {showCategory && <span className="chip">{REASON_CATEGORY_LABEL[category]}</span>}
      <span className="reason-text" title={reason}>
        {reason}
      </span>
    </span>
  );
}
