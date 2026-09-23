import json
import logging
import sys
from datetime import UTC, datetime


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
    SENSITIVE_KEYS = {"api_key", "password", "token", "secret", "credential", "auth"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "level": record.levelname, "message": record.getMessage()}
        for field in ("component", "event", "error_category", "request_id", "job_id", "application_id"):
            if (value := getattr(record, field, None)) is not None:
                payload[field] = value

        # Redact sensitive information from extra fields
        for key, value in record.__dict__.items():
            if key not in {"name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs", "relativeCreated", "thread", "threadName", "processName", "process", "message", "asctime"}:
                if any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYS):
                    payload[key] = "[REDACTED]"
                else:
                    payload[key] = value

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
