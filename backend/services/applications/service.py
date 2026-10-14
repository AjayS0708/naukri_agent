from datetime import UTC, datetime
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationAnswer as ApplicationAnswerModel
from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference, MatchResult
from backend.models.ai import JobAnalysisModel
from backend.schemas.application import (
    ApplicationStatus, ApplicationMethod, ApplicationSchema,
    ApplicationCreate, ApplicationUpdate
)
from backend.schemas.ai import JobAnalysis
from backend.services.matching.normalizer import (
    has_overlapping_location,
    extract_experience_years,
    is_employment_type_allowed,
    compute_profile_experience_years,
    normalize_naukri_url_for_comparison,
    evaluate_salary_gate,
)
from backend.services.matching.engine import (
    experience_passes_fresher_rule,
    is_strict_it_job,
    job_relevance_check,
)
from backend.core.logging import get_logger

logger = get_logger(__name__)


# E5-R5.3: exact page-chrome URL proven by the E5-R4.1 detector fix to have
# caused false EXTERNAL_APPLICATION classifications before that fix shipped.
# Only rows whose external_url equals this signature byte-for-byte are
# eligible for reconciliation; similar or derived URLs never match.
STALE_EXTERNAL_PAGE_CHROME_URL = (
    "https://www.ambitionbox.com/interviews"
    "?utm_source=naukri&utm_medium=desktop&utm_campaign=gnb"
)

STALE_EXTERNAL_RECONCILE_SKIP_REASON = (
    "Reconciled by E5-R5.3 stale-external reconciliation: prior "
    "EXTERNAL_APPLICATION classification came from the known Naukri "
    "page-chrome URL "
    f"({STALE_EXTERNAL_PAGE_CHROME_URL}), not a job-specific external "
    "application target. No external application was opened, submitted, or "
    "confirmed; job released back to the normal candidate pipeline."
)

# E5-R6: second reconciliation rule for EXTERNAL_APPLICATION rows created by
# the pre-E5-R5.4 body-scan-first classifier. Those rows recorded the job's
# own canonical Naukri URL as the "external" destination because the external
# URL grounding fell back to job.url when no indicator-matched external CTA
# link existed. A genuine external redirect destination can never equal the
# job's own Naukri URL, so an exact normalized equality with the linked
# job's URL (on a Naukri job-listing host/path) proves misclassification.
PRE_R5_4_NATIVE_URL_RECOVERY_TOKEN = (
    "recovered_pre_r5_4_native_url_misclassification"
)

PRE_R5_4_NATIVE_URL_RECOVERY_SKIP_REASON = (
    f"{PRE_R5_4_NATIVE_URL_RECOVERY_TOKEN}: EXTERNAL_APPLICATION external_url "
    "matched the linked job's own canonical Naukri URL (pre-E5-R5.4 "
    "body-scan-first misclassification). No external application was opened, "
    "submitted, or confirmed; job released back to the normal candidate "
    "pipeline for relevance-first evaluation."
)

# Defensive belt beyond the status filter: the operating instruction forbids
# reconciling these job IDs in any state. Their live rows are NEEDS_ATTENTION
# (already protected by the EXTERNAL_APPLICATION-only status filter), but the
# explicit ID guard protects against any future state drift.
PROTECTED_RECONCILE_JOB_IDS = {87, 120}

# E5-R16: read-only Naukri history reconciliation additionally never writes to
# these job IDs in any state (81, 114 extend the E5-R5/R6 protected pair).
PROTECTED_HISTORY_JOB_IDS = {81, 87, 114, 120}


# E5-R23: normalize_naukri_url_for_comparison now lives in
# backend.services.matching.normalizer (imported above) so the discovery
# deduplicator shares the exact same canonical form without importing this
# heavy module. The name is re-exported here for backward compatibility —
# existing callers import it from this module.


class SafetyGateError(Exception):
    """Raised when the safety gate blocks an application."""
    pass


