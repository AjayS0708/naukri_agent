from datetime import UTC, datetime
from types import SimpleNamespace

from backend.models.notification import Notification
from backend.schemas.notification import NotificationStatus, NotificationType
from backend.services.notifications import NotificationService


class FakeSender:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.sent: list[tuple[str, str, str]] = []

    def send(self, subject: str, body: str, recipient: str) -> None:
        if self.error:
            raise self.error
        self.sent.append((subject, body, recipient))


def configured_service(db, sender=None) -> NotificationService:
    service = NotificationService(db, sender or FakeSender())
    service.settings = SimpleNamespace(
        notifications_enabled=True,
        notification_email="owner@example.test",
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_username="user",
        smtp_password="secret",
        smtp_from="agent@example.test",
        notification_timezone="UTC",
        evening_summary_hour=20,
    )
    return service


def test_event_notification_is_persisted_and_sent(db):
    sender = FakeSender()
    result = configured_service(db, sender).security_challenge("Human verification required")

    assert result.notification_type == NotificationType.SECURITY_CHALLENGE
    assert result.status == NotificationStatus.SENT
    assert sender.sent[0][2] == "owner@example.test"
    assert db.query(Notification).count() == 1


def test_delivery_failure_is_persisted_without_raising(db):
    result = configured_service(db, FakeSender(RuntimeError("SMTP unavailable"))).critical_error("worker failed")

    assert result.status == NotificationStatus.FAILED
    assert result.error_message == "SMTP unavailable"


def test_missing_configuration_is_persisted_without_sending(db):
    service = configured_service(db)
    service.settings.notification_email = None

    result = service.authentication_required("Sign in is required")

    assert result.status == NotificationStatus.FAILED
    assert result.error_message == "Notification recipient is not configured"


def test_evening_summary_is_deduplicated(db):
    sender = FakeSender()
    service = configured_service(db, sender)
    moment = datetime(2025, 1, 15, 20, 5, tzinfo=UTC)

    first = service.send_evening_summary(moment)
    second = service.send_evening_summary(moment)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert first.notification_type == NotificationType.EVENING_SUMMARY
    assert len(sender.sent) == 1


def test_summary_is_not_sent_outside_evening_window(db):
    service = configured_service(db)

    assert service.send_evening_summary(datetime(2025, 1, 15, 19, 59, tzinfo=UTC)) is None


def test_notification_history_endpoint(client, db):
    configured_service(db).critical_error("history entry")

    response = client.get("/api/notifications")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["notifications"][0]["notification_type"] == "CRITICAL_ERROR"
