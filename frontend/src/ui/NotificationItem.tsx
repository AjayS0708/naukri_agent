import { useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import type { Notification } from "../types/api";
import { fmtDateTime, statusLabel } from "./status";

function severityTone(severity: string): string {
  const value = severity.toLowerCase();
  if (value.includes("error") || value.includes("critical")) return "red";
  if (value.includes("warn")) return "amber";
  if (value.includes("success")) return "green";
  return "blue";
}

/** Wraps long URLs / raw tokens so they never blow out the row layout. */
function renderMessage(message: string) {
  const parts = message.split(/(https?:\/\/\S+)/g);
  return parts.map((part, index) =>
    /^https?:\/\//.test(part) ? (
      <span key={index} className="url-text" title={part}>
        {part.length > 48 ? `${part.slice(0, 48)}…` : part}
      </span>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}

interface NotificationItemProps {
  notification: Notification;
}

export function NotificationItem({ notification }: NotificationItemProps) {
  const [expanded, setExpanded] = useState(false);
  const needsExpand = notification.message.length > 140 || /https?:\/\//.test(notification.message);
  const tone = severityTone(notification.severity);

  return (
    <li className={`notification-item tone-${tone}`}>
      <span className={`notif-dot tone-${tone}`} aria-hidden />
      <div className="notif-main">
        <div className="notif-topline">
          <strong className="notif-title">{notification.title}</strong>
          <span className="notif-meta">
            <span className="chip chip-quiet">{statusLabel(notification.notification_type)}</span>
            <time dateTime={notification.created_at} title={fmtDateTime(notification.created_at)}>
              {fmtDateTime(notification.created_at)}
            </time>
          </span>
        </div>
        <p className={`notif-message ${expanded ? "expanded" : ""}`}>
          {renderMessage(notification.message)}
        </p>
        {needsExpand && (
          <button
            type="button"
            className="link-button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
          >
            {expanded ? (
              <>
                Less <ChevronUp size={13} />
              </>
            ) : (
              <>
                More <ChevronDown size={13} />
              </>
            )}
          </button>
        )}
      </div>
      <ExternalLink size={14} className="notif-chevron" aria-hidden />
    </li>
  );
}
