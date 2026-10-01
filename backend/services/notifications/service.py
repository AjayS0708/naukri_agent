from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
import smtplib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.job import Job
from backend.models.notification import Notification
from backend.schemas.notification import (
    NotificationHistoryResponse,
    NotificationSchema,
    NotificationStatus,
    NotificationType,
)

logger = get_logger(__name__)


class SMTPEmailSender:
    """Small SMTP boundary that is straightforward to replace in tests."""

    def send(self, subject: str, body: str, recipient: str) -> None:
        settings = get_settings()
        if not settings.smtp_host or not settings.smtp_from:
            raise ValueError("SMTP notification configuration is incomplete")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.starttls()
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)


class NotificationService:
    def __init__(self, session: Session, sender: SMTPEmailSender | None = None):
        self.session = session
        self.sender = sender or SMTPEmailSender()
        self.settings = get_settings()

    def notify(
        self,
        notification_type: NotificationType,
        title: str,
        message: str,
        severity: str = "INFO",
        dedup_key: str | None = None,
    ) -> NotificationSchema:
        if dedup_key and self._already_created(dedup_key):
            existing = self.session.execute(
                select(Notification)
                .where(Notification.dedup_key == dedup_key)
                .order_by(Notification.created_at.desc())
            ).scalars().first()
            if existing:
                return self._to_schema(existing)

        notification = Notification(
            notification_type=notification_type.value,
            title=title,
            message=message,
            severity=severity,
            dedup_key=dedup_key,
            status=NotificationStatus.PENDING.value,
        )
        self.session.add(notification)
        self.session.commit()
        self.session.refresh(notification)

        if not self.settings.notifications_enabled:
            notification.status = NotificationStatus.FAILED.value
            notification.error_message = "Notifications are disabled"
        elif not self.settings.notification_email:
            notification.status = NotificationStatus.FAILED.value
            notification.error_message = "Notification recipient is not configured"
        else:
            try:
                self.sender.send(title, message, self.settings.notification_email)
                notification.status = NotificationStatus.SENT.value
                notification.sent_at = datetime.now(UTC)
            except Exception as exc:
                notification.status = NotificationStatus.FAILED.value
                notification.error_message = str(exc)[:512]
                logger.error(
                    "notification_delivery_failed",
                    extra={"notification_type": notification_type.value},
                )

        self.session.commit()
        self.session.refresh(notification)
        return self._to_schema(notification)

    def critical_error(self, message: str, dedup_key: str | None = None) -> NotificationSchema:
        return self.notify(NotificationType.CRITICAL_ERROR, "Critical agent error", message, "CRITICAL", dedup_key)

    def authentication_required(self, message: str) -> NotificationSchema:
        return self.notify(NotificationType.AUTHENTICATION_REQUIRED, "Authentication required", message, "WARNING")

    def security_challenge(self, message: str) -> NotificationSchema:
        return self.notify(NotificationType.SECURITY_CHALLENGE, "Security challenge detected", message, "WARNING")

    def external_application(self, job_title: str, external_url: str) -> NotificationSchema:
        return self.notify(
            NotificationType.EXTERNAL_APPLICATION,
            "External application encountered",
            f"{job_title}\nExternal URL: {external_url}",
            "INFO",
        )

    def send_evening_summary(self, now: datetime | None = None) -> NotificationSchema | None:
        now = now or datetime.now(UTC)
        try:
            local_now = now.astimezone(ZoneInfo(self.settings.notification_timezone))
        except ZoneInfoNotFoundError:
            logger.warning("notification_timezone_invalid", extra={"timezone": self.settings.notification_timezone})
            local_now = now

        if local_now.hour != self.settings.evening_summary_hour:
            return None

        day_key = local_now.date().isoformat()
        dedup_key = f"evening-summary:{day_key}"
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        end = start + timedelta(days=1)
        applications = self.session.execute(
            select(func.count(Application.id)).where(Application.created_at >= start, Application.created_at < end)
        ).scalar_one()
        discovered = self.session.execute(
            select(func.count(Job.id)).where(Job.created_at >= start, Job.created_at < end)
        ).scalar_one()
        analyzed = self.session.execute(
            select(func.count(JobAnalysisModel.id)).where(JobAnalysisModel.created_at >= start, JobAnalysisModel.created_at < end)
        ).scalar_one()
        message = (
            f"Date: {day_key}\n"
            f"Jobs discovered: {discovered}\n"
            f"Jobs analyzed: {analyzed}\n"
            f"Applications recorded: {applications}"
        )
        return self.notify(NotificationType.EVENING_SUMMARY, "Naukri Agent evening summary", message, "INFO", dedup_key)

    def history(self, limit: int = 100) -> NotificationHistoryResponse:
        rows = self.session.execute(
            select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        ).scalars().all()
        return NotificationHistoryResponse(
            notifications=[self._to_schema(row) for row in rows],
            total=len(rows),
        )

    def _already_created(self, dedup_key: str) -> bool:
        return self.session.execute(
            select(Notification.id).where(Notification.dedup_key == dedup_key).limit(1)
        ).scalar_one_or_none() is not None

    def _to_schema(self, notification: Notification) -> NotificationSchema:
        return NotificationSchema.model_validate(notification, from_attributes=True)
