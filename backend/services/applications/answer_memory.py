"""E5-R21: scoped, human-approved screening-answer memory.

Design rules (from MASTER_PRD / FUTURE_IMPLEMENTATION_ROADMAP):
- Reuse is scope-aware: GLOBAL, EMPLOYER or JOB — never widens silently.
- Sensitive/auth-type questions (password, OTP, tokens, ...) are NEVER
  stored as reusable answers and never auto-answered.
- Context-sensitive answers (salary, notice, relocation, visa, availability,
  commitment) are treated as JOB-scoped unless the user explicitly
  authorises a wider scope.
- PROFILE-sourced answers carry a profile-data hash and are considered
  stale (and skipped) whenever the profile changes underneath them.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.logging import get_logger
from backend.models.screening import ScreeningAnswer

logger = get_logger(__name__)

# Questions that must never be answered automatically or persisted: credentials,
# one-time codes and other secrets.
_SENSITIVE_RE = re.compile(
    r"\b("
    r"password|passwd|pass word|otp|one[-\s]?time (password|code|passcode)|"
    r"token|secret|api[ _-]?key|credential|security answer|login id|"
    r"card number|cvv|social security|aadhaar|pan number"
    r")\b",
    re.IGNORECASE,
)

# Context-sensitive families: a one-off answer here must not become a
# universal answer without explicit authorisation.
CONTEXT_SENSITIVE_FAMILIES: dict[str, tuple[str, ...]] = {
    "salary": ("salary", "ctc", "compensation", "expected ctc", "current ctc", "pay expectation"),
    "notice": ("notice period", "notice", "serving notice", "notice days"),
    "relocation": ("relocat", "willing to move", "ready to move", "open to move"),
    "visa": ("visa", "work authori", "work permit", "right to work", "passport"),
    "availability": ("immediate joiner", "available from", "available to start", "joining date", "join by", "start date"),
    "commitment": ("long term", "retention", "how long will you", "bond period", "commitment"),
}


def normalize_question(text: Optional[str]) -> str:
    """Lowercase, strip punctuation, collapse whitespace; cap at column size."""
    lowered = (text or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()[:512]


def normalize_option(option: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", (option or "").lower())


def is_sensitive_question(question: Optional[str]) -> bool:
    return bool(_SENSITIVE_RE.search(question or ""))


def context_sensitive_family(question: Optional[str]) -> Optional[str]:
    lowered = (question or "").lower()
    for family, keywords in CONTEXT_SENSITIVE_FAMILIES.items():
        for keyword in keywords:
            if keyword in lowered:
                return family
    return None


def profile_data_hash(profile: Any) -> str:
    """Stable hash of confirmed profile data used to detect staleness."""
    data = getattr(profile, "data", None)
    if not isinstance(data, dict):
        data = {}
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:64]


class ScreeningAnswerService:
    """Lookup/upsert for the reusable screening-answer store."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ read

    def find(
        self,
        question: str,
        *,
        options: Optional[list[str]] = None,
        employer: Optional[str] = None,
        job_id: Optional[int] = None,
        profile: Any = None,
    ) -> Optional[ScreeningAnswer]:
        """Return the best reusable answer for ``question``, or None.

        Scope rules: a JOB answer only applies to the same job, an EMPLOYER
        answer only to the same employer (or the original job), a GLOBAL
        answer anywhere. PROFILE-sourced rows are skipped when the profile
        data hash no longer matches. Choice answers are skipped when they are
        not one of the currently offered options.
        """
        if is_sensitive_question(question):
            return None

        fingerprint = normalize_question(question)
        if not fingerprint:
            return None

        rows = self.session.execute(
            select(ScreeningAnswer)
            .where(ScreeningAnswer.question_fingerprint == fingerprint)
            .order_by(ScreeningAnswer.id.desc())
        ).scalars().all()
        if not rows:
            return None

        current_hash = profile_data_hash(profile) if profile is not None else None
        normalized_options = (
            {normalize_option(option) for option in options} if options else None
        )
        normalized_employer = normalize_option(employer)

        for row in rows:
            if not row.auto_reusable:
                continue

            if row.scope == "JOB":
                if job_id is None or row.job_id != job_id:
                    continue
            elif row.scope == "EMPLOYER":
                same_job = row.job_id is not None and job_id is not None and row.job_id == job_id
                same_employer = bool(
                    row.employer
                    and normalized_employer
                    and normalize_option(row.employer) == normalized_employer
                )
                if not (same_job or same_employer):
                    continue
            # GLOBAL: applies everywhere.

            if (
                row.source == "PROFILE"
                and row.profile_hash
                and current_hash
                and row.profile_hash != current_hash
            ):
                # Profile changed since this answer was derived — stale.
                continue

            if normalized_options is not None and normalize_option(row.answer) not in normalized_options:
                # The option list changed or the saved answer is not offered
                # anymore — this must go back to the human.
                continue

            return row

        return None

    def mark_reused(self, row: ScreeningAnswer) -> None:
        row.reuse_count = (row.reuse_count or 0) + 1
        row.last_used_at = datetime.now(UTC)
        self.session.commit()

    def list_answers(self) -> list[ScreeningAnswer]:
        return list(
            self.session.execute(
                select(ScreeningAnswer).order_by(ScreeningAnswer.updated_at.desc())
            ).scalars().all()
        )

    def get(self, answer_id: int) -> Optional[ScreeningAnswer]:
        return self.session.get(ScreeningAnswer, answer_id)

    # ----------------------------------------------------------------- write

    def save_user_answer(
        self,
        question: str,
        answer: str,
        *,
        scope: str = "JOB",
        employer: Optional[str] = None,
        job_id: Optional[int] = None,
        options: Optional[list[str]] = None,
        source: str = "USER",
        answer_type: str = "TEXT",
        profile_hash: Optional[str] = None,
        origin_pending_question_id: Optional[int] = None,
        allow_global_reuse: bool = False,
    ) -> ScreeningAnswer:
        """Persist an answer (upsert on fingerprint + scope + keys).

        Raises ValueError for sensitive questions and for a GLOBAL scope on a
        context-sensitive question that was not explicitly authorised.
        """
        if is_sensitive_question(question):
            raise ValueError("Sensitive questions are never stored as reusable answers")
        if scope not in ("GLOBAL", "EMPLOYER", "JOB"):
            raise ValueError(f"Invalid scope: {scope}")

        family = context_sensitive_family(question)
        if family and scope == "GLOBAL" and not allow_global_reuse:
            raise ValueError(
                "Context-sensitive answers require explicit authorisation "
                "before they can be reused for all jobs"
            )

        fingerprint = normalize_question(question)
        if not fingerprint or not (answer or "").strip():
            raise ValueError("Question and answer are required")

        existing = None
        if scope == "GLOBAL":
            stmt = (
                select(ScreeningAnswer)
                .where(ScreeningAnswer.question_fingerprint == fingerprint)
                .where(ScreeningAnswer.scope == "GLOBAL")
            )
            existing = self.session.execute(stmt).scalars().first()
        elif scope == "EMPLOYER":
            stmt = (
                select(ScreeningAnswer)
                .where(ScreeningAnswer.question_fingerprint == fingerprint)
                .where(ScreeningAnswer.scope == "EMPLOYER")
                .where(ScreeningAnswer.employer == employer)
                .where(ScreeningAnswer.job_id.is_(None))
            )
            existing = self.session.execute(stmt).scalars().first()
        else:  # JOB
            stmt = (
                select(ScreeningAnswer)
                .where(ScreeningAnswer.question_fingerprint == fingerprint)
                .where(ScreeningAnswer.scope == "JOB")
                .where(ScreeningAnswer.job_id == job_id)
            )
            existing = self.session.execute(stmt).scalars().first()

        if existing is None:
            existing = ScreeningAnswer(
                question_fingerprint=fingerprint,
                question_text=question.strip(),
                answer=answer.strip(),
                answer_type=answer_type,
                scope=scope,
                employer=employer,
                job_id=job_id if scope == "JOB" else None,
                source=source,
                verification_status="VERIFIED",
                profile_hash=profile_hash,
                auto_reusable=True,
                context_sensitive=bool(family),
                options=options,
                origin_pending_question_id=origin_pending_question_id,
                reuse_count=0,
            )
            self.session.add(existing)
        else:
            existing.question_text = question.strip()
            existing.answer = answer.strip()
            existing.answer_type = answer_type
            existing.source = source
            existing.verification_status = "VERIFIED"
            existing.profile_hash = profile_hash
            existing.context_sensitive = bool(family)
            if options:
                existing.options = options
            if origin_pending_question_id:
                existing.origin_pending_question_id = origin_pending_question_id
            existing.updated_at = datetime.now(UTC)

        self.session.commit()
        self.session.refresh(existing)
        return existing

    def update_answer(
        self,
        answer_id: int,
        *,
        answer: Optional[str] = None,
        scope: Optional[str] = None,
        allow_global_reuse: bool = False,
    ) -> Optional[ScreeningAnswer]:
        row = self.get(answer_id)
        if row is None:
            return None
        if scope is not None and scope not in ("GLOBAL", "EMPLOYER", "JOB"):
            raise ValueError(f"Invalid scope: {scope}")
        question_for_checks = row.question_text
        new_scope = scope or row.scope
        if is_sensitive_question(question_for_checks):
            raise ValueError("Sensitive questions are never stored as reusable answers")
        family = context_sensitive_family(question_for_checks)
        if family and new_scope == "GLOBAL" and not allow_global_reuse:
            raise ValueError(
                "Context-sensitive answers require explicit authorisation "
                "before they can be reused for all jobs"
            )
        if answer is not None and not answer.strip():
            raise ValueError("Answer cannot be empty")
        if answer is not None:
            row.answer = answer.strip()
        if scope is not None:
            row.scope = scope
            row.context_sensitive = bool(family)
        row.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete_answer(self, answer_id: int) -> bool:
        row = self.get(answer_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
