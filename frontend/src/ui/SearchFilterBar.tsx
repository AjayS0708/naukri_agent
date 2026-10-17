import { RefreshCw, Search, X } from "lucide-react";
import type { ReactNode } from "react";

interface SearchFilterBarProps {
  query?: string;
  onQueryChange?: (value: string) => void;
  searchPlaceholder?: string;
  searchLabel?: string;
  onRefresh?: () => void;
  refreshDisabled?: boolean;
  children?: ReactNode;
}

export function SearchFilterBar({
  query,
  onQueryChange,
  searchPlaceholder = "Search…",
  searchLabel = "Search",
  onRefresh,
  refreshDisabled,
  children,
}: SearchFilterBarProps) {
  return (
    <div className="filter-bar">
      {onQueryChange && (
        <label className="search-field">
          <Search size={16} aria-hidden />
          <input
            type="search"
            value={query ?? ""}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchLabel}
          />
          {query && (
            <button
              type="button"
              className="search-clear"
              onClick={() => onQueryChange("")}
              aria-label="Clear search"
            >
              <X size={14} />
            </button>
          )}
        </label>
      )}
      {children}
      {onRefresh && (
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onRefresh}
          disabled={refreshDisabled}
        >
          <RefreshCw size={14} className={refreshDisabled ? "spin" : ""} />
          Refresh
        </button>
      )}
    </div>
  );
}
