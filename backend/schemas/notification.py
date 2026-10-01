from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NotificationType(StrEnum):
    CRITICAL_ERROR = "CRITICAL_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    SECURITY_CHALLENGE = "SECURITY_CHALLENGE"
    EXTERNAL_APPLICATION = "EXTERNAL_APPLICATION"
    EVENING_SUMMARY = "EVENING_SUMMARY"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_type: NotificationType
    severity: str
    title: str
    message: str
    channel: str
    status: NotificationStatus
    dedup_key: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sent_at: datetime | None = None


class NotificationHistoryResponse(BaseModel):
    notifications: list[NotificationSchema]
    total: int
