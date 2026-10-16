"""E5-R30: manual apply queue API — pagination, search, fallback parity.

Covers the Phase 5/7 behaviors:

- ``/manual-apply/eligible`` server-side pagination (limit/offset) and search
  (q) with counts over the whole search-matched set, plus
  ``eligible_job_ids`` covering every eligible id (not just the page).
- Expired listings are excluded with the ``listing_expired`` reason.
- The manual run persists the same deterministic-fallback analysis the
  autonomous cycle writes before invoking the runner (the root cause of the
  first real manual run's "No AI analysis available" skips), and drops
  pre-run jobs that no longer pass the shared gates with a recorded reason.
- Structured API errors: unknown endpoint 404, conflict 409.
- The last manual run survives a restart via the persisted control row.
"""
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.cycle_run import CycleRunControl
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.autonomous_cycle.coordinator import CONTROL_ROW_ID
from backend.services.manual_apply.service import ManualApplyService

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def reset_cycle_control(db):
    """Fresh singleton control row per test (shared global test DB)."""
    row = db.get(CycleRunControl, CONTROL_ROW_ID)
    if row is not None:
        db.delete(row)
        db.commit()


def _seed(db, index: int, *, title: str = "Data Analyst", mode: str | None = "NAUKRI_NATIVE", status: str = "DISCOVERED") -> Job:
    """Confirmed profile + preferences + one job (idempotent context seed)."""
    if db.execute(select(Profile)).scalars().first() is None:
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
    if db.execute(select(JobPreference)).scalars().first() is None:
        db.add(
            JobPreference(
                locations=["Bengaluru", "Remote"],
                job_titles=["Data Analyst", "Software Engineer"],
                employment_types=["Full-time"],
                min_salary_lpa=3.0,
                aggressiveness="BALANCED",
            )
        )
    db.commit()
    job = Job(
        platform="naukri",
        external_job_id=f"e5r30api{index}",
        url=f"https://www.naukri.com/e5r30api{index}",
        title=title,
        company=f"Company {index}",
        description="Python and SQL reporting role",
        location="Bengaluru",
        salary="5-7 LPA",
        salary_max=7.0,
        experience="0-2 years",
        employment_type="Full-time",
        status=status,
        application_mode=mode,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class TestEligiblePaginationAndSearch:
    def test_pagination_and_eligible_job_ids(self, client: TestClient, db) -> None:
        job_a = _seed(db, 1, title="Data Analyst Alpha")
        job_b = _seed(db, 2, title="Data Analyst Beta")
        job_c = _seed(db, 3, title="Software Engineer Gamma")
        _seed(db, 4, title="Voice Executive", mode="EXTERNAL")

        page = client.get("/api/manual-apply/eligible?limit=2&offset=0")
        assert page.status_code == 200
        data = page.json()
        # Counts describe the whole set, the page only slices items.
        assert data["total"] == 4
        assert data["eligible_count"] == 3
        # Every eligible id is returned regardless of pagination.
        assert sorted(data["eligible_job_ids"]) == sorted(
            [job_a.id, job_b.id, job_c.id]
        )
        assert len(data["items"]) == 2

        next_page = client.get("/api/manual-apply/eligible?limit=2&offset=2")
        assert next_page.status_code == 200
        page_two_ids = [item["job_id"] for item in next_page.json()["items"]]
        page_one_ids = [item["job_id"] for item in data["items"]]
        # Stable ordering: no duplicates, no gaps across pages.
        assert not set(page_one_ids) & set(page_two_ids)
        assert len(page_two_ids) == 2

    def test_server_side_search(self, client: TestClient, db) -> None:
        _seed(db, 1, title="Data Analyst Alpha")
        _seed(db, 2, title="Data Analyst Beta")
        _seed(db, 3, title="Software Engineer Gamma")

        found = client.get("/api/manual-apply/eligible?q=data").json()
        assert found["total"] == 2
        assert found["eligible_count"] == 2
        assert all("Data Analyst" in item["title"] for item in found["items"])

        page = client.get("/api/manual-apply/eligible?q=data&limit=1&offset=1").json()
        assert len(page["items"]) == 1
        # Counts stay the whole matched set even when paging inside a search.
        assert page["total"] == 2
        assert page["eligible_count"] == 2

        none = client.get("/api/manual-apply/eligible?q=zzz-no-match").json()
        assert none["total"] == 0
        assert none["items"] == []
        assert none["eligible_job_ids"] == []

    def test_only_eligible_with_search(self, client: TestClient, db) -> None:
        _seed(db, 1, title="Data Analyst Alpha")
        _seed(db, 2, title="Data Analyst Beta", mode="EXTERNAL")

        data = client.get(
            "/api/manual-apply/eligible?q=data&only_eligible=true"
        ).json()
        assert data["total"] == 2
        assert data["eligible_count"] == 1
        assert [i["job_id"] for i in data["items"]] == [
            item["job_id"] for item in data["items"] if item["eligible"]
        ]

    def test_expired_job_excluded_with_reason(self, client: TestClient, db) -> None:
        expired = _seed(db, 1, status="EXPIRED")
        live = _seed(db, 2)

        data = client.get("/api/manual-apply/eligible").json()
        by_id = {item["job_id"]: item for item in data["items"]}
        assert by_id[expired.id]["eligible"] is False
        assert by_id[expired.id]["exclusion_reason"] == "listing_expired"
        assert by_id[live.id]["eligible"] is True


class TestFallbackAnalysisParity:
    def test_fallback_analysis_created_for_no_analysis_job(self, db) -> None:
        job = _seed(db, 1)
        service = ManualApplyService(db)

        ready = service._ensure_fallback_analyses(db, [job.id])

        assert ready == [job.id]
        analysis = db.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
        ).scalars().first()
        assert analysis is not None
        assert analysis.model == "deterministic_fallback"
        assert analysis.recommendation == "APPLY"
        assert analysis.suspicious is False
        assert analysis.short_reason == "Deterministic filter pass (no AI analysis)"
        # Idempotent: a second pass must not duplicate or alter anything.
        again = service._ensure_fallback_analyses(db, [job.id])
        assert again == [job.id]
        rows = (
            db.execute(select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id))
            .scalars()
            .all()
        )
        assert len(rows) == 1

    def test_existing_ai_analysis_is_reused_not_overwritten(self, db) -> None:
        job = _seed(db, 1)
        db.add(
            JobAnalysisModel(
                job_id=job.id,
                match_score=91,
                role_match=True,
                skill_match=True,
                experience_match=True,
                location_match=True,
                salary_match=True,
                job_quality="GOOD",
                duplicate_probability=0.0,
                suspicious=False,
                recommendation="APPLY",
                short_reason="AI analysis",
                model="gemini-2.0-flash",
                prompt_version="v7",
            )
        )
        db.commit()

        ready = ManualApplyService(db)._ensure_fallback_analyses(db, [job.id])

        assert ready == [job.id]
        analysis = db.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
        ).scalars().one()
        assert analysis.match_score == 91
        assert analysis.model == "gemini-2.0-flash"

    def test_run_persists_fallback_before_invoking_runner(
        self, client: TestClient, db
    ) -> None:
        job = _seed(db, 1)
        seen: dict = {}

        async def fake_run_applications(job_ids, dry_run=False):
            from backend.database import database as database_module

            session = database_module.SessionLocal()
            try:
                seen["analysis"] = (
                    session.execute(
                        select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
                    )
                    .scalars()
                    .first()
                )
            finally:
                session.close()
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
                "attempts_started": 0,
            }

        with patch(
            "backend.services.manual_apply.service.ApplicationRunner"
        ) as mock_runner:
            mock_instance = AsyncMock()
            mock_instance.run_applications = AsyncMock(side_effect=fake_run_applications)
            mock_instance.reconcile_history = AsyncMock(return_value=None)
            mock_instance.close_session = AsyncMock(return_value=None)
            mock_runner.return_value = mock_instance

            response = client.post("/api/manual-apply/start", json={"job_ids": [job.id]})
            assert response.status_code == 200
            assert response.json()["accepted_job_ids"] == [job.id]

            deadline = time.time() + 3
            while time.time() < deadline:
                if client.get("/api/manual-apply/status").json()["active_state"] == "IDLE":
                    break
                time.sleep(0.05)

            mock_instance.run_applications.assert_awaited_once()
            # The runner received the job only AFTER the fallback analysis
            # was persisted (this is what the first real manual run lacked).
            assert seen.get("analysis") is not None
            assert seen["analysis"].model == "deterministic_fallback"

    def test_preflight_drop_recorded_when_context_unavailable(self, db) -> None:
        job = _seed(db, 1)
        # Remove the context so the defensive drop path runs.
        for profile in db.execute(select(Profile)).scalars().all():
            db.delete(profile)
        db.commit()

        ready = ManualApplyService(db)._ensure_fallback_analyses(db, [job.id])

        assert ready == []
        row = db.execute(
            select(Application).where(Application.job_id == job.id)
        ).scalars().one()
        assert row.status == "SKIPPED"
        assert "Profile or preferences unavailable" in (row.skip_reason or "")