class ApplicationService:
    """
    Coordinates the application flow with final safety gate.
    Gemini provides advisory analysis; Python rules are authoritative.
    """
    
    def __init__(self, session: Session):
        self.session = session

    # E5-R16: statuses that describe an *open* attempt for a job — an attempt
    # that was started but never reached a terminal state. Exactly one open
    # attempt may exist per job so a crash between the browser submission and
    # the database write can be resumed/reconciled instead of duplicated.
    OPEN_ATTEMPT_STATUSES = (
        ApplicationStatus.DISCOVERED.value,
        ApplicationStatus.PRE_APPLY.value,
        ApplicationStatus.APPLICATION_STARTED.value,
    )

    def _find_open_attempt(self, job_id: int) -> Optional[Application]:
        """Return the newest unfinished attempt row for a job, if any."""
        stmt = (
            select(Application)
            .where(Application.job_id == job_id)
            .where(Application.status.in_(self.OPEN_ATTEMPT_STATUSES))
            .order_by(Application.id.desc())
        )
        return self.session.execute(stmt).scalars().first()

    def create_application(self, create: ApplicationCreate) -> ApplicationSchema:
        """Create (or resume) an application attempt record.

        E5-R16 idempotency: a job may only have one open attempt. Repeated
        calls for the same job reuse the unfinished row instead of inserting
        a duplicate, giving every attempt a stable identifier.
        """
        application = self._find_open_attempt(create.job_id)
        created = application is None
        if application is None:
            application = Application(
                job_id=create.job_id,
                status=create.status.value,
                application_method=create.application_method.value if create.application_method else None,
                is_dry_run=create.is_dry_run
            )
            self.session.add(application)
        else:
            application.status = create.status.value
            if create.application_method is not None:
                application.application_method = create.application_method.value
            application.is_dry_run = create.is_dry_run
        self.session.commit()
        self.session.refresh(application)
        if not created:
            logger.debug(
                "application_attempt_reused",
                extra={"application_id": application.id, "job_id": create.job_id},
            )
        return self._to_schema(application)
    
    def get_application(self, application_id: int) -> Optional[ApplicationSchema]:
        """Get an application by ID."""
        application = self.session.get(Application, application_id)
        if not application:
            return None
        return self._to_schema(application)
    
    def update_application(self, application_id: int, update: ApplicationUpdate) -> Optional[ApplicationSchema]:
        """Update an application."""
        application = self.session.get(Application, application_id)
        if not application:
            return None
        
        if update.status is not None:
            application.status = update.status.value
        if update.application_method is not None:
            application.application_method = update.application_method.value
        if update.started_at is not None:
            application.started_at = update.started_at
        if update.applied_at is not None:
            application.applied_at = update.applied_at
        if update.failure_reason is not None:
            application.failure_reason = update.failure_reason
        if update.skip_reason is not None:
            application.skip_reason = update.skip_reason
        if update.confirmation_evidence is not None:
            application.confirmation_evidence = update.confirmation_evidence
        if update.external_url is not None:
            application.external_url = update.external_url
        if update.needs_attention is not None:
            application.needs_attention = update.needs_attention
        if update.is_dry_run is not None:
            application.is_dry_run = update.is_dry_run
        
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def get_application_by_job(self, job_id: int) -> Optional[ApplicationSchema]:
        """Get the most recent application for a job."""
        stmt = select(Application).where(Application.job_id == job_id).order_by(Application.created_at.desc())
        application = self.session.execute(stmt).scalars().first()
        if not application:
            return None
        return self._to_schema(application)
    
    def run_final_safety_gate(
        self,
        job: Job,
        profile: Profile,
        preference: JobPreference,
        job_analysis: Optional[JobAnalysis] = None
    ) -> tuple[bool, str]:
        """
        Final deterministic Python safety gate before application submission.
        Gemini output is advisory; this gate is authoritative.
        
        Returns:
            (allowed: bool, reason: str)
        """
        # 1. Job exists
        if not job or not job.id:
            return False, "Job does not exist"
        
        # 2. Profile is confirmed
        if not profile or not profile.confirmed:
            return False, "Profile is not confirmed by user"
        
        # 3. Check if already applied (duplicate protection)
        existing_application = self.get_application_by_job(job.id)
        if existing_application and existing_application.status in [ApplicationStatus.APPLIED, ApplicationStatus.SUBMITTED]:
            return False, "Job already applied to"
        
        # 4. Location hard filter
        if job.location and preference.locations:
            if not has_overlapping_location(job.location, preference.locations):
                return False, f"Location mismatch: job location '{job.location}' not in allowed locations"
        
        # 5. Strict fresher experience and IT-only scope
        experience_ok, experience_reason = experience_passes_fresher_rule(job, preference)
        if not experience_ok:
            return False, experience_reason
        if not is_strict_it_job(job, preference.it_industry_allowlist, preference.it_keyword_list):
            return False, "Industry/department/role category is not an allowed IT value or title has no IT keyword"
        
        # 6. Salary minimum rule (E5-R25: shared gate — unpaid and
        # disclosed-below-min reject; salary NULL/None (undisclosed) or
        # genuinely ambiguous is NOT rejected).
        salary_ok, salary_reason = evaluate_salary_gate(
            job.salary, job.salary_max, preference.min_salary_lpa
        )
        if not salary_ok:
            return False, salary_reason or "Salary does not meet the minimum preference."
        
        # 7. Employment type
        if job.employment_type and preference.employment_types:
            if not is_employment_type_allowed(job.employment_type, preference.employment_types):
                return False, f"Employment type '{job.employment_type}' not allowed"
        
        # 8. Role relevance — shared deterministic gate (E5-R17): title/search
        # scope plus the job's actual role category/department and described
        # responsibilities. This avoids false rejections from strict substring
        # mismatches between configured search titles (e.g. "Python Developer
        # Fresher") and actual Naukri job titles (e.g. "Python Developer"),
        # while rejecting sales/voice-process/manufacturing work that only
        # sounds technical in its title.  Unwanted specializations are caught
        # by title_matches_allowed_role inside job_relevance_check.
        if job.title:
            role_allowed, role_reason = job_relevance_check(
                job.title,
                getattr(preference, "job_titles", None),
                role_category=job.role_category,
                department=job.department,
                description=job.description,
            )
            if not role_allowed:
                return False, f"Job title '{job.title}' not in configured search scope: {role_reason}"
        
        # 9. Gemini suspicious/fraud flag (only if analysis available).
        #
        # Gemini is advisory. Its subjective recommendation is never treated as
        # proof of fraud: a job that matches the user's saved preferences and
        # passes every deterministic hard rule above must not be rejected solely
        # because Gemini returned NEEDS_ATTENTION (weak fit / vague description).
        # Only the explicit `suspicious` fraud flag blocks here, and the
        # deterministic rules above remain authoritative.
        if job_analysis and job_analysis.suspicious:
            return False, "Job flagged as suspicious by AI analysis"

        return True, "All safety checks passed"
    
    def check_duplicate_application(self, job: Job) -> bool:
        """
        Check if this job has already been applied to.
        Returns True if duplicate, False otherwise.
        """
        existing = self.get_application_by_job(job.id)
        if existing and existing.status in [ApplicationStatus.APPLIED, ApplicationStatus.SUBMITTED]:
            return True
        return False
    
    def record_external_application(
        self,
        job: Job,
        external_url: str,
        reason: str = "External application redirect",
        is_dry_run: bool = False
    ) -> ApplicationSchema:
        """
        Record an external application redirect.
        Does NOT submit the external application.
        """
        # E5-R16: reuse an unfinished attempt row for this job rather than
        # stacking a second record for the same attempt.
        application = self._find_open_attempt(job.id)
        if application is None:
            application = Application(
                job_id=job.id,
                status=ApplicationStatus.EXTERNAL_APPLICATION.value,
                application_method=ApplicationMethod.EXTERNAL.value,
                external_url=external_url,
                skip_reason=reason,
                needs_attention=True,
                is_dry_run=is_dry_run,
                started_at=datetime.now(UTC)
            )
            self.session.add(application)
        else:
            application.status = ApplicationStatus.EXTERNAL_APPLICATION.value
            application.application_method = ApplicationMethod.EXTERNAL.value
            application.external_url = external_url
            application.skip_reason = reason
            application.needs_attention = True
            application.is_dry_run = is_dry_run
            if application.started_at is None:
                application.started_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def record_application_failure(
        self,
        job: Job,
        failure_reason: str,
        needs_attention: bool = True
    ) -> ApplicationSchema:
        """Record an application failure."""
        application = self._find_open_attempt(job.id)
        status = (
            ApplicationStatus.NEEDS_ATTENTION.value
            if needs_attention
            else ApplicationStatus.SKIPPED.value
        )
        if application is None:
            application = Application(
                job_id=job.id,
                status=status,
                failure_reason=failure_reason,
                needs_attention=needs_attention,
                started_at=datetime.now(UTC)
            )
            self.session.add(application)
        else:
            application.status = status
            application.failure_reason = failure_reason
            application.needs_attention = needs_attention
            if application.started_at is None:
                application.started_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)

    def resolve_open_attempt(
        self, job: Job, failure_reason: str
    ) -> Optional[ApplicationSchema]:
        """Resolve an existing unfinished attempt; create nothing new.

        E5-R16: a session-level failure (logged out mid-flow) is not evidence
        about a job, so when no attempt row exists this returns None and the
        job is left without any application record.
        """
        application = self._find_open_attempt(job.id)
        if application is None:
            return None
        application.status = ApplicationStatus.NEEDS_ATTENTION.value
        application.failure_reason = failure_reason
        application.needs_attention = True
        if application.started_at is None:
            application.started_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)

    def record_application_skip(
        self,
        job: Job,
        skip_reason: str
    ) -> ApplicationSchema:
        """Record a skipped application.

        E5-R16: an identical repeat skip for the same job updates the existing
        SKIPPED row instead of appending a duplicate record.
        """
        stmt = (
            select(Application)
            .where(Application.job_id == job.id)
            .where(Application.status == ApplicationStatus.SKIPPED.value)
            .order_by(Application.id.desc())
        )
        latest_skip = self.session.execute(stmt).scalars().first()
        if latest_skip is not None and (latest_skip.skip_reason or "") == skip_reason:
            latest_skip.updated_at = datetime.now(UTC)
            self.session.commit()
            self.session.refresh(latest_skip)
            return self._to_schema(latest_skip)

        application = Application(
            job_id=job.id,
            status=ApplicationStatus.SKIPPED.value,
            skip_reason=skip_reason,
            started_at=datetime.now(UTC)
        )
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)

    def reconcile_stale_externals(self) -> dict:
        """
        Release jobs locked by proven-false external classifications.

        Rule 1 (E5-R5.3, unchanged): reclassifies only EXTERNAL_APPLICATION
        rows whose external_url exactly equals STALE_EXTERNAL_PAGE_CHROME_URL
        to SKIPPED, recording STALE_EXTERNAL_RECONCILE_SKIP_REASON.

        Rule 2 (E5-R6): reclassifies EXTERNAL_APPLICATION rows whose
        external_url matches the linked job's own canonical Naukri URL after
        safe normalization (see normalize_naukri_url_for_comparison) on a
        Naukri job-listing host/path, recording
        PRE_R5_4_NATIVE_URL_RECOVERY_SKIP_REASON. A genuine external
        redirect destination can never equal the job's own Naukri URL.
        Ambiguous rows (missing job, unparseable URL, non-Naukri host, non
        job-listing path, submission evidence, protected job IDs) are left
        unchanged and logged with the ineligibility reason.

        Both rules are idempotent, clear needs_attention on recovered rows,
        preserve history/timestamps, never delete records, never modify
        APPLIED, SUBMITTED, NEEDS_ATTENTION, FAILED, or already-SKIPPED rows,
        and are never invoked automatically by the autonomous cycle.
        Returns exact per-rule counts and affected IDs.
        """
        # Rule 1: legacy page-chrome signature (E5-R5.3)
        stmt = select(Application).where(
            Application.status == ApplicationStatus.EXTERNAL_APPLICATION.value,
            Application.external_url == STALE_EXTERNAL_PAGE_CHROME_URL,
        )
        applications = list(self.session.execute(stmt).scalars().all())
        application_ids: list[int] = []
        job_ids: list[int] = []
        for application in applications:
            application.status = ApplicationStatus.SKIPPED.value
            application.skip_reason = STALE_EXTERNAL_RECONCILE_SKIP_REASON
            application.needs_attention = False
            application_ids.append(application.id)
            job_ids.append(application.job_id)
        if applications:
            # Make rule-1 reclassifications visible to rule 2's query even on
            # sessions with autoflush disabled, so recovered rows are never
            # reconsidered as remaining EXTERNAL_APPLICATION rows.
            self.session.flush()

        # Rule 2: pre-R5.4 native-URL misclassification recovery (E5-R6)
        recovered_application_ids: list[int] = []
        recovered_job_ids: list[int] = []
        remaining_external_ids: list[int] = []
        external_stmt = (
            select(Application)
            .where(Application.status == ApplicationStatus.EXTERNAL_APPLICATION.value)
            .order_by(Application.id)
        )
        for application in self.session.execute(external_stmt).scalars().all():
            if application.status != ApplicationStatus.EXTERNAL_APPLICATION.value:
                # Already reclassified by rule 1 in this call.
                continue
            ineligibility = self._native_url_recovery_ineligibility_reason(application)
            if ineligibility is not None:
                remaining_external_ids.append(application.id)
                logger.info(
                    "reconcile_native_url_unchanged",
                    extra={
                        "application_id": application.id,
                        "job_id": application.job_id,
                        "reason": ineligibility,
                    },
                )
                continue
            application.status = ApplicationStatus.SKIPPED.value
            application.skip_reason = PRE_R5_4_NATIVE_URL_RECOVERY_SKIP_REASON
            application.needs_attention = False
            recovered_application_ids.append(application.id)
            recovered_job_ids.append(application.job_id)

        if applications or recovered_application_ids:
            self.session.commit()
            logger.info(
                "reconciled_stale_externals",
                extra={
                    "affected_count": len(applications),
                    "application_ids": application_ids,
                    "job_ids": job_ids,
                    "recovered_count": len(recovered_application_ids),
                    "recovered_application_ids": recovered_application_ids,
                    "recovered_job_ids": recovered_job_ids,
                },
            )
        return {
            "affected_count": len(application_ids),
            "application_ids": application_ids,
            "job_ids": job_ids,
            "signature": STALE_EXTERNAL_PAGE_CHROME_URL,
            "recovered_count": len(recovered_application_ids),
            "recovered_application_ids": recovered_application_ids,
            "recovered_job_ids": recovered_job_ids,
            "remaining_external_ids": remaining_external_ids,
        }

    def _native_url_recovery_ineligibility_reason(
        self, application: Application
    ) -> Optional[str]:
        """
        Return why an EXTERNAL_APPLICATION row is not eligible for E5-R6
        native-URL recovery, or None when it is eligible. Every condition is
        verified against the linked job record; ambiguity never matches.
        """
        if application.job_id in PROTECTED_RECONCILE_JOB_IDS:
            return "protected_job_id"
        if application.confirmation_evidence is not None:
            return "submission_evidence_present"
        if application.applied_at is not None:
            return "applied_at_present"
        job = self.session.get(Job, application.job_id)
        if job is None:
            return "missing_job_record"
        external_norm = normalize_naukri_url_for_comparison(application.external_url)
        if external_norm is None:
            return "unparseable_external_url"
        job_norm = normalize_naukri_url_for_comparison(job.url)
        if job_norm is None:
            return "unparseable_job_url"
        if external_norm != job_norm:
            return "external_url_not_job_canonical_url"
        host = urlsplit(external_norm).hostname or ""
        if host != "naukri.com" and not host.endswith(".naukri.com"):
            return "non_naukri_host"
        if not urlsplit(external_norm).path.startswith("/job-listings-"):
            return "non_job_listing_path"
        return None

    def reconcile_interrupted_attempts(self) -> dict:
        """Resolve attempts that never reached a terminal state (E5-R16).

        A crash (or a hard process kill) between the browser submission and
        the database write leaves a row stuck in APPLICATION_STARTED. Such a
        row is *unresolved*, never APPLIED: no submission is inferred without
        positive confirmation evidence. The row is moved to NEEDS_ATTENTION so
        it is visible for review and cannot silently double-submit.

        Idempotent, additive-only, and never touches APPLIED/SUBMITTED rows.
        """
        stmt = (
            select(Application)
            .where(Application.status == ApplicationStatus.APPLICATION_STARTED.value)
            .order_by(Application.id)
        )
        applications = list(self.session.execute(stmt).scalars().all())
        reconciled_ids: list[int] = []
        job_ids: list[int] = []
        for application in applications:
            application.status = ApplicationStatus.NEEDS_ATTENTION.value
            application.needs_attention = True
            application.failure_reason = (
                "Interrupted before submission confirmation; verify against "
                "Naukri application history before any retry"
            )
            reconciled_ids.append(application.id)
            job_ids.append(application.job_id)
        if applications:
            self.session.commit()
            logger.info(
                "reconciled_interrupted_attempts",
                extra={"count": len(applications), "application_ids": reconciled_ids},
            )
        return {
            "reconciled_count": len(reconciled_ids),
            "application_ids": reconciled_ids,
            "job_ids": job_ids,
        }

    @staticmethod
    def _normalize_title(value: Optional[str]) -> str:
        return " ".join((value or "").split()).lower()

    @staticmethod
    def _text_compatible(left: str, right: str) -> bool:
        """Loose equality for Naukri card labels vs stored job fields.

        Cards render decorated titles/companies ("Immediate openings For ...",
        "... Pvt Ltd"), so exact equality would reject true matches while a
        pure contains-check would accept unrelated labels.
        """
        if not left or not right:
            return True
        if left == right or left in right or right in left:
            return True
        left_tokens, right_tokens = set(left.split()), set(right.split())
        if not left_tokens or not right_tokens:
            return False
        overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
        return overlap >= 0.5

    def reconcile_from_history(self, history_entries: list[dict]) -> dict:
        """Reconcile verified Naukri application history against local rows.

        ``history_entries`` must come from a read-only inspection of the
        authenticated Naukri applied-jobs page — never from an Apply click,
        never from inference.

        Rules:
        * a local APPLIED/SUBMITTED row matching a history entry is reported
          as confirmed and left untouched;
        * a history entry with no local applied row creates ONE new APPLIED
          row (idempotent on re-run), marked as reconciled from history with
          the original timestamp preserved when available;
        * a local applied row absent from history is reported only — it is
          never deleted or downgraded;
        * entries that cannot be matched reliably are reported as ambiguous.

        Protected job IDs are reported but never written to.
        """
        jobs = list(self.session.execute(select(Job)).scalars().all())
        by_url: dict[str, list[Job]] = {}
        by_title_company: dict[tuple[str, str], list[Job]] = {}
        by_external_id: dict[str, list[Job]] = {}
        for job in jobs:
            norm = normalize_naukri_url_for_comparison(job.url)
            if norm:
                by_url.setdefault(norm, []).append(job)
            key = (self._normalize_title(job.title), self._normalize_title(job.company))
            if key[0]:
                by_title_company.setdefault(key, []).append(job)
            external_id = str(job.external_job_id or "").strip()
            if external_id:
                by_external_id.setdefault(external_id, []).append(job)

        applications = list(self.session.execute(select(Application)).scalars().all())
        applied_by_job: dict[int, list[Application]] = {}
        for application in applications:
            if application.status in (
                ApplicationStatus.APPLIED.value,
                ApplicationStatus.SUBMITTED.value,
            ):
                applied_by_job.setdefault(application.job_id, []).append(application)

        confirmed: list[int] = []
        reconciled_application_ids: list[int] = []
        reconciled_job_ids: list[int] = []
        ambiguous: list[str] = []
        unmatched: list[str] = []
        protected: list[int] = []

        for entry in history_entries or []:
            url = (entry.get("url") or "").strip()
            external_job_id = str(entry.get("external_job_id") or "").strip()
            entry_title = self._normalize_title(entry.get("title"))
            entry_company = self._normalize_title(entry.get("company"))
            label = (
                url
                or (f"naukri_job_id:{external_job_id}" if external_job_id else "")
                or str(entry.get("title") or "unknown")
            )

            candidates: list[Job] = []
            id_key_rejected = False

            # 1. Naukri's numeric job id is the most precise key the history
            #    card exposes; the card's title/company must not contradict it.
            #    When the card carries an id we do not know locally, the entry
            #    is not fuzzy-matched onto some other job — it is reported.
            if external_job_id:
                id_matches = by_external_id.get(external_job_id, [])
                if not id_matches:
                    unmatched.append(label)
                    continue
                if len(id_matches) == 1:
                    job = id_matches[0]
                    if self._text_compatible(
                        entry_title, self._normalize_title(job.title)
                    ) and self._text_compatible(
                        entry_company, self._normalize_title(job.company or "")
                    ):
                        candidates = [job]
                    else:
                        id_key_rejected = True
                elif len(id_matches) > 1:
                    id_key_rejected = True

            # 2. Canonical Naukri URL, when the card renders a link.
            if not candidates and not id_key_rejected and url:
                norm = normalize_naukri_url_for_comparison(url)
                if norm:
                    candidates = list(by_url.get(norm, []))

            # 3. Title + company (exact key first, then loose compatibility).
            if not candidates and not id_key_rejected and entry_title and entry_company:
                candidates = list(by_title_company.get((entry_title, entry_company), []))
                if not candidates:
                    candidates = [
                        job
                        for job in jobs
                        if self._text_compatible(
                            entry_title, self._normalize_title(job.title)
                        )
                        and self._text_compatible(
                            entry_company, self._normalize_title(job.company or "")
                        )
                    ]

            if id_key_rejected:
                ambiguous.append(label)
                continue
            if not candidates:
                unmatched.append(label)
                continue
            if len(candidates) > 1:
                ambiguous.append(label)
                continue

            job = candidates[0]
            if job.id in PROTECTED_HISTORY_JOB_IDS:
                if job.id not in applied_by_job:
                    protected.append(job.id)
                continue
            if job.id in applied_by_job:
                confirmed.append(job.id)
                continue

            applied_at = entry.get("applied_at")
            if isinstance(applied_at, str):
                applied_at = None
            source = label
            application = Application(
                job_id=job.id,
                status=ApplicationStatus.APPLIED.value,
                application_method=ApplicationMethod.NAUKRI_NATIVE.value,
                applied_at=applied_at,
                started_at=applied_at,
                confirmation_evidence=f"reconciled_from_naukri_history:{source}",
                reconciled_from_history=True,
                needs_attention=False,
                is_dry_run=False,
            )
            self.session.add(application)
            self.session.flush()
            applied_by_job.setdefault(job.id, []).append(application)
            reconciled_application_ids.append(application.id)
            reconciled_job_ids.append(job.id)

        local_without_history = sorted(
            job_id
            for job_id in applied_by_job
            if job_id not in set(confirmed) and job_id not in set(reconciled_job_ids)
        )

        if reconciled_application_ids:
            self.session.commit()
            logger.info(
                "reconciled_from_naukri_history",
                extra={
                    "reconciled_count": len(reconciled_application_ids),
                    "job_ids": reconciled_job_ids,
                },
            )
        else:
            self.session.commit()

        return {
            "history_entries": len(history_entries or []),
            "confirmed_local_job_ids": confirmed,
            "reconciled_count": len(reconciled_application_ids),
            "reconciled_application_ids": reconciled_application_ids,
            "reconciled_job_ids": reconciled_job_ids,
            "local_applied_without_history_evidence": local_without_history,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
            "protected_job_ids": sorted(set(protected)),
        }

    def get_application_history(self, limit: int = 100) -> list[ApplicationSchema]:
        """Get application history."""
        stmt = select(Application).order_by(Application.created_at.desc()).limit(limit)
        applications = self.session.execute(stmt).scalars().all()
        return [self._to_schema(app) for app in applications]
    
    def _to_schema(self, application: Application) -> ApplicationSchema:
        """Convert model to schema."""
        return ApplicationSchema(
            id=application.id,
            job_id=application.job_id,
            status=ApplicationStatus(application.status),
            application_method=ApplicationMethod(application.application_method) if application.application_method else None,
            started_at=application.started_at,
            applied_at=application.applied_at,
            failure_reason=application.failure_reason,
            skip_reason=application.skip_reason,
            confirmation_evidence=application.confirmation_evidence,
            external_url=application.external_url,
            needs_attention=application.needs_attention,
            is_dry_run=application.is_dry_run,
            reconciled_from_history=bool(
                getattr(application, "reconciled_from_history", False)
            ),
            created_at=application.created_at,
            updated_at=application.updated_at
        )
