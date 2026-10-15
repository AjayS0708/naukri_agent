"""E5-R29: manual apply queue tests.

Covers the manual "Apply to Discovered Jobs" backend:

- Eligibility listing excludes protected / external / irrelevant /
  hard-filtered jobs, each with a reason, and never mutates anything.
- POST /start re-validates job ids, drops ineligible ones, and reuses the
  singleton cycle lock (409 on conflict, concurrent start blocked).
- The runner is invoked with the accepted ids and DiscoveryService is never
  touched (manual apply never runs discovery).
- Stop cancels at a safe boundary and lands the run CANCELLED.
- AMBIGUOUS / NULL-mode jobs stay eligible for live re-verification (never
  forced native); EXTERNAL-mode jobs are never attempted.
- The scheduler's apply phase yields to the cycle lock instead of starting a
  second browser session.
- The autonomous-cycle status endpoint hides manual-apply last runs.

Browser behavior is mocked throughout: no live Naukri pages, no apply
clicks, no credential or application-record changes beyond in-memory
fixtures.
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.application import Application
from backend.models.cycle_run import CycleRunControl
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.schemas.application import ApplicationStatus
from backend.services.autonomous_cycle.coordinator import (
    CONTROL_ROW_ID,
    CycleCoordinator,
)
from backend.services.manual_apply.service import ManualApplyService

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(autocommit=False, autoflush=False, bind=engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def confirmed_profile(db_session: Session):
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="resume.pdf",
        sha256="abc123",
        file_size=1000,
        text_length=5000,
        is_current=True,
    )
    db_session.add(resume)
    db_session.commit()
    profile = Profile(
        resume_id=resume.id,
        status="CONFIRMED",
        confirmed=True,
        data={
            "name": "Test User",
            "skills": ["Python", "SQL"],
            "location": "Bengaluru",
        },
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preferences(db_session: Session):
    preferences = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Data Analyst", "Software Engineer"],
        employment_types=["Full-time"],
        min_salary_lpa=4.0,
        aggressiveness="BALANCED",
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


def _make_job(
    db_session: Session,
    index: int,
    *,
    title: str = "Data Analyst",
    application_mode: str | None = "NAUKRI_NATIVE",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r29job{index}",
        url=f"https://www.naukri.com/e5r29job{index}",
        title=title,
        company=f"Company {index}",
        description="Python and SQL reporting role",
        location="Bengaluru",
        salary="5-7 LPA",
        salary_max=7.0,
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode=application_mode,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _seed_eligible_job(db: Session, index: int = 1) -> Job:
    """Seed a confirmed profile, preferences, and one eligible job into the
    given session (used by API tests that share the global test DB)."""
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="resume.pdf",
        sha256="abc123",
        file_size=1000,
        text_length=5000,
        is_current=True,
    )
    db.add(resume)
    db.commit()
    db.add(
        Profile(
            resume_id=resume.id,
            status="CONFIRMED",
            confirmed=True,
            data={"name": "Test User", "skills": ["Python", "SQL"], "location": "Bengaluru"},
        )
    )
    db.add(
        JobPreference(
            locations=["Bengaluru", "Remote"],
            job_titles=["Data Analyst", "Software Engineer"],
            employment_types=["Full-time"],
            min_salary_lpa=4.0,
            aggressiveness="BALANCED",
        )
    )
    db.commit()
    return _make_job(db, index)


@pytest.fixture(autouse=True)
def reset_cycle_control(db):
    """Fresh singleton control row per test (in the global test DB the API
    client uses). The background task of a prior API test can leave the row
    RUNNING with a live PID (the pytest process), so orphan adoption cannot
    clean it up — reset it explicitly."""
    row = db.get(CycleRunControl, CONTROL_ROW_ID)
    if row is not None:
        db.delete(row)
        db.commit()


class TestManualApplyEligibility:
    def test_eligible_listing_marks_native_job(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        payload = ManualApplyService(db_session).list_eligible()
        assert payload["total"] == 1
        assert payload["eligible_count"] == 1
        item = payload["items"][0]
        assert item["job_id"] == job.id
        assert item["eligible"] is True
        assert item["exclusion_reason"] is None

    def test_external_job_excluded_with_reason(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        _make_job(db_session, 1, application_mode="EXTERNAL")
        payload = ManualApplyService(db_session).list_eligible()
        item = payload["items"][0]
        assert item["eligible"] is False
        assert item["exclusion_reason"] == "external_application"

    def test_protected_job_excluded_with_reason(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        db_session.add(
            Application(job_id=job.id, status=ApplicationStatus.APPLIED.value)
        )
        db_session.commit()
        payload = ManualApplyService(db_session).list_eligible()
        item = payload["items"][0]
        assert item["eligible"] is False
        assert item["exclusion_reason"] == "application_history"
        assert item["application_status"] == "APPLIED"

    def test_irrelevant_title_excluded(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        _make_job(db_session, 1, title="BPO Voice Executive")
        payload = ManualApplyService(db_session).list_eligible()
        item = payload["items"][0]
        assert item["eligible"] is False
        assert item["exclusion_reason"].startswith("not_relevant")

    def test_unconfirmed_profile_excludes_everything(
        self, db_session: Session, job_preferences
    ) -> None:
        _make_job(db_session, 1)
        payload = ManualApplyService(db_session).list_eligible()
        assert payload["profile_confirmed"] is False
        assert payload["eligible_count"] == 0
        assert payload["items"][0]["exclusion_reason"] == "profile_not_confirmed"

    def test_only_eligible_filter_drops_ineligible_items(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        _make_job(db_session, 1)
        _make_job(db_session, 2, application_mode="EXTERNAL")
        payload = ManualApplyService(db_session).list_eligible(only_eligible=True)
        assert payload["total"] == 2
        assert len(payload["items"]) == 1
        assert payload["items"][0]["eligible"] is True

    def test_ambiguous_and_null_mode_stay_eligible(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        """AMBIGUOUS / unclassified jobs are eligible for live re-verification
        (the runner never forces native without Apply-button evidence)."""
        _make_job(db_session, 1, application_mode="AMBIGUOUS")
        _make_job(db_session, 2, application_mode=None)
        payload = ManualApplyService(db_session).list_eligible(only_eligible=True)
        assert payload["eligible_count"] == 2

    def test_listing_is_read_only(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        _make_job(db_session, 1)
        ManualApplyService(db_session).list_eligible()
        rows = db_session.execute(select(Application)).scalars().all()
        assert rows == []


class TestManualApplyValidate:
    def test_drops_unknown_and_ineligible_ids(
        self, db_session: Session, confirmed_profile, job_preferences
    ) -> None:
        good = _make_job(db_session, 1)
        external = _make_job(db_session, 2, application_mode="EXTERNAL")
        accepted, dropped = ManualApplyService(db_session).validate_job_ids(
            [good.id, external.id, 999999]
        )
        assert accepted == [good.id]
        assert set(dropped) == {external.id, 999999}

    def test_empty_input_returns_empty(self, db_session: Session) -> None:
        accepted, dropped = ManualApplyService(db_session).validate_job_ids([])
        assert accepted == []
        assert dropped == []


class TestManualApplyApi:
    def test_manual_apply_routes_registered_on_app(self) -> None:
        """Regression for the live-dashboard "Loading queue…" failure.

        An app that never registers the manual-apply router answers every
        queue request with 404, which the dashboard renders as a generic
        error and an empty queue. Assert the served app exposes all four
        routes so a missing/renamed registration fails in CI, not on the
        running server.
        """
        from backend.main import app

        paths = app.openapi()["paths"]
        for path in (
            "/api/manual-apply/eligible",
            "/api/manual-apply/start",
            "/api/manual-apply/status",
            "/api/manual-apply/stop",
        ):
            assert path in paths, f"missing route: {path}"
        assert "get" in paths["/api/manual-apply/eligible"]
        assert "post" in paths["/api/manual-apply/start"]
        assert "get" in paths["/api/manual-apply/status"]
        assert "post" in paths["/api/manual-apply/stop"]

    def test_eligible_endpoint_read_only(self, client: TestClient) -> None:
        response = client.get("/api/manual-apply/eligible")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {
            "items",
            "total",
            "eligible_count",
            "profile_confirmed",
            "preferences_present",
        }

    def test_start_conflicts_with_running_cycle(self, client: TestClient) -> None:
        async def slow_cycle():
            await asyncio.sleep(0.4)
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}

        with patch(
            "backend.api.routes.autonomous_cycle.AutonomousCycle"
        ) as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_cycle
            mock_cycle.return_value = mock_instance
            client.post("/api/autonomous-cycle/run", json={})

            response = client.post(
                "/api/manual-apply/start", json={"job_ids": [1]}
            )
            assert response.status_code == 409
            assert (
                response.json()["detail"]["code"]
                == "APPLY_PROCESS_ALREADY_RUNNING"
            )

    def test_concurrent_manual_starts_blocked(self, client: TestClient, db) -> None:
        job = _seed_eligible_job(db)

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(0.4)
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}

        with patch(
            "backend.services.manual_apply.service.ApplicationRunner"
        ) as mock_runner:
            mock_instance = AsyncMock()
            mock_instance.run_applications = slow_run
            mock_instance.reconcile_history = AsyncMock(return_value=None)
            mock_instance.close_session = AsyncMock(return_value=None)
            mock_runner.return_value = mock_instance

            r1 = client.post("/api/manual-apply/start", json={"job_ids": [job.id]})
            assert r1.status_code == 200
            assert r1.json()["status"] == "RUNNING"

            r2 = client.post("/api/manual-apply/start", json={"job_ids": [job.id]})
            assert r2.status_code == 409

    def test_start_with_no_eligible_jobs_releases_lock(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/manual-apply/start", json={"job_ids": [424242]})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "NO_ELIGIBLE_JOBS"
        assert body["run_token"] is None
        assert body["accepted_job_ids"] == []
        assert 424242 in body["dropped_job_ids"]

        # Lock must be free again for the next run.
        status = client.get("/api/manual-apply/status").json()
        assert status["active_state"] == "IDLE"
        assert status["lock_held"] is False

    def test_start_invokes_runner_never_discovery(
        self, client: TestClient, db
    ) -> None:
        job = _seed_eligible_job(db)

        async def fake_run_applications(job_ids, dry_run=False):
            return {
                "total": len(job_ids),
                "processed": len(job_ids),
                "applied": 1,
                "submitted_unconfirmed": 0,
                "skipped": 0,
                "needs_attention": 0,
                "external": 0,
                "failed": 0,
                "errors": 0,
                "auth_required": 0,
                "dry_run": 0,
                "dry_run_mode": dry_run,
                "attempts_started": 1,
            }

        with patch(
            "backend.services.manual_apply.service.ApplicationRunner"
        ) as mock_runner, patch(
            "backend.services.discovery.service.DiscoveryService"
        ) as mock_discovery:
            mock_instance = AsyncMock()
            mock_instance.run_applications = AsyncMock(side_effect=fake_run_applications)
            mock_instance.reconcile_history = AsyncMock(return_value=None)
            mock_instance.close_session = AsyncMock(return_value=None)
            mock_runner.return_value = mock_instance

            response = client.post(
                "/api/manual-apply/start", json={"job_ids": [job.id]}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "RUNNING"
            assert body["accepted_job_ids"] == [job.id]

            # Wait for the background task to finish.
            deadline = time.time() + 3
            while time.time() < deadline:
                status = client.get("/api/manual-apply/status").json()
                if status["active_state"] == "IDLE":
                    break
                time.sleep(0.05)

            mock_instance.run_applications.assert_awaited_once()
            called_ids = mock_instance.run_applications.await_args.args[0]
            assert called_ids == [job.id]
            mock_discovery.assert_not_called()

    def test_stop_cancels_active_manual_run(
        self, client: TestClient, db
    ) -> None:
        job = _seed_eligible_job(db)

        async def slow_run_applications(job_ids, dry_run=False):
            await asyncio.sleep(0.4)
            return {
                "total": len(job_ids),
                "processed": len(job_ids),
                "applied": 0,
                "submitted_unconfirmed": 0,
                "skipped": 0,
                "needs_attention": 0,
                "external": 0,
                "failed": 0,
                "errors": 0,
                "auth_required": 0,
                "dry_run": 0,
                "dry_run_mode": dry_run,
                "attempts_started": 0,
            }

        with patch(
            "backend.services.manual_apply.service.ApplicationRunner"
        ) as mock_runner:
            mock_instance = AsyncMock()
            mock_instance.run_applications = slow_run_applications
            mock_instance.reconcile_history = AsyncMock(return_value=None)
            mock_instance.close_session = AsyncMock(return_value=None)
            mock_runner.return_value = mock_instance

            start = client.post(
                "/api/manual-apply/start", json={"job_ids": [job.id]}
            )
            assert start.status_code == 200
            run_token = start.json()["run_token"]

            stop = client.post(
                "/api/manual-apply/stop", json={"run_token": run_token}
            )
            assert stop.status_code == 200
            assert stop.json()["cancel_requested"] is True

            deadline = time.time() + 3
            while time.time() < deadline:
                status = client.get("/api/manual-apply/status").json()
                if status["active_state"] == "IDLE":
                    break
                time.sleep(0.05)

            last = client.get("/api/manual-apply/status").json()["last_manual_run"]
            assert last is not None
            assert last["status"] == "CANCELLED"

    def test_stop_when_idle_idempotent(self, client: TestClient) -> None:
        response = client.post("/api/manual-apply/stop", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["cancel_requested"] is False
        assert body["active_state"] == "IDLE"

    def test_status_structure(self, client: TestClient) -> None:
        response = client.get("/api/manual-apply/status")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {
            "active_state",
            "lock_held",
            "active_run",
            "last_manual_run",
            "pending_question_available",
        }

    def test_unknown_field_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/manual-apply/start",
            json={"job_ids": [1], "force_external": True},
        )
        assert response.status_code == 422

    def test_empty_job_ids_rejected(self, client: TestClient) -> None:
        response = client.post("/api/manual-apply/start", json={"job_ids": []})
        assert response.status_code == 422


class TestAutonomousStatusHidesManualRuns:
    def test_manual_last_run_hidden_from_cycle_panel(self, client: TestClient) -> None:
        """The autonomous-cycle panel must not display a manual apply run as
        if it were an autonomous cycle (no discovery ever ran)."""
        with patch(
            "backend.api.routes.autonomous_cycle.coordinator.snapshot"
        ) as mock_snapshot:
            mock_snapshot.return_value = {
                "active_state": "IDLE",
                "lock_held": False,
                "active_run": None,
                "last_run": {
                    "run_id": None,
                    "status": "COMPLETED",
                    "stats": {"run_kind": "MANUAL_APPLY", "applied": 2},
                    "error": None,
                    "cancel_requested": False,
                },
            }
            response = client.get("/api/autonomous-cycle/status")
        assert response.status_code == 200
        assert response.json()["last_run"] is None

    def test_scheduled_last_run_hidden_from_cycle_panel(self, client: TestClient) -> None:
        with patch(
            "backend.api.routes.autonomous_cycle.coordinator.snapshot"
        ) as mock_snapshot:
            mock_snapshot.return_value = {
                "active_state": "IDLE",
                "lock_held": False,
                "active_run": None,
                "last_run": {
                    "run_id": None,
                    "status": "COMPLETED",
                    "stats": {"run_kind": "SCHEDULED", "applied": 0},
                    "error": None,
                    "cancel_requested": False,
                },
            }
            response = client.get("/api/autonomous-cycle/status")
        assert response.status_code == 200
        assert response.json()["last_run"] is None


class TestSchedulerLockGate:
    def test_scheduler_apply_skipped_when_lock_held(
        self, db_session: Session
    ) -> None:
        from backend.services.scheduler.service import SchedulerService
        from backend.services.agent_state import AgentStateManager

        coordinator = CycleCoordinator()
        acquired, token, _ = coordinator.try_acquire(db=db_session)
        assert acquired

        try:
            service = SchedulerService(
                state_manager=AgentStateManager(),
                discovery_service=None,
            )
            stats = asyncio.run(service._invoke_application_runner(db_session))
            assert stats.get("skipped_lock_held") is True
            assert stats["candidates"] == 0
        finally:
            coordinator.complete(
                token, {"status": "COMPLETED", "run_id": None, "stats": {}}, db=db_session
            )

    def test_scheduler_releases_lock_after_apply(
        self, db_session: Session
    ) -> None:
        from backend.services.scheduler.service import SchedulerService
        from backend.services.agent_state import AgentStateManager

        async def fake_run_applications(job_ids, dry_run=False):
            return {
                "applied": 0,
                "skipped": 0,
                "needs_attention": 0,
                "failed": 0,
            }

        with patch(
            "backend.services.scheduler.service.ApplicationRunner"
        ) as mock_runner:
            mock_instance = AsyncMock()
            mock_instance.run_applications = fake_run_applications
            mock_runner.return_value = mock_instance

            service = SchedulerService(
                state_manager=AgentStateManager(),
                discovery_service=None,
            )
            asyncio.run(service._invoke_application_runner(db_session))

        coordinator = CycleCoordinator()
        snapshot = coordinator.snapshot(db=db_session)
        assert snapshot["active_state"] == "IDLE"
        assert snapshot["lock_held"] is False
        assert snapshot["last_run"]["stats"]["run_kind"] == "SCHEDULED"
