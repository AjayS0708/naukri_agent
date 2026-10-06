from datetime import datetime
import inspect
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.models.discovery import DiscoveryRun, utc_now
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.services.naukri.adapter import NaukriAdapter
from backend.services.matching.engine import experience_passes_fresher_rule
from backend.services.matching.normalizer import parse_salary_to_range
from backend.database.database import SessionLocal
from backend.core.logging import get_logger
from backend.core.config import get_settings

logger = get_logger(__name__)

DISCOVERY_STATUS_RUNNING = "RUNNING"
DISCOVERY_STATUS_COMPLETED = "COMPLETED"
DISCOVERY_STATUS_FAILED = "FAILED"
DISCOVERY_STATUS_STOPPED = "STOPPED"
DISCOVERY_STATUS_AUTH_REQUIRED = "AUTH_REQUIRED"
DISCOVERY_STATUS_SECURITY_REQUIRED = "SECURITY_REQUIRED"


class DiscoveryService:
    def __init__(self, state_manager: AgentStateManager, max_cards: int = 150):
        self.state_manager = state_manager
        settings = get_settings()
        self.adapter = NaukriAdapter(browser_type=settings.browser_type)
        self.current_run: Optional[DiscoveryRun] = None
        self.current_search: Optional[str] = None
        self._stop_requested = False
        self.max_cards = max_cards
        self.current_run_job_ids: set[int] = set()  # Track job IDs from current run

    @property
    def is_running(self) -> bool:
        return self.state_manager.current_state in [
            AgentState.RUNNING,
            AgentState.SEARCHING,
            AgentState.FILTERING,
        ]

    async def stop_safely(self):
        """Request a graceful stop to the discovery process."""
        self._stop_requested = True
        logger.info("discovery_stop_requested")

    async def run_discovery(self, db: Session | None = None) -> None:
        """
        Orchestrates the discovery flow fetching jobs using the adapter,
        deduplicating them, and persisting them to the database.
        """
        if self.is_running:
            return

        owns_session = db is None
        db = db or SessionLocal()

        self._stop_requested = False
        self.state_manager.transition_to(AgentState.RUNNING)

        run = DiscoveryRun(status=DISCOVERY_STATUS_RUNNING)
        db.add(run)
        db.commit()
        db.refresh(run)
        self.current_run = run

        # Ensure the new column exists (for backward compatibility)
        try:
            from sqlalchemy import inspect
            inspector = inspect(db.bind)
            columns = [col['name'] for col in inspector.get_columns('discovery_runs')]
            if 'current_run_job_ids' not in columns:
                try:
                    db.execute("ALTER TABLE discovery_runs ADD COLUMN current_run_job_ids TEXT")
                    db.commit()
                except Exception as e:
                    logger.warning(f"Failed to add current_run_job_ids column: {e}")
        except Exception as e:
            # Schema inspection may fail on mock sessions during tests
            logger.debug(f"Schema inspection skipped (likely mock session): {e}")

        filtering_entered = False

        try:
            started = await self.adapter.start_session()
            if not started:
                self._finalize_run(db, DISCOVERY_STATUS_FAILED, "Failed to start browser session.")
                self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
                return

            if self._stop_requested:
                self._abort_before_search(db, "Stopped by user.")
                return

            preferences = db.execute(select(JobPreference)).scalars().first()
            if not preferences:
                self._abort_before_search(db, "No job preferences found. Configure them first.")
                return

            search_terms = preferences.job_titles or [
                "Data Analyst Fresher",
                "Junior Data Analyst",
                "Associate Data Analyst",
                "Software Engineer Fresher",
                "Associate Software Engineer",
                "Software Developer Fresher",
                "Python Developer Fresher",
                "Data Engineer Fresher",
                "Junior Data Engineer",
                "Associate Data Engineer",
                "DevOps Trainee",
                "Junior DevOps Engineer",
                "DevOps Engineer Fresher",
            ]
            locations = preferences.locations or []
            if not search_terms:
                self._abort_before_search(db, "No job titles configured.")
                return

            self.state_manager.transition_to(AgentState.SEARCHING)

            for term in search_terms:
                if self._stop_requested:
                    break

                self.current_search = term
                self.current_run.searches_attempted += 1
                db.commit()

                if not filtering_entered:
                    self.state_manager.transition_to(AgentState.FILTERING)
                    filtering_entered = True

                jobs_before_term = self.current_run.jobs_discovered
                seen_pages: set[int] = set()
                term_yielded_any = False

                try:
                    async for job_data in self.adapter.search_jobs(term, locations):
                        if self._stop_requested:
                            break

                        term_yielded_any = True
                        self._track_page_processed(db, job_data, seen_pages)
                        self.current_run.jobs_discovered += 1
                        if self.current_run.jobs_discovered > self.max_cards:
                            self._stop_requested = True
                            break

                        card_job = Job(
                            title=job_data.get("title") or "",
                            experience=job_data.get("experience"),
                        )
                        experience_text = job_data.get("experience")
                        experience_ok, _ = experience_passes_fresher_rule(card_job, preferences)
                        # Only reject before opening when the card explicitly shows
                        # an over-cap minimum. Missing text requires page enrichment.
                        if experience_text and not experience_ok:
                            self.current_run.jobs_discovered -= 1
                            continue

                        existing_job = self._find_existing_job(db, job_data)

                        if existing_job:
                            self.current_run.duplicate_jobs += 1
                            existing_job.last_seen = utc_now()
                            db.commit()
                            # Track existing job ID as part of current run
                            self.current_run_job_ids.add(existing_job.id)
                            continue

                        self.current_run.new_jobs += 1

                        # Always fetch job details to enrich IT metadata (industry/department/role_category)
                        # even if description is already present from the card
                        if job_data.get("url"):
                            details_result = await self.adapter.fetch_job_details(job_data["url"])
                            if details_result:
                                job_data.update(details_result)

                        new_job = self._build_job(job_data, term)
                        if new_job is None:
                            self.current_run.new_jobs -= 1
                            self.current_run.jobs_discovered -= 1
                            continue

                        db.add(new_job)
                        db.commit()
                        db.refresh(new_job)

                        # Track new job ID as part of current run
                        self.current_run_job_ids.add(new_job.id)

                    self._track_implicit_page(db, jobs_before_term, seen_pages)

                    # If this search term yielded no jobs and it's the first term,
                    # this indicates a navigation/selector failure (not just empty results)
                    if not term_yielded_any and self.current_run.jobs_discovered == 0:
                        logger.warning(f"Search term '{term}' yielded no jobs - possible navigation failure")
                        self.current_run.errors += 1

                except Exception as e:
                    logger.error(f"Error during search for {term}: {str(e)}", exc_info=True)
                    self.current_run.errors += 1

                    error_lower = str(e).lower()
                    if "login required" in error_lower or "sign in" in error_lower:
                        self._finalize_run(db, DISCOVERY_STATUS_AUTH_REQUIRED, "Naukri login required.")
                        self._transition_to_auth_required()
                        return
                    if "security verification" in error_lower or "captcha" in error_lower or "access blocked" in error_lower:
                        self._finalize_run(db, DISCOVERY_STATUS_SECURITY_REQUIRED, f"Security verification required: {str(e)}")
                        self._transition_to_security_required()
                        # Page is left open by adapter for manual CAPTCHA resolution
                        # Browser context will be cleaned up when session is stopped
                        return

            if self._stop_requested:
                self._finalize_run(db, DISCOVERY_STATUS_STOPPED, None)
            else:
                self._finalize_run(db, DISCOVERY_STATUS_COMPLETED, None)
            self._return_to_idle_from_active()

        except Exception as e:
            logger.error(f"Discovery run failed: {str(e)}", exc_info=True)
            self._finalize_run(db, DISCOVERY_STATUS_FAILED, f"Critical error: {str(e)}")
            self._transition_to_critical_error()
        finally:
            await self.adapter.stop_session()
            self.current_search = None
            if owns_session:
                db.close()

    def _track_page_processed(self, db: Session, job_data: dict[str, Any], seen_pages: set[int]) -> None:
        page_number = job_data.get("page_number")
        if page_number is None:
            return
        if page_number in seen_pages:
            return
        seen_pages.add(page_number)
        self.current_run.pages_processed += 1
        db.commit()

    def _track_implicit_page(self, db: Session, jobs_before_term: int, seen_pages: set[int]) -> None:
        if seen_pages:
            return
        if self.current_run.jobs_discovered <= jobs_before_term:
            return
        self.current_run.pages_processed += 1
        db.commit()

    def _find_existing_job(self, db: Session, job_data: dict[str, Any]) -> Job | None:
        existing_job = None
        if job_data.get("external_job_id"):
            existing_job = db.execute(
                select(Job).where(Job.external_job_id == job_data["external_job_id"])
            ).scalars().first()

        if not existing_job and job_data.get("url"):
            existing_job = db.execute(
                select(Job).where(Job.url == job_data["url"])
            ).scalars().first()

        if not existing_job and job_data.get("title") and job_data.get("company"):
            existing_job = db.execute(
                select(Job).where(Job.title == job_data["title"], Job.company == job_data["company"])
            ).scalars().first()

        return existing_job

    def _normalize_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _build_job(self, job_data: dict[str, Any], source_term: str) -> Job | None:
        url = self._normalize_optional_str(job_data.get("url"))
        title = self._normalize_optional_str(job_data.get("title"))
        company = self._normalize_optional_str(job_data.get("company"))
        external_job_id = self._normalize_optional_str(job_data.get("external_job_id"))

        if not title or not company:
            return None

        if not external_job_id:
            if not url:
                return None
            external_job_id = f"tmp_{hash(url)}"

        now = utc_now()
        posted_at = job_data.get("posted_at")
        if posted_at is not None and not isinstance(posted_at, datetime):
            posted_at = None

        # Parse salary to extract min/max in LPA
        salary_text = self._normalize_optional_str(job_data.get("salary"))
        salary_min, salary_max = parse_salary_to_range(salary_text) if salary_text else (None, None)

        return Job(
            platform=self.adapter.platform_name,
            external_job_id=external_job_id,
            url=url or "",
            title=title,
            company=company,
            description=self._normalize_optional_str(job_data.get("description")),
            location=self._normalize_optional_str(job_data.get("location")),
            salary=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            experience=self._normalize_optional_str(job_data.get("experience")),
            employment_type=self._normalize_optional_str(job_data.get("employment_type")),
            industry=self._normalize_optional_str(job_data.get("industry")),
            department=self._normalize_optional_str(job_data.get("department")),
            role_category=self._normalize_optional_str(job_data.get("role_category")),
            posted_at=posted_at,
            discovered_at=now,
            last_seen=now,
            source=source_term,
        )

    def _finalize_run(self, db: Session, status: str, error_message: str | None) -> None:
        if self.current_run:
            self.current_run.status = status
            self.current_run.completed_at = utc_now()
            self.current_run.error_message = error_message
            # Save job IDs from current run as comma-separated string
            if self.current_run_job_ids:
                self.current_run.current_run_job_ids = ",".join(str(jid) for jid in sorted(self.current_run_job_ids))
            db.commit()

    def _abort_before_search(self, db: Session, error_message: str) -> None:
        self._finalize_run(db, DISCOVERY_STATUS_STOPPED, error_message)
        if self.state_manager.current_state == AgentState.RUNNING:
            self.state_manager.transition_to(AgentState.STOPPED)
        if self.state_manager.current_state == AgentState.STOPPED:
            self.state_manager.transition_to(AgentState.IDLE)

    def _return_to_idle_from_active(self) -> None:
        state = self.state_manager.current_state
        if state == AgentState.FILTERING:
            self.state_manager.transition_to(AgentState.STOPPED)
        elif state == AgentState.SEARCHING:
            self.state_manager.transition_to(AgentState.FILTERING)
            self.state_manager.transition_to(AgentState.STOPPED)
        if self.state_manager.current_state == AgentState.STOPPED:
            self.state_manager.transition_to(AgentState.IDLE)

    def _transition_to_auth_required(self) -> None:
        state = self.state_manager.current_state
        if state == AgentState.SEARCHING:
            self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
        elif state == AgentState.FILTERING:
            self.state_manager.transition_to(AgentState.AUTH_REQUIRED)

    def _transition_to_security_required(self) -> None:
        state = self.state_manager.current_state
        if state == AgentState.SEARCHING:
            self.state_manager.transition_to(AgentState.SECURITY_REQUIRED)
        elif state == AgentState.FILTERING:
            self.state_manager.transition_to(AgentState.SECURITY_REQUIRED)

    def _transition_to_critical_error(self) -> None:
        state = self.state_manager.current_state
        if state == AgentState.RUNNING:
            self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
        elif state == AgentState.SEARCHING:
            self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
        elif state == AgentState.FILTERING:
            self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
