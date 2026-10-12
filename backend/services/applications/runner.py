import asyncio
from datetime import UTC, datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.models.ai_queue import AIQueueItem
from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.applications.service import ApplicationService, SafetyGateError
from backend.schemas.application import (
    ApplicationStatus,
    ApplicationMethod,
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationStartResult,
)
from backend.services.naukri.adapter import NaukriAdapter
from backend.services.matching.normalizer import compute_profile_experience_years
from backend.services.gemini.provider import GeminiProvider
from backend.services.notifications import NotificationService
from backend.schemas.ai import JobAnalysis
from backend.schemas.ai_queue import AIQueueStatus
from backend.core.logging import get_logger
from backend.core.config import get_settings

logger = get_logger(__name__)


class ApplicationRunner:
    """
    Coordinates the application flow for eligible jobs.
    Processes jobs sequentially with safety gate enforcement.
    """

    def __init__(
        self,
        session: Session,
        state_manager: AgentStateManager,
        dry_run: bool = False,
        supervise_form: bool = False,
    ):
        self.session = session
        self.state_manager = state_manager
        self.application_service = ApplicationService(session)
        self.adapter = NaukriAdapter(browser_type=get_settings().browser_type)
        self.ai_provider = GeminiProvider()
        self._stop_requested = False
        self._session_started = False
        self.dry_run = dry_run
        self.supervise_form = supervise_form
        self.answer_questions = get_settings().answer_questions
        self.dry_run_result = None

    async def stop_safely(self):
        """Request a graceful stop to the application runner."""
        self._stop_requested = True
        logger.info("application_runner_stop_requested")

    async def run_applications(self, job_ids: list[int], dry_run: bool = False) -> dict:
        """
        Process a list of eligible job IDs sequentially.
        Returns statistics about the run.

        Args:
            job_ids: List of job IDs to process
            dry_run: If True, inspect application form but do not submit (default: False)
        """
        self.dry_run = dry_run
        if self.state_manager.current_state != AgentState.IDLE:
            logger.warning("Application runner can only start from IDLE state")
            return {"error": "Invalid state"}

        self._stop_requested = False
        self.state_manager.transition_to(AgentState.RUNNING)

        stats = {
            "total": len(job_ids),
            "processed": 0,
            "applied": 0,
            "submitted_unconfirmed": 0,
            "skipped": 0,
            "needs_attention": 0,
            "external": 0,
            "failed": 0,
            "errors": 0,
            "auth_required": 0,
            "dry_run": 0,
            "dry_run_mode": dry_run
        }

        try:
            # Start browser session
            started = await self.adapter.start_session()
            if not started:
                logger.error("Failed to start browser session")
                self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
                return stats

            self._session_started = True
            self.state_manager.transition_to(AgentState.SEARCHING)
            self.state_manager.transition_to(AgentState.FILTERING)
            self.state_manager.transition_to(AgentState.APPLYING)

            # Get profile and preferences
            profile = self.session.execute(select(Profile)).scalars().first()
            if not profile or not profile.confirmed:
                logger.error("No confirmed profile found")
                stats["errors"] = len(job_ids)
                return stats

            preferences = self.session.execute(select(JobPreference)).scalars().first()
            if not preferences:
                logger.error("No job preferences found")
                stats["errors"] = len(job_ids)
                return stats

            # Process jobs sequentially
            for job_id in job_ids:
                if self._stop_requested:
                    logger.info("Application runner stopped by user request")
                    break

                try:
                    result = await self._process_single_job(job_id, profile, preferences)
                    stats["processed"] += 1

                    if result == "APPLIED":
                        stats["applied"] += 1
                    elif result == "SUBMITTED_UNCONFIRMED":
                        stats["submitted_unconfirmed"] += 1
                    elif result == "SKIPPED":
                        stats["skipped"] += 1
                    elif result == "NEEDS_ATTENTION":
                        stats["needs_attention"] += 1
                    elif result == "EXTERNAL":
                        stats["external"] += 1
                    elif result == "FAILED":
                        stats["failed"] += 1
                    elif result == "ERROR":
                        stats["errors"] += 1
                    elif result == "AUTH_REQUIRED":
                        # E5-R16: logged-out session — halt immediately; the
                        # caller surfaces LOGIN_REQUIRED to the dashboard.
                        stats["auth_required"] += 1
                        break
                    elif result == "DRY_RUN_COMPLETE":
                        stats["dry_run"] += 1

                    # Small delay between applications
                    await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
                    stats["errors"] += 1
                    if self.state_manager.current_state in (
                        AgentState.SECURITY_REQUIRED,
                        AgentState.AUTH_REQUIRED,
                        AgentState.CRITICAL_ERROR,
                    ):
                        break

            # Return to IDLE, except after a logged-out session (E5-R16):
            # AUTH_REQUIRED stays visible so the operator sees why the workflow
            # stopped instead of an unexplained idle state.
            if self.state_manager.current_state != AgentState.AUTH_REQUIRED:
                self.state_manager.transition_to(AgentState.STOPPED)
                self.state_manager.transition_to(AgentState.IDLE)

        except Exception as e:
            logger.error(f"Application runner failed: {e}", exc_info=True)
            self.state_manager.transition_to(AgentState.CRITICAL_ERROR)

        finally:
            if self._session_started:
                await self.adapter.stop_session()
                self._session_started = False

        return stats

    async def _process_single_job(
        self,
        job_id: int,
        profile: Profile,
        preferences: JobPreference
    ) -> str:
        """
        Process a single job through the complete application flow.
        Returns: "APPLIED", "SUBMITTED_UNCONFIRMED", "SKIPPED", "NEEDS_ATTENTION", "EXTERNAL", "FAILED", "ERROR"
        """
        job = self.session.get(Job, job_id)
        if not job:
            logger.warning(f"Job {job_id} not found")
            return "ERROR"

        # Check if job is in AI queue and not completed
        queue_item = self.session.execute(
            select(AIQueueItem).where(AIQueueItem.job_id == job_id)
        ).scalars().first()

        if queue_item and queue_item.status != AIQueueStatus.COMPLETED.value:
            logger.info(f"Job {job_id} has incomplete AI analysis (status: {queue_item.status})")
            self.application_service.record_application_skip(job, f"AI analysis not completed: {queue_item.status}")
            return "SKIPPED"

        # Get AI analysis if available
        job_analysis = None
        analysis_model = self.session.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job_id)
        ).scalars().first()

        if analysis_model:
            job_analysis = JobAnalysis(
                match_score=analysis_model.match_score,
                role_match=analysis_model.role_match,
                skill_match=analysis_model.skill_match,
                experience_match=analysis_model.experience_match,
                location_match=analysis_model.location_match,
                salary_match=analysis_model.salary_match,
                job_quality=analysis_model.job_quality,
                duplicate_probability=analysis_model.duplicate_probability,
                suspicious=analysis_model.suspicious,
                recommendation=analysis_model.recommendation,
                short_reason=analysis_model.short_reason
            )
        else:
            # No AI analysis available - skip job
            logger.info(f"Job {job_id} has no AI analysis")
            self.application_service.record_application_skip(job, "No AI analysis available")
            return "SKIPPED"

        # Run final safety gate
        allowed, reason = self.application_service.run_final_safety_gate(
            job, profile, preferences, job_analysis
        )

        if not allowed:
            logger.info(f"Job {job_id} blocked by safety gate: {reason}")
            self.application_service.record_application_skip(job, reason)
            return "SKIPPED"

        # Check duplicate
        if self.application_service.check_duplicate_application(job):
            logger.info(f"Job {job_id} already applied to")
            self.application_service.record_application_skip(job, "Duplicate application")
            return "SKIPPED"

        latest = self.application_service.get_application_by_job(job.id)
        if latest and latest.status in (
            ApplicationStatus.EXTERNAL_APPLICATION,
            ApplicationStatus.NEEDS_ATTENTION,
        ):
            logger.info(f"Job {job_id} has an unresolved prior attempt; manual reset required")
            return "SKIPPED"

        # Open job page
        page = None
        try:
            result = await self.adapter.open_job_page(job.url)
            page = result.page

            # Check if security intervention is required
            if result.security_required:
                logger.warning(f"Security challenge encountered for job {job_id}: {result.security_reason}")
                self.application_service.record_application_failure(
                    job, f"Security challenge: {result.security_reason}"
                )
                self._notify_safely(
                    lambda: NotificationService(self.session).security_challenge(
                        f"Security challenge while opening job {job_id}: {result.security_reason}"
                    )
                )
                return "SECURITY_REQUIRED"

            # Phase 10: Detect application type BEFORE creating APPLICATION_STARTED
            # E5-R16: authentication state is checked first and kept separate
            # from application mode. A logged-out session must stop this job
            # without producing an application record of any kind.
            login_state = await self.adapter.detect_login_state(page)
            if login_state.get("authenticated") is False:
                logger.warning(
                    "Naukri session logged out for job %s (evidence: %s); "
                    "stopping application processing",
                    job_id,
                    login_state.get("evidence"),
                )
                self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
                return "AUTH_REQUIRED"

            app_type = await self.adapter.detect_application_type(page)

            if app_type == "EXTERNAL":
                external_url = await self.adapter.get_external_redirect_url(page)
                if not external_url:
                    # E5-R16: no positive destination evidence. The page is
                    # not provably external (a logged-out or incomplete page
                    # is not evidence either), so this is unresolved.
                    logger.warning(
                        "Job %s classified EXTERNAL without destination "
                        "evidence; recording unresolved instead",
                        job_id,
                    )
                    self.application_service.record_application_failure(
                        job, "Application destination unresolved (no external link evidence)"
                    )
                    return "NEEDS_ATTENTION"
                self.application_service.record_external_application(
                    job,
                    external_url,
                    "external - needs review",
                    is_dry_run=self.dry_run,
                )
                self._notify_safely(
                    lambda: NotificationService(self.session).external_application(
                        job.title, external_url
                    )
                )
                logger.info(
                    "Job %s requires external application (external_url=%s)",
                    job_id,
                    external_url,
                )
                return "EXTERNAL"

            if app_type == "AMBIGUOUS":
                logger.warning("Application type is ambiguous for job %s", job_id)
                return "NEEDS_ATTENTION"

            # Phase 10: Re-classify immediately before the click (non-dry-run only)
            if not self.dry_run:
                recheck_type = await self.adapter.detect_application_type(page)
                if recheck_type == "EXTERNAL":
                    external_url = await self.adapter.get_external_redirect_url(page)
                    if external_url:
                        logger.warning(
                            "Application type changed before Apply click: %s",
                            recheck_type,
                        )
                        self.application_service.record_external_application(
                            job,
                            external_url,
                            "external - needs review",
                            is_dry_run=False,
                        )
                        return "EXTERNAL"
                    logger.warning(
                        "Re-check reported EXTERNAL for job %s without "
                        "destination evidence; not recording EXTERNAL",
                        job_id,
                    )
                elif recheck_type != "NAUKRI_NATIVE":
                    # E5-R16: AMBIGUOUS (e.g. Apply hidden while logged out)
                    # is NOT evidence of an external destination. Never record
                    # an external application for an unresolved re-check.
                    logger.warning(
                        "Application type changed before Apply click: %s "
                        "(unresolved; no external record created)",
                        recheck_type,
                    )
                    return "NEEDS_ATTENTION"

            # Phase 10: Create APPLICATION_STARTED only after classification is confirmed
            application = self.application_service.create_application(
                ApplicationCreate(
                    job_id=job_id,
                    status=ApplicationStatus.PRE_APPLY if self.dry_run else ApplicationStatus.APPLICATION_STARTED,
                    application_method=ApplicationMethod.NAUKRI_NATIVE,
                    is_dry_run=self.dry_run,
                )
            )
            if not self.dry_run:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        started_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                    ),
                )

            if self.dry_run:
                self.dry_run_result = {
                    "job_id": job.id,
                    "job_title": job.title,
                    "job_company": job.company,
                    "job_url": job.url,
                    "application_type": app_type,
                    "inspection_only": True,
                    "native_apply_clicked": False,
                    "start_application_called": False,
                    "submit_application_called": False,
                }
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        skip_reason="Dry run mode: pre-Apply inspection only",
                    ),
                )
                logger.info(
                    f"DRY RUN: Job {job.id} inspected before native Apply; no remote action"
                )
                return "DRY_RUN_COMPLETE"

            # Start Naukri-native application
            start_result = await self.adapter.start_application(page)
            if start_result == ApplicationStartResult.APPLIED:
                evidence = await self.adapter.detect_applied_state(page)
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                        confirmation_evidence=evidence[1],
                    ),
                )
                return "APPLIED"
            if start_result != ApplicationStartResult.FORM_OPENED:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        needs_attention=True,
                        skip_reason="Application form did not open within bounded wait",
                    ),
                )
                return "NEEDS_ATTENTION"

            # E5-R7: Naukri's native Apply opens a multi-step *conversational*
            # drawer (chatbot_Drawer) that asks one screening question at a time
            # and submits on the final Save. Drive it to completion here; the
            # legacy single-form path below cannot model this flow.
            if await self.adapter.is_conversational_apply(page):
                return await self._complete_conversational_application(
                    page, application, job, profile
                )

            # Detect and answer questions
            questions = await self.adapter.detect_application_questions(page)
            if questions and not self.answer_questions:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        needs_attention=True,
                        skip_reason="questions - needs review",
                    ),
                )
                return "NEEDS_ATTENTION"
            if self.supervise_form:
                visible_fields = [
                    {
                        "question": question.get("question", ""),
                        "required": question.get("required", False),
                        "type": question.get("type"),
                    }
                    for question in questions
                ]
                logger.warning(
                    "Supervised form stop for job %s; visible editable fields: %s",
                    job_id,
                    visible_fields,
                )
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        needs_attention=True,
                        skip_reason="Supervised stop at FORM_OPENED; no fields filled",
                    ),
                )
                return "NEEDS_ATTENTION"

            prepared_answers = []

            for q in questions:
                question_text = q.get("question", "")
                if not question_text:
                    continue

                # Try to answer from profile
                answer = self._get_answer_from_profile(question_text, profile)
                answer_source = "PROFILE" if answer else None

                if not answer:
                    # Try AI-generated answer
                    answer = self._get_ai_answer(question_text, job, profile)
                    if answer:
                        answer_source = "GEMINI"

                if answer:
                    prepared_answers.append({
                        "question": question_text,
                        "answer": answer,
                        "source": answer_source,
                        "required": q.get("required", False)
                    })
                    if not self.dry_run:
                        await self.adapter.answer_question(page, question_text, answer)
                else:
                    # Cannot answer - needs attention
                    self.application_service.update_application(
                        application.id,
                        ApplicationUpdate(
                            status=ApplicationStatus.NEEDS_ATTENTION,
                            skip_reason=f"Could not answer question: {question_text}"
                        )
                    )
                    return "NEEDS_ATTENTION"

            # Submit application (production path only)
            submitted = await self.adapter.submit_application(page)
            if not submitted:
                if self.adapter.last_submit_outcome == "AMBIGUOUS":
                    # E5-R20: a timed-out/intercepted click leaves the true
                    # state unknown — reconcile against Naukri's application
                    # history before recording any outcome.
                    return await self._reconcile_unconfirmed_attempt(
                        application,
                        job,
                        "Form submit click timed out or was intercepted (ambiguous)",
                    )
                self.application_service.record_application_failure(
                    job, "Failed to submit application"
                )
                return "FAILED"

            # Confirm submission
            confirmed = await self.adapter.confirm_submission(page)
            if confirmed:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC)
                    )
                )
                logger.info(f"Job {job_id} applied successfully")
                return "APPLIED"
            else:
                # Submission may have succeeded even without confirmation.
                # E5-R5.2: this is NOT a confirmed application. Persist the
                # truthful SUBMITTED status (no retry, no resubmission) and
                # report a distinct outcome so callers never count it as
                # APPLIED or consume the successful-application budget.
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.SUBMITTED,
                        applied_at=datetime.now(UTC)
                    )
                )
                logger.info(
                    f"Job {job_id} submitted without confirmation "
                    f"(confirmation_unclear)"
                )
                return "SUBMITTED_UNCONFIRMED"

        except Exception as e:
            error_msg = str(e).lower()

            # Check for security/authentication issues
            if "captcha" in error_msg or "security" in error_msg:
                self.application_service.record_application_failure(
                    job, "Security verification required"
                )
                self.state_manager.transition_to(AgentState.SECURITY_REQUIRED)
                self._notify_safely(
                    lambda: NotificationService(self.session).security_challenge(
                        "Security verification required during application processing"
                    )
                )
                return "FAILED"

            if "login" in error_msg or "auth" in error_msg:
                # E5-R16: a session-level failure says nothing about this job.
                # Resolve an attempt row if one is already open; otherwise
                # create no application record at all.
                self.application_service.resolve_open_attempt(
                    job, "Authentication required"
                )
                self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
                self._notify_safely(
                    lambda: NotificationService(self.session).authentication_required(
                        "Authentication required during application processing"
                    )
                )
                return "AUTH_REQUIRED"

            logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
            self.application_service.record_application_failure(
                job, f"Application error: {str(e)}"
            )
            return "FAILED"

        finally:
            if page:
                await page.close()

    def _notify_safely(self, callback: Callable[[], object]) -> None:
        try:
            callback()
        except Exception as exc:
            logger.error(
                "application_notification_failed",
                extra={"error_type": type(exc).__name__},
            )

    def _get_answer_from_profile(self, question: str, profile: Profile) -> Optional[str]:
        """Try to answer a question from confirmed profile data."""
        question_lower = question.lower()
        profile_data = profile.data if isinstance(profile.data, dict) else {}

        # E5-R14: Handle specific screening questions based on profile skills/projects
        # Data Cleaning/EDA question - check for relevant skills and projects
        if "data cleaning" in question_lower or "eda" in question_lower or "exploratory data analysis" in question_lower:
            skills = profile_data.get("skills", [])
            projects = profile_data.get("projects", [])
            
            # Check for data cleaning/EDA skills
            relevant_skills = [s for s in skills if any(term in s.lower() for term in ["pandas", "numpy", "data", "analysis", "cleaning"])]
            
            # Check projects for data cleaning work
            has_data_project = False
            for project in projects:
                if isinstance(project, dict):
                    desc = project.get("description", "").lower()
                    if "clean" in desc or "process" in desc or "data" in desc:
                        has_data_project = True
                        break
            
            if relevant_skills or has_data_project:
                return "Yes"

        # Common factual questions
        if "experience" in question_lower or "years" in question_lower:
            exp_count = compute_profile_experience_years(profile_data.get("experience", []))
            return str(exp_count)

        if "current ctc" in question_lower or "salary" in question_lower:
            ctc = profile_data.get("current_ctc")
            if ctc:
                return str(ctc)

        if "notice period" in question_lower:
            notice = profile_data.get("notice_period")
            if notice:
                return str(notice)

        if "location" in question_lower:
            location = profile_data.get("location")
            if location:
                return str(location)

        if "education" in question_lower or "degree" in question_lower:
            education = profile_data.get("education", [])
            if education:
                return str(education[0]) if isinstance(education, list) else str(education)

        return None

    def _get_ai_answer(self, question: str, job: Job, profile: Profile) -> Optional[str]:
        """Get AI-generated answer for open-ended questions."""
        try:
            job_context = f"Title: {job.title}\nCompany: {job.company}\nDescription: {job.description or ''}"
            profile_context = str(profile.data)

            answer = self.ai_provider.answer_question(job_context, profile_context, question)
            if answer and answer.answer and not answer.needs_attention:
                return answer.answer
        except Exception as e:
            logger.warning(f"AI answer generation failed: {e}")

        return None

    # E5-R7: conversational (chatbot_Drawer) application support ----------------

    _CONVERSATIONAL_MAX_STEPS = 12
    # E5-R20: the same prompt may be interacted with at most this many times
    # before the attempt terminates with a specific reason (previously the
    # same nudge was "answered" 12 times in a row with no progress).
    _CONVERSATIONAL_MAX_PROMPT_HANDLES = 2
    # E5-R20: global bound on answer interactions per attempt.
    _CONVERSATIONAL_MAX_ANSWERS = 8

    async def _complete_conversational_application(
        self, page, application, job: Job, profile: Profile
    ) -> str:
        """Drive Naukri's multi-step conversational apply drawer to completion.

        The drawer shows one prompt at a time: an answerable question, an
        informational nudge (e.g. "update your profile") or a confirmation.

        E5-R20 rules:
        - questions are answered at most ``_CONVERSATIONAL_MAX_PROMPT_HANDLES``
          times per distinct prompt; an unchanged repeat terminates the
          attempt with a specific reason instead of looping.
        - nudges/prompts with no answer options are NEVER answered: they are
          observed once (with at most one supported dismissal click) and a
          second unchanged observation terminates with a specific reason.
        - Applied is recorded only on explicit confirmation evidence; every
          other ending is reconciled against Naukri's application history
          first (history is authoritative over an intercepted/timed-out
          click) before NEEDS_ATTENTION is written.
        """
        prompt_handles: dict[tuple, int] = {}
        total_answers = 0

        for step in range(1, self._CONVERSATIONAL_MAX_STEPS + 1):
            applied, evidence = await self.adapter.detect_applied_state(page)
            if applied:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                        confirmation_evidence=evidence,
                    ),
                )
                logger.info("Conversational apply confirmed (step %d): %s", step, evidence)
                return "APPLIED"

            questions = await self.adapter.detect_application_questions(page)
            if not questions:
                logger.info("Conversational drawer has no more questions (step %d)", step)
                break

            question = questions[0]
            question_text = question.get("question", "")
            options = question.get("options") or []
            # E5-R20: detection tags conversational prompts with an explicit
            # kind ("question" | "nudge" | "info"). Dicts without a kind are
            # legacy-shaped form questions and stay answerable.
            kind = question.get("kind") or (
                "question"
                if options or question.get("type") in ("text", "radio", "select")
                else "info"
            )
            signature = (
                self.adapter._normalize_choice(question_text),
                tuple(self.adapter._normalize_choice(o) for o in options),
            )
            handles = prompt_handles.get(signature, 0)

            if kind != "question":
                # E5-R20: informational prompt (nudge) — never answer it.
                if handles == 0:
                    prompt_handles[signature] = 1
                    if await self.adapter.dismiss_conversational_nudge(page):
                        logger.info(
                            "Dismissed conversational prompt (step %d): %r",
                            step,
                            question_text,
                        )
                    else:
                        logger.info(
                            "Observed conversational prompt without answer options "
                            "(step %d): %r",
                            step,
                            question_text,
                        )
                    await asyncio.sleep(2.0)
                    continue
                return await self._reconcile_unconfirmed_attempt(
                    application,
                    job,
                    "Persistent conversational nudge with no answer options "
                    f"(unanswered): {question_text}",
                )

            if handles >= self._CONVERSATIONAL_MAX_PROMPT_HANDLES:
                return await self._reconcile_unconfirmed_attempt(
                    application,
                    job,
                    "Conversational prompt unchanged after answering "
                    f"(possible stale UI): {question_text}",
                )

            # Answerable question: answer from profile first.
            answer = self._get_answer_from_profile(question_text, profile)
            if options:
                if not answer or self.adapter._normalize_choice(answer) not in [
                    self.adapter._normalize_choice(o) for o in options
                ]:
                    answer = self._answer_radio_via_ai(question_text, options, job, profile)
                if not answer:
                    return await self._reconcile_unconfirmed_attempt(
                        application, job,
                        f"Could not choose an option for: {question_text}",
                    )
            else:
                if not answer:
                    answer = self._get_ai_answer(question_text, job, profile)
                if not answer:
                    return await self._reconcile_unconfirmed_attempt(
                        application, job,
                        f"Could not answer question: {question_text}",
                    )

            if not await self.adapter.answer_conversational_question(
                page, answer, expected_question=question_text
            ):
                return await self._reconcile_unconfirmed_attempt(
                    application, job,
                    f"Failed to answer question: {question_text}",
                )

            prompt_handles[signature] = handles + 1
            total_answers += 1
            logger.info(
                "Conversational step %d answered %r with %r", step, question_text, answer
            )
            if total_answers >= self._CONVERSATIONAL_MAX_ANSWERS:
                return await self._reconcile_unconfirmed_attempt(
                    application,
                    job,
                    "Conversational interaction bound reached before Applied confirmation",
                )
            await asyncio.sleep(2.0)

        # Final explicit confirmation, then a bounded submit attempt whose
        # result is reconciled against Naukri's application history.
        applied, evidence = await self.adapter.detect_applied_state(page)
        if applied:
            self.application_service.update_application(
                application.id,
                ApplicationUpdate(
                    status=ApplicationStatus.APPLIED,
                    applied_at=datetime.now(UTC),
                    application_method=ApplicationMethod.NAUKRI_NATIVE,
                    confirmation_evidence=evidence,
                ),
            )
            logger.info("Conversational apply confirmed after loop: %s", evidence)
            return "APPLIED"

        # E5-R20: click only a supported Apply/Submit control (never .sendMsg)
        # and treat every non-confirmed result — including a timed-out or
        # intercepted click — as unconfirmed pending history reconciliation.
        outcome = await self.adapter.submit_conversational_application(page)
        if outcome == "SUBMITTED":
            await asyncio.sleep(2.0)
            applied, evidence = await self.adapter.detect_applied_state(page)
            if applied:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                        confirmation_evidence=evidence,
                    ),
                )
                logger.info("Conversational apply confirmed after submit: %s", evidence)
                return "APPLIED"
            return await self._reconcile_unconfirmed_attempt(
                application,
                job,
                "Conversational submit clicked without Applied confirmation",
            )
        if outcome == "AMBIGUOUS":
            return await self._reconcile_unconfirmed_attempt(
                application,
                job,
                "Conversational submit click timed out or was intercepted (ambiguous)",
            )
        return await self._reconcile_unconfirmed_attempt(
            application,
            job,
            "Conversational apply completed without Applied confirmation "
            "and no supported submit control was found",
        )

    async def _reconcile_unconfirmed_attempt(
        self, application, job: Job, reason: str
    ) -> str:
        """E5-R20: reconcile an unconfirmed ending against Naukri's
        application history before recording NEEDS_ATTENTION.

        History is authoritative: when the applied-jobs page lists this job,
        ApplicationService.reconcile_from_history (idempotent, never touches
        protected jobs) records/keeps the APPLIED row, the current attempt
        row is annotated for audit but never rewritten to APPLIED, and the
        outcome reported is "APPLIED". When history does not list it, the
        attempt is annotated NEEDS_ATTENTION with the specific reason — no
        retry is attempted from here.
        """
        history_entries = None
        try:
            history_entries = await self.adapter.fetch_application_history()
        except Exception as exc:
            logger.warning(
                "Job %s: application-history reconciliation unavailable: %s",
                job.id,
                exc,
            )

        if history_entries is not None:
            try:
                result = self.application_service.reconcile_from_history(history_entries)
            except Exception as exc:
                logger.warning(
                    "Job %s: reconcile_from_history failed: %s", job.id, exc
                )
                result = None
            if result is not None:
                confirmed_ids = set(result.get("confirmed_local_job_ids") or [])
                reconciled_ids = set(result.get("reconciled_job_ids") or [])
                if job.id in confirmed_ids or job.id in reconciled_ids:
                    self.application_service.update_application(
                        application.id,
                        ApplicationUpdate(
                            status=ApplicationStatus.NEEDS_ATTENTION,
                            needs_attention=True,
                            skip_reason=(
                                f"{reason}; application confirmed via Naukri "
                                "application history (no in-page confirmation)"
                            ),
                        ),
                    )
                    logger.info(
                        "Job %s confirmed via application-history reconciliation",
                        job.id,
                    )
                    return "APPLIED"
                logger.info(
                    "Job %s: history does not list this application "
                    "(reconciled=%d, confirmed=%d, ambiguous=%d, unmatched=%d)",
                    job.id,
                    len(reconciled_ids),
                    len(confirmed_ids),
                    len(result.get("ambiguous") or []),
                    len(result.get("unmatched") or []),
                )

        self.application_service.update_application(
            application.id,
            ApplicationUpdate(
                status=ApplicationStatus.NEEDS_ATTENTION,
                needs_attention=True,
                skip_reason=(
                    f"{reason}; not confirmed in Naukri application history"
                    if history_entries is not None
                    else f"{reason}; application history unavailable for verification"
                ),
            ),
        )
        logger.warning("Job %s unconfirmed: %s", job.id, reason)
        return "NEEDS_ATTENTION"

    def _answer_radio_via_ai(
        self, question: str, options: list[str], job: Job, profile: Profile
    ) -> Optional[str]:
        """Ask the AI to pick exactly one of the provided radio options.

        Returns the matched option (normalized back to its original casing) or
        None when no option can be chosen confidently. Never fabricates a choice.
        """
        try:
            constrained = (
                f"{question}\n"
                f"Options: {', '.join(options)}. "
                "Reply with exactly one option word/phrase from the list."
            )
            raw = self._get_ai_answer(constrained, job, profile)
            if not raw:
                return None
            norm_raw = self.adapter._normalize_choice(raw)
            for option in options:
                if self.adapter._normalize_choice(option) == norm_raw:
                    return option
            for option in options:
                norm_opt = self.adapter._normalize_choice(option)
                if norm_opt and (norm_opt in norm_raw or norm_raw in norm_opt):
                    return option
        except Exception as exc:
            logger.warning("Radio AI answer failed: %s", exc)
        return None
