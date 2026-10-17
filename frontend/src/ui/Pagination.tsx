import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
  loading?: boolean;
}

export function Pagination({ offset, limit, total, onChange, loading }: PaginationProps) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="pagination-info">
        {from}–{to} of {total}
      </span>
      <div className="pagination-buttons">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0 || loading}
        >
          <ChevronLeft size={14} />
          Previous
        </button>
        <span className="pagination-page">
          Page {page} of {pages}
        </span>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => onChange(offset + limit)}
          disabled={to >= total || loading}
        >
          Next
          <ChevronRight size={14} />
        </button>
      </div>
    </nav>
  );
}
