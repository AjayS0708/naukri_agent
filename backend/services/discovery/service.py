from datetime import UTC, datetime
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
from backend.services.matching.engine import experience_passes_fresher_rule, irrelevant_role_reason
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

# E5-R19: targeted search groups beyond the configured job_titles, so discovery
# covers the preference's full scope instead of only the exact configured
# phrasings. Every term here is verified to match an allowed role family in the
# shared relevance gate (title_matches_allowed_role), so search capacity is
# never spent on queries whose results the gate would reject outright. Plain
# "Business Analyst" / "Reporting Analyst" titles are intentionally absent:
# the shared gate rejects them, so querying them cannot yield an eligible job.
# Ordered P1 (data/BI analytics) → P2 (data engineering/cloud/AI-ML) → P3
# (graduate software) so the freshest coverage runs first if a budget stops a
# run early. Sales / business development / BPO / support queries are never
# searched here.
DISCOVERY_SEARCH_GROUPS: dict[str, tuple[str, ...]] = {
    "p1_data_analytics": (
        "Data Analyst",
        "Data Analytics",
        "Power BI Analyst",
        "BI Analyst",
        "Business Intelligence Analyst",
        "MIS Analyst",
        "SQL Data Analyst",
        "Python Data Analyst",
    ),
    "p2_data_engineering_cloud_ai": (
        "Junior Data Engineer",
        "Data Engineer",
        "ETL Developer",
        "Cloud Engineer Trainee",
        "Machine Learning Trainee",
        "AI Engineer Fresher",
    ),
    "p3_graduate_software": (
        "Graduate Trainee",
        "Software Engineer",
    ),
}

DISCOVERY_EXTRA_SEARCH_TERMS: tuple[str, ...] = (
    DISCOVERY_SEARCH_GROUPS["p1_data_analytics"]
    + DISCOVERY_SEARCH_GROUPS["p2_data_engineering_cloud_ai"]
    + DISCOVERY_SEARCH_GROUPS["p3_graduate_software"]
)

# Preserved pre-E5-R19 fallback used only when preferences carry no titles.
DISCOVERY_FALLBACK_SEARCH_TERMS: tuple[str, ...] = (
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
)


