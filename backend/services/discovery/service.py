import asyncio
from datetime import datetime
from typing import Optional
import urllib.parse
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.services.naukri.adapter import NaukriAdapter
from backend.services.matching.engine import MatchEngine
from backend.core.logging import get_logger

logger = get_logger(__name__)


class DiscoveryService:
    def __init__(self, state_manager: AgentStateManager):
        self.state_manager = state_manager
        self.adapter = NaukriAdapter()
        self.current_run: Optional[DiscoveryRun] = None
        self.current_search: Optional[str] = None
        self._stop_requested = False

    @property
    def is_running(self) -> bool:
        return self.state_manager.current_state in [AgentState.RUNNING, AgentState.SEARCHING]

    async def stop_safely(self):
        """Request a graceful stop to the discovery process."""
        self._stop_requested = True
        logger.info("discovery_stop_requested")

    async def run_discovery(self, db: Session):
        """
        Orchestrates the discovery flow fetching jobs using the adapter,
        normalizing/saving them, and passing them to Phase 4 Match Engine.
        """
        if self.is_running:
            return

        self._stop_requested = False
        self.state_manager.transition_to(AgentState.RUNNING)
        
        # Create run record
        run = DiscoveryRun(status=AgentState.RUNNING)
        db.add(run)
        db.commit()
        db.refresh(run)
        self.current_run = run

        match_engine = MatchEngine(db)
        
        try:
            # 1. Start browser via adapter
            started = await self.adapter.start_session()
            if not started:
                self._handle_failure("Failed to start browser session.", AgentState.CRITICAL_ERROR, db)
                return

            if self._stop_requested:
                self._handle_failure("Stopped by user.", AgentState.STOPPED, db)
                return

            # 2. Get preferences
            preferences = db.execute(select(JobPreference)).scalars().first()
            if not preferences:
                self._handle_failure("No job preferences found. Configure them first.", AgentState.STOPPED, db)
                return

            search_terms = preferences.job_titles or []
            locations = preferences.locations or []
            if not search_terms:
                self._handle_failure("No job titles configured.", AgentState.STOPPED, db)
                return

            self.state_manager.transition_to(AgentState.SEARCHING)

            for term in search_terms:
                if self._stop_requested:
                    break

                self.current_search = term
                self.current_run.searches_attempted += 1
                db.commit()

                try:
                    # 3. Perform search using the adapter (generator)
                    async for job_data in self.adapter.search_jobs(term, locations):
                        if self._stop_requested:
                            break
                            
                        self.current_run.jobs_discovered += 1
                        
                        # 4. Deduplicate (Phase 5 requirement check 3 things)
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

                        if existing_job:
                            self.current_run.duplicate_jobs += 1
                            existing_job.last_seen = datetime.utcnow()
                            db.commit()
                            continue
                            
                        self.current_run.new_jobs += 1
                        
                        # Fetch full description if missing but we have URL (for Phase 5)
                        if not job_data.get("description") and job_data.get("url"):
                             full_desc = await self.adapter.fetch_job_description(job_data["url"])
                             job_data["description"] = full_desc

                        # 5. Persist Job
                        new_job = Job(
                            platform=self.adapter.platform_name,
                            external_job_id=job_data.get("external_job_id") or "tmp_" + str(hash(job_data.get("url"))),
                            url=job_data.get("url", ""),
                            title=job_data.get("title", ""),
                            company=job_data.get("company", ""),
                            description=job_data.get("description"),
                            location=job_data.get("location"),
                            salary=job_data.get("salary"),
                            experience=job_data.get("experience"),
                            employment_type=job_data.get("employment_type"),
                            source=term
                        )
                        db.add(new_job)
                        db.commit()
                        db.refresh(new_job)

                        # 6. Pass to Match Engine (Phase 4 integration)
                        match_engine.evaluate_job(new_job)
                        db.commit()
                        
                except Exception as e:
                    logger.error(f"Error during search for {term}: {str(e)}", exc_info=True)
                    self.current_run.errors += 1
                    
                    # Handle specific internal halt conditions like CAPTCHA/AUTH
                    if "auth" in str(e).lower() or "login" in str(e).lower():
                        self._handle_failure("Naukri login required.", AgentState.AUTH_REQUIRED, db)
                        return
                    if "security" in str(e).lower() or "captcha" in str(e).lower():
                        self._handle_failure("Security verification required.", AgentState.SECURITY_REQUIRED, db)
                        return

            # Graceful finish
            final_status = AgentState.STOPPED if self._stop_requested else AgentState.IDLE
            self._handle_failure(None, final_status, db)

        except Exception as e:
            logger.error(f"Discovery run failed: {str(e)}", exc_info=True)
            self._handle_failure(f"Critical error: {str(e)}", AgentState.CRITICAL_ERROR, db)
        finally:
            await self.adapter.stop_session()
            self.current_search = None


    def _handle_failure(self, error_message: str | None, state: AgentState, db: Session):
        if self.current_run:
            self.current_run.status = state
            self.current_run.completed_at = datetime.utcnow()
            if error_message:
                self.current_run.error_message = error_message
            db.commit()
        
        # State transition according to allowed rules from AgentStateManager
        # Running -> Stopped
        # Searching -> Filter -> PAUSED/CRITICAL ERROR. 
        # For simplicity, if we need IDLE, we must go to STOPPED first
        try:
             self.state_manager.transition_to(state)
        except ValueError:
             try:
                 self.state_manager.transition_to(AgentState.STOPPED)
                 self.state_manager.transition_to(AgentState.IDLE)
             except Exception as e:
                 logger.error(f"State transition fallback failed: {e}")
