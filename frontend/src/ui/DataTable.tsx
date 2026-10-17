import { Fragment } from "react";
import type { ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  width?: string;
  render: (row: T) => ReactNode;
  mobileLabel?: string;
  align?: "start" | "end";
}

interface DataTableProps<T> {
  columns: Array<DataTableColumn<T>>;
  rows: T[];
  rowKey: (row: T) => string | number;
  expandable?: (row: T) => ReactNode;
  expandedKey?: string | number | null;
  onToggleExpand?: (key: string | number) => void;
  emptyMessage?: ReactNode;
  rowClassName?: (row: T) => string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  expandable,
  expandedKey,
  onToggleExpand,
  emptyMessage,
  rowClassName,
}: DataTableProps<T>) {
  if (rows.length === 0 && emptyMessage) {
    return <div className="table-empty">{emptyMessage}</div>;
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {expandable && <th className="col-expand" aria-label="Expand" />}
            {columns.map((column) => (
              <th
                key={column.key}
                style={column.width ? { width: column.width } : undefined}
                className={column.align === "end" ? "align-end" : ""}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const isExpanded = expandedKey === key;
            return (
              <Fragment key={key}>
                <tr className={rowClassName?.(row)}>
                  {expandable && (
                    <td className="col-expand">
                      <button
                        type="button"
                        className="expand-btn"
                        onClick={() => onToggleExpand?.(key)}
                        aria-label={isExpanded ? "Collapse details" : "Expand details"}
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </button>
                    </td>
                  )}
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      data-label={column.mobileLabel ?? (typeof column.header === "string" ? column.header : undefined)}
                      className={column.align === "end" ? "align-end" : ""}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
                {expandable && isExpanded && (
                  <tr className="expand-row">
                    <td colSpan={columns.length + 1}>
                      <div className="expand-content">{expandable(row)}</div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
