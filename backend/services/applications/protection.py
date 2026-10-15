"""E5-R28: shared application-history protection for candidate selection.

Run 88 found the same defect in three stages: each stage re-implemented the
"has this job already been applied to?" rule slightly differently, and the
apply-loop candidate query used *per-row* semantics —
``(Application.id == None) | (Application.status == SKIPPED)`` matched a job
that had a SKIPPED row **and** an unresolved NEEDS_ATTENTION / APPLIED row
(job #81), so a protected job entered the candidate list and was only skipped
late by the runner's manual-reset guard.

This module is the single source of truth for that rule:

- A job with **no** application rows is eligible.
- A job whose rows are **only** SKIPPED rows is eligible (a deliberate skip is
  re-processable — pinned by E5-R6 / E5-R13 tests).
- A job with any *blocking* row (an in-flight, confirmed, or unresolved
  attempt) is protected — even when a SKIPPED row also exists. This is the
  only semantic change versus the legacy per-row rule: blocking rows always
  win.
- A job with rows but no SKIPPED row (e.g. only EXTERNAL_APPLICATION) stays
  protected, exactly as before.

Protection is never weakened: the new predicate is a strict superset of the
legacy one, so every job excluded before is still excluded.

Two shapes are provided because the call sites differ:

- :func:`protected_from_candidate_selection` — a correlated SQL predicate for
  unbounded queries (candidate query, scheduler query).
- :func:`protected_job_ids` — a bulk Python helper for bounded id sets
  (recovery pools, enqueue stage, runner guard) that also lets each stage
  count how many jobs protection removed.
"""

from collections.abc import Iterable, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.job import Job
from backend.schemas.application import ApplicationStatus

# Statuses that represent a real application state: an in-flight attempt, a
# confirmed submission, or an unresolved row that requires a manual reset.
# Legacy row kinds that are not attempts (FILTERED / AI_ANALYZED /
# APPROVED_BY_RULES) are intentionally absent — a job holding only such rows
# is still protected by the "rows but no SKIPPED row" clause below, and a job
# holding one of them *plus* a deliberate SKIPPED row may be reconsidered.
# EXTERNAL_APPLICATION is also absent: pinned E5-R6 behavior keeps a
# SKIPPED + EXTERNAL job a candidate, while an EXTERNAL-only job remains
# protected by the "rows but no SKIPPED row" clause.
BLOCKING_APPLICATION_STATUSES: frozenset[str] = frozenset(
    {
        ApplicationStatus.DISCOVERED.value,
        ApplicationStatus.PRE_APPLY.value,
        ApplicationStatus.APPLICATION_STARTED.value,
        ApplicationStatus.APPLIED.value,
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.NEEDS_ATTENTION.value,
    }
)

_SKIPPED = ApplicationStatus.SKIPPED.value


def is_protected_statuses(statuses: Iterable[str | None]) -> bool:
    """Pure-Python protection rule for one job's application statuses."""
    seen = {(status or "").strip() for status in statuses}
    if not seen:
        return False
    if seen & set(BLOCKING_APPLICATION_STATUSES):
        return True
    # Rows exist but none of them is a deliberate SKIPPED record.
    return _SKIPPED not in seen


def protected_from_candidate_selection():
    """Correlated SQL boolean expression: the job's history blocks a new attempt.

    Job-level semantics (one decision per job), so a job with several
    application rows is evaluated once instead of once per joined row.
    """
    any_row = select(Application.id).where(Application.job_id == Job.id)
    skipped_row = select(Application.id).where(
        Application.job_id == Job.id,
        Application.status == _SKIPPED,
    )
    blocking_row = select(Application.id).where(
        Application.job_id == Job.id,
        Application.status.in_(sorted(BLOCKING_APPLICATION_STATUSES)),
    )
    return or_(
        blocking_row.exists(),
        and_(any_row.exists(), ~skipped_row.exists()),
    )


def protected_job_ids(session: Session, job_ids: Sequence[int]) -> set[int]:
    """Bulk lookup: which of ``job_ids`` are protected by application history.

    Issues a single query over the bounded id set and applies
    :func:`is_protected_statuses` per job. Returns an empty set for an empty
    input so call sites can call it unconditionally.
    """
    ids: set[int] = set()
    for job_id in job_ids:
        try:
            ids.add(int(job_id))
        except (TypeError, ValueError):
            continue
    if not ids:
        return set()

    rows = session.execute(
        select(Application.job_id, Application.status).where(
            Application.job_id.in_(ids)
        )
    ).all()

    statuses_by_job: dict[int, set[str]] = {}
    for job_id, status in rows:
        statuses_by_job.setdefault(job_id, set()).add(status or "")

    return {
        job_id
        for job_id, statuses in statuses_by_job.items()
        if is_protected_statuses(statuses)
    }
