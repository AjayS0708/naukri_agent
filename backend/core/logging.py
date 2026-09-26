import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any


REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = ("api_key", "apikey", "password", "passwd", "token", "secret", "credential", "authorization", "cookie", "session", "auth")
RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
URL_CREDENTIALS_PATTERN = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/@:]+(?::[^\s/@]*)?@", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"\b(bearer\s+)[^\s,;]+", re.IGNORECASE)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"\b(api[_-]?key|password|passwd|token|secret|credential|authorization|cookie|session|auth)\b(\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
QUERY_SECRET_PATTERN = re.compile(
    r"([?&](?:api[_-]?key|password|passwd|token|secret|credential|authorization|cookie|session|auth)=)[^&#\s]+",
    re.IGNORECASE,
)


def _is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and any(part in key.lower() for part in SENSITIVE_KEY_PARTS)


def _sanitize_text(value: str) -> str:
    """Redact credentials appearing in free-form logging strings."""
    value = URL_CREDENTIALS_PATTERN.sub(r"\1" + REDACTED + "@", value)
    value = BEARER_PATTERN.sub(r"\1" + REDACTED, value)
    value = QUERY_SECRET_PATTERN.sub(r"\1" + REDACTED, value)
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2" + REDACTED, value)


def sanitize_log_value(value: Any, key: object | None = None) -> Any:
    """Recursively sanitize arbitrary logging values without mutating them."""
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, BaseException):
        return {"exception_type": type(value).__name__}
    if isinstance(value, dict):
        return {str(item_key): sanitize_log_value(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [sanitize_log_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_log_value(item) for item in value]
    if isinstance(value, set):
        return [sanitize_log_value(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "level": record.levelname, "message": record.getMessage()}
        for field in ("component", "event", "error_category", "request_id", "job_id", "application_id"):
            if (value := getattr(record, field, None)) is not None:
                payload[field] = value
        return json.dumps(payload, default=str)


class SafeJsonFormatter(logging.Formatter):
    """
    Production-safe formatter that redacts sensitive information.
    Never logs API keys, passwords, or sensitive credentials.
    """
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": _sanitize_text(record.getMessage()),
        }
        for field in ("component", "event", "error_category", "request_id", "job_id", "application_id"):
            if (value := getattr(record, field, None)) is not None:
                payload[field] = sanitize_log_value(value, field)

        # LogRecord includes arbitrary ``extra`` data. Sanitize all of it,
        # including nested data and exception objects, before serialization.
        for key, value in record.__dict__.items():
            if key not in RECORD_FIELDS:
                payload[key] = sanitize_log_value(value, key)

        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__

        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def configure_production_logging(level: str) -> None:
    """Configure production-safe logging with sensitive information redaction."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SafeJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
