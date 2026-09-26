import json
import logging
import sys

from backend.core.logging import REDACTED, SafeJsonFormatter


def _format_record(message: str, *args: object, **extras: object) -> dict[str, object]:
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )
    for key, value in extras.items():
        setattr(record, key, value)
    return json.loads(SafeJsonFormatter().format(record))


def test_safe_json_formatter_redacts_sensitive_extra_keys() -> None:
    payload = _format_record("request failed", api_key="AIza-not-for-logs", password="not-for-logs")

    assert payload["api_key"] == REDACTED
    assert payload["password"] == REDACTED
    assert "AIza-not-for-logs" not in json.dumps(payload)


def test_safe_json_formatter_redacts_credentials_in_message_and_extra_strings() -> None:
    database_url = "postgresql+psycopg://user:super-secret@db.example.com/naukri"
    payload = _format_record("Database connection failed: %s", database_url, error=database_url)

    rendered = json.dumps(payload)
    assert "super-secret" not in rendered
    assert "user:" not in rendered
    assert "postgresql+psycopg://[REDACTED]@db.example.com/naukri" in rendered


def test_safe_json_formatter_redacts_nested_values_and_auth_headers() -> None:
    payload = _format_record(
        "Failure Authorization: Bearer top-secret-token",
        details={
            "connection": "postgresql://user:password@host/naukri",
            "headers": {"Authorization": "Bearer top-secret-token"},
            "items": [{"session_data": "browser-cookie"}],
        },
    )

    rendered = json.dumps(payload)
    for secret in ("password", "top-secret-token", "browser-cookie"):
        assert secret not in rendered
    assert payload["details"]["headers"]["Authorization"] == REDACTED


def test_safe_json_formatter_preserves_normal_values_and_sqlite_urls() -> None:
    sqlite_url = "sqlite:///./data/naukri_agent.db"
    payload = _format_record("Normal event", details={"database": sqlite_url, "attempt": 2})

    assert payload["message"] == "Normal event"
    assert payload["details"] == {"database": sqlite_url, "attempt": 2}


def test_safe_json_formatter_never_serializes_exception_messages_or_args() -> None:
    try:
        raise RuntimeError("postgresql://user:password@host/naukri")
    except RuntimeError:
        payload = _format_record("operation failed", exc_info=sys.exc_info())

    rendered = json.dumps(payload)
    assert "password" not in rendered
    assert payload["exception_type"] == "RuntimeError"
