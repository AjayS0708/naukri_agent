import { useEffect, useMemo, useState } from "react";
import { BellRing } from "lucide-react";
import { getNotifications } from "../services/api";
import type { Notification } from "../types/api";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { NotificationItem } from "../ui/NotificationItem";
import { PageHeader } from "../ui/PageHeader";
import { SearchFilterBar } from "../ui/SearchFilterBar";
import { statusLabel } from "../ui/status";

export function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getNotifications(100);
      setNotifications(data.notifications);
    } catch (err: unknown) {
      setError((err as { message?: string } | null)?.message ?? "Unable to load notifications.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const types = useMemo(
    () => Array.from(new Set(notifications.map((n) => n.notification_type))).sort(),
    [notifications],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return notifications.filter((n) => {
      if (typeFilter && n.notification_type !== typeFilter) return false;
      if (q && !n.title.toLowerCase().includes(q) && !n.message.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [notifications, query, typeFilter]);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Activity stream"
        title="Notifications"
        description={
          loading
            ? "Loading notifications…"
            : `${filtered.length} event${filtered.length === 1 ? "" : "s"} recorded by the agent`
        }
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
        }
      />

      <SearchFilterBar
        query={query}
        onQueryChange={setQuery}
        searchPlaceholder="Search title or message"
        searchLabel="Search notifications"
        onRefresh={() => void load()}
        refreshDisabled={loading}
      >
        <select
          className="select-field"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          aria-label="Filter by category"
        >
          <option value="">All categories</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {statusLabel(type)}
            </option>
          ))}
        </select>
      </SearchFilterBar>

      {loading ? (
        <LoadingState title="Loading notifications…" />
      ) : error ? (
        <ErrorState title="Unable to load notifications" message={error} action={{ label: "Retry", onClick: () => void load() }} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={BellRing}
          title={notifications.length === 0 ? "No notifications yet" : "No notifications match the filters"}
          message="Agent events — run outcomes, blockers, and state changes — will appear here."
        />
      ) : (
        <ul className="notification-list">
          {filtered.map((notification) => (
            <NotificationItem key={notification.id} notification={notification} />
          ))}
        </ul>
      )}
    </div>
  );
}
