import asyncio
from datetime import UTC, datetime
from typing import Optional

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
from backend.services.applications.limits import ApplicationLimitService
from backend.schemas.application import ApplicationStatus, ApplicationMethod, ApplicationCreate, ApplicationUpdate
from backend.services.naukri.adapter import NaukriAdapter
from backend.services.gemini.provider import GeminiProvider
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

    def __init__(self, session: Session, state_manager: AgentStateManager):
        self.session = session
        self.state_manager = state_manager
        self.application_service = ApplicationService(session)
        self.limit_service = ApplicationLimitService(session)
        self.adapter = NaukriAdapter(browser_type=get_settings().browser_type)
        self.ai_provider = GeminiProvider()
        self._stop_requested = False
        self._session_started = False

    async def stop_safely(self):
        """Request a graceful stop to the application runner."""
        self._stop_requested = True
        logger.info("application_runner_stop_requested")

    async def run_applications(self, job_ids: list[int]) -> dict:
        """
        Process a list of eligible job IDs sequentially.
        Returns statistics about the run.
        """
        if self.state_manager.current_state != AgentState.IDLE:
            logger.warning("Application runner can only start from IDLE state")
            return {"error": "Invalid state"}

        self._stop_requested = False
        self.state_manager.transition_to(AgentState.RUNNING)

        stats = {
            "total": len(job_ids),
            "processed": 0,
            "applied": 0,
            "skipped": 0,
            "needs_attention": 0,
            "external": 0,
            "failed": 0,
            "errors": 0
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

                    # Small delay between applications
                    await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
                    stats["errors"] += 1

            # Return to IDLE
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
        Returns: "APPLIED", "SKIPPED", "NEEDS_ATTENTION", "EXTERNAL", "FAILED", "ERROR"
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

        # Check application limits
        limit_check = self.limit_service.check_limits()
        if not limit_check.allowed:
            logger.info(f"Job {job_id} blocked by application limits: {limit_check.reason}")
            self.application_service.record_application_skip(job, limit_check.reason)
            return "SKIPPED"

        # Create application record
        application = self.application_service.create_application(
            ApplicationCreate(job_id=job_id, status=ApplicationStatus.APPLICATION_STARTED)
        )

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
                return "SECURITY_REQUIRED"

            # Detect application type
            app_type = await self.adapter.detect_application_type(page)

            if app_type == "EXTERNAL":
                external_url = await self.adapter.get_external_redirect_url(page)
                self.application_service.record_external_application(
                    job, external_url or job.url, "External application redirect"
                )
                logger.info(f"Job {job_id} requires external application")
                return "EXTERNAL"

            # Start Naukri-native application
            started = await self.adapter.start_application(page)
            if not started:
                self.application_service.record_application_failure(
                    job, "Failed to start application"
                )
                return "FAILED"

            # Detect and answer questions
            questions = await self.adapter.detect_application_questions(page)
            for q in questions:
                question_text = q.get("question", "")
                if not question_text:
                    continue

                # Try to answer from profile
                answer = self._get_answer_from_profile(question_text, profile)
                if not answer:
                    # Try AI-generated answer
                    answer = self._get_ai_answer(question_text, job, profile)

                if answer:
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

            # Submit application
            submitted = await self.adapter.submit_application(page)
            if not submitted:
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
                # Submission may have succeeded even without confirmation
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.SUBMITTED,
                        applied_at=datetime.now(UTC)
                    )
                )
                logger.info(f"Job {job_id} submitted (confirmation unclear)")
                return "APPLIED"

        except Exception as e:
            error_msg = str(e).lower()

            # Check for security/authentication issues
            if "captcha" in error_msg or "security" in error_msg:
                self.application_service.record_application_failure(
                    job, "Security verification required"
                )
                self.state_manager.transition_to(AgentState.SECURITY_REQUIRED)
                return "FAILED"

            if "login" in error_msg or "auth" in error_msg:
                self.application_service.record_application_failure(
                    job, "Authentication required"
                )
                self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
                return "FAILED"

            logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
            self.application_service.record_application_failure(
                job, f"Application error: {str(e)}"
            )
            return "FAILED"

        finally:
            if page:
                await page.close()

    def _get_answer_from_profile(self, question: str, profile: Profile) -> Optional[str]:
        """Try to answer a question from confirmed profile data."""
        question_lower = question.lower()
        profile_data = profile.data if isinstance(profile.data, dict) else {}

        # Common factual questions
        if "experience" in question_lower or "years" in question_lower:
            exp_count = len(profile_data.get("experience", []))
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