class TestStructuredApiErrors:
    def test_unknown_endpoint_is_404_with_detail(self, client: TestClient) -> None:
        response = client.get("/api/manual-apply/no-such-endpoint")
        assert response.status_code == 404
        # The frontend maps `detail` (or a status fallback) to a message;
        # never a stack trace.
        body = response.json()
        assert isinstance(body.get("detail"), str)

    def test_conflict_is_409_with_structured_code(self, client: TestClient, db) -> None:
        job = _seed(db, 1)

        async def slow_run(*args, **kwargs):
            import asyncio

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

            first = client.post("/api/manual-apply/start", json={"job_ids": [job.id]})
            assert first.status_code == 200
            second = client.post("/api/manual-apply/start", json={"job_ids": [job.id]})
            assert second.status_code == 409
            detail = second.json()["detail"]
            assert detail["code"] == "APPLY_PROCESS_ALREADY_RUNNING"
            assert isinstance(detail["message"], str)

            deadline = time.time() + 3
            while time.time() < deadline:
                if client.get("/api/manual-apply/status").json()["active_state"] == "IDLE":
                    break
                time.sleep(0.05)


class TestLastRunSurvivesRestart:
    def test_status_falls_back_to_persisted_last_result(
        self, client: TestClient, db
    ) -> None:
        import backend.services.manual_apply.service as manual_module

        # Simulate a process restart: the in-process summary is gone.
        manual_module._last_manual_run = None

        row = db.get(CycleRunControl, CONTROL_ROW_ID)
        if row is None:
            from backend.services.autonomous_cycle.coordinator import coordinator

            coordinator.ensure_row(db)
            row = db.get(CycleRunControl, CONTROL_ROW_ID)
        row.last_result = {
            "run_id": None,
            "status": "COMPLETED",
            "started_at": "2026-10-15T15:31:03+00:00",
            "completed_at": "2026-10-15T15:32:47+00:00",
            "stats": {
                "run_kind": "MANUAL_APPLY",
                "requested": 23,
                "processed": 23,
                "applied": 1,
                "skipped": 19,
                "needs_attention": 4,
            },
            "error": None,
        }
        row.run_token = "cycle-previous"
        db.commit()

        data = client.get("/api/manual-apply/status").json()
        last = data["last_manual_run"]
        assert last is not None
        assert last["status"] == "COMPLETED"
        assert last["stats"]["run_kind"] == "MANUAL_APPLY"
        assert last["stats"]["applied"] == 1
