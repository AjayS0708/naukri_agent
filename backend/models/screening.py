"""E5-R21: screening-answer memory and pending human-in-the-loop questions.

``ScreeningAnswer`` is the persistent, scoped, reusable answer store for
screening questions (approved by the user or derived from verified profile
data). ``PendingQuestion`` records a question the agent paused on, linked to
the active run and job attempt, until the user answers or skips.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


# Scopes: GLOBAL (all jobs), EMPLOYER (one employer), JOB (one job only).
ANSWER_SCOPES = ("GLOBAL", "EMPLOYER", "JOB")
# Sources: USER (approved through the human-in-the-loop flow), PROFILE
# (derived from confirmed profile data).
ANSWER_SOURCES = ("USER", "PROFILE")
# Answer types: text / boolean / single choice / multiple choice.
ANSWER_TYPES = ("TEXT", "BOOLEAN", "SINGLE_CHOICE", "MULTIPLE_CHOICE")
# Pending-question lifecycle.
PENDING_STATUSES = ("WAITING", "ANSWERED", "SKIPPED", "CANCELLED", "EXPIRED")


class ScreeningAnswer(Base):
    """A reusable, scoped answer to a screening question."""

    __tablename__ = "screening_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Normalized question fingerprint (lowercased, punctuation-stripped) and
    # the original question text kept verbatim for audit.
    question_fingerprint: Mapped[str] = mapped_column(String(512), index=True)
    question_text: Mapped[str] = mapped_column(Text)

    answer: Mapped[str] = mapped_column(Text)
    # TEXT / BOOLEAN / SINGLE_CHOICE / MULTIPLE_CHOICE
    answer_type: Mapped[str] = mapped_column(String(32), default="TEXT")

    # GLOBAL / EMPLOYER / JOB — reuse never widens beyond the stored scope.
    scope: Mapped[str] = mapped_column(String(16), default="JOB", index=True)
    employer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id"), nullable=True, index=True
    )

    # USER (approved by the user) / PROFILE (verified profile data)
    source: Mapped[str] = mapped_column(String(16), default="USER")
    # VERIFIED / UNVERIFIED
    verification_status: Mapped[str] = mapped_column(String(16), default="VERIFIED")
    # Hash of the profile data a PROFILE-sourced answer was derived from;
    # a mismatch marks the answer stale so it is never silently reused.
    profile_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Context-sensitive answers (salary, notice, relocation, ...) only reuse
    # when explicitly authorised; others may be reused automatically.
    auto_reusable: Mapped[bool] = mapped_column(Boolean, default=True)
    # Whether the question is family-sensitive (salary/notice/relocation/...).
    context_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Audit/provenance: which pending question produced this answer and how
    # often it has been reused since.
    origin_pending_question_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reuse_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optional stored option set for choice questions, used to detect a
    # changed/ambiguous option list before reusing an answer.
    options: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PendingQuestion(Base):
    """A screening question the run is waiting for the user to answer."""

    __tablename__ = "pending_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Linkage: active run token, the attempt being worked on, and the job.
    run_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    application_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("applications.id"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id"), nullable=True, index=True
    )
    employer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    question_text: Mapped[str] = mapped_column(Text)
    question_fingerprint: Mapped[str] = mapped_column(String(512), index=True)
    # TEXT / BOOLEAN / SINGLE_CHOICE / MULTIPLE_CHOICE
    question_type: Mapped[str] = mapped_column(String(32), default="TEXT")
    options: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    context_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # WAITING / ANSWERED / SKIPPED / CANCELLED / EXPIRED
    status: Mapped[str] = mapped_column(String(16), default="WAITING", index=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_scope: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # USER / REUSED (answered from a saved ScreeningAnswer)
    answered_via: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