class DiscoveryService:
    def __init__(
        self,
        state_manager: AgentStateManager,
        max_cards: int = 150,
        cancel_check: Optional[Any] = None,
    ):
        self.state_manager = state_manager
        settings = get_settings()
        self.adapter = NaukriAdapter(browser_type=settings.browser_type)
        self.current_run: Optional[DiscoveryRun] = None
        self.current_search: Optional[str] = None
        self._stop_requested = False
        self.max_cards = max_cards
        self.current_run_job_ids: set[int] = set()  # Track job IDs from current run
        # E5-R16: optional cooperative cancellation hook. The autonomous cycle
        # passes its run-token cancellation check so a Stop request interrupts
        # discovery at the next safe boundary instead of only after the whole
        # search/enrichment pass finishes.
        self.cancel_check = cancel_check

    def _should_stop(self) -> bool:
        """True when discovery must stop: explicit stop or external cancel."""
        if self._stop_requested:
            return True
        if self.cancel_check is None:
            return False
        try:
            if bool(self.cancel_check()):
                self._stop_requested = True
                logger.info("discovery_cancelled_by_run_stop")
                return True
        except Exception as exc:
            logger.warning(f"discovery cancellation check failed (continuing): {exc}")
        return False

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
                detail = getattr(self.adapter, "last_startup_error", None)
                error_message = "Failed to start browser session."
                if detail:
                    error_message = f"{error_message} {detail}"
                self._finalize_run(db, DISCOVERY_STATUS_FAILED, error_message)
                self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
                return

            if self._should_stop():
                self._abort_before_search(db, "Stopped by user.")
                return

            preferences = db.execute(select(JobPreference)).scalars().first()
            if not preferences:
                self._abort_before_search(db, "No job preferences found. Configure them first.")
                return

            search_terms = self._discovery_search_terms(preferences)
            locations = preferences.locations or []
            if not search_terms:
                self._abort_before_search(db, "No job titles configured.")
                return

            # E5-R8: search every configured location, not only locations[0].
            # Empty/blank names are dropped; an empty list still becomes a
            # single unfiltered (India-wide) search via the adapter fallback.
            search_locations = self._normalize_search_locations(locations)

            self.state_manager.transition_to(AgentState.SEARCHING)

            for term in search_terms:
                if self._should_stop():
                    break

                if not filtering_entered:
                    self.state_manager.transition_to(AgentState.FILTERING)
                    filtering_entered = True

                for location in search_locations:
                    if self._should_stop():
                        break

                    self.current_search = (
                        term if location is None else f"{term} in {location}"
                    )
                    self.current_run.searches_attempted += 1
                    db.commit()

                    jobs_before_term = self.current_run.jobs_discovered
                    seen_pages: set[int] = set()
                    term_yielded_any = False

                    try:
                        location_locations: list[str] = [] if location is None else [location]
                        async for job_data in self.adapter.search_jobs(term, location_locations):
                            if self._should_stop():
                                break

                            term_yielded_any = True
                            self._track_page_processed(db, job_data, seen_pages)
                            self.current_run.jobs_discovered += 1

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
                                # E5-R9: backfill application_mode on rediscovery
                                # when still unknown, reusing the same page visit
                                # path as new-job enrichment. Known modes are left
                                # alone so we never invent a new classification.
                                if (
                                    not getattr(existing_job, "application_mode", None)
                                    and job_data.get("url")
                                ):
                                    try:
                                        details_result = await self.adapter.fetch_job_details(
                                            job_data["url"]
                                        )
                                    except Exception as e:
                                        logger.debug(
                                            f"application_mode backfill failed for {job_data['url']}: {e}"
                                        )
                                        details_result = None
                                    if details_result:
                                        job_data.update(details_result)
                                self._refresh_duplicate_job(db, existing_job, job_data)
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

                            # The scan budget is applied to NEW distinct jobs, not
                            # to every card. A stream of already-known duplicates
                            # therefore can never starve fresh eligible jobs out of
                            # the discovery budget.
                            if self.current_run.new_jobs >= self.max_cards:
                                self._stop_requested = True
                                break

                        self._track_implicit_page(db, jobs_before_term, seen_pages)

                        # If this search term yielded no jobs and it's the first term,
                        # this indicates a navigation/selector failure (not just empty results)
                        if not term_yielded_any and self.current_run.jobs_discovered == 0:
                            location_label = location or "india"
                            logger.warning(
                                f"Search term '{term}' in '{location_label}' yielded no jobs "
                                "- possible navigation failure"
                            )
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

            if self._should_stop():
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

    @staticmethod
    def _discovery_search_terms(preferences: JobPreference) -> list[str]:
        """
        E5-R19: ordered, de-duplicated discovery queries.

        Targeted groups (DISCOVERY_SEARCH_GROUPS) run first so fresh coverage
        of under-searched preference families (BI/Power BI, SQL/Python
        analytics, junior data engineering/ETL, cloud trainee, AI/ML fresher,
        graduate software) is attempted before the already-saturated configured
        titles. Configured job_titles always remain in the list; the historical
        fallback list is used only when no titles are configured. Matching is
        case-insensitive so a configured title equal to a targeted term is not
        searched twice.
        """
        configured = list(getattr(preferences, "job_titles", None) or []) or list(
            DISCOVERY_FALLBACK_SEARCH_TERMS
        )
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in (*DISCOVERY_EXTRA_SEARCH_TERMS, *configured):
            term = " ".join(str(raw or "").split())
            if not term:
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(term)
        return ordered

    @staticmethod
    def _normalize_search_locations(locations: list[str] | None) -> list[str | None]:
        """
        Ordered, de-duplicated configured locations for E5-R8 multi-location search.

        Returns a list where each entry is a non-empty location name. An empty
        or all-blank input collapses to ``[None]`` so the caller still performs
        one India-wide search (adapter path-based fallback), preserving the
        pre-E5-R8 behaviour when no locations are configured.
        """
        ordered: list[str | None] = []
        seen: set[str] = set()
        for raw in locations or []:
            name = (raw or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(name)
        return ordered or [None]

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

    def _as_aware_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _refresh_duplicate_job(
        self, db: Session, existing_job: Job, job_data: dict[str, Any]
    ) -> None:
        """Refresh an already-known job without creating a duplicate.

        ``last_seen`` always advances. ``posted_at`` is only updated when the
        freshly observed, grounded date is newer than what is stored; unknown
        dates never overwrite a known one. ``application_mode`` is backfilled
        only when still NULL and the observed value is classifier-known.
        """
        existing_job.last_seen = utc_now()

        observed = job_data.get("posted_at")
        if isinstance(observed, datetime):
            observed = self._as_aware_utc(observed)
            current = self._as_aware_utc(existing_job.posted_at)
            if current is None or observed > current:
                existing_job.posted_at = observed

        if not getattr(existing_job, "application_mode", None):
            observed_mode = (
                self._normalize_optional_str(job_data.get("application_mode")) or ""
            ).upper()
            if observed_mode in ("NAUKRI_NATIVE", "EXTERNAL", "AMBIGUOUS"):
                existing_job.application_mode = observed_mode

        db.commit()

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

        # E5-R17: reject irrelevant roles before they are persisted, so the
        # dashboard, the queue and the application path never see sales /
        # BPO-voice / support / manufacturing postings that only look
        # technical in their title. This is the same shared check used by the
        # MatchEngine deterministic filter and the final safety gate.
        relevance_reason = irrelevant_role_reason(
            title,
            role_category=self._normalize_optional_str(job_data.get("role_category")),
            department=self._normalize_optional_str(job_data.get("department")),
            description=self._normalize_optional_str(job_data.get("description")),
        )
        if relevance_reason:
            logger.info(
                "Skipping irrelevant discovered job '%s' (%s): %s",
                title,
                self._normalize_optional_str(job_data.get("company")),
                relevance_reason,
            )
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

        # E5-R9: persist only classifier-known values; anything else stays NULL
        # so ranking treats it as unknown/ambiguous rather than inventing native.
        application_mode = (self._normalize_optional_str(job_data.get("application_mode")) or "").upper()
        if application_mode not in ("NAUKRI_NATIVE", "EXTERNAL", "AMBIGUOUS"):
            application_mode = None

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
            application_mode=application_mode,
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
            # E5-R19: reload the finalized run so its attributes stay readable
            # after the owning session closes below. Without this the status
            # endpoint hit an expired, detached instance and returned 500 for
            # every completed run.
            db.refresh(self.current_run)

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
