"""
Checkpoint E1 — Tests for GET /api/dashboard/summary and GET /api/dashboard/recent-applications.

These tests verify:
- Correct response schema
- Correct behaviour with empty database
- Correct counts from populated database
- No secrets exposed in any response
- Endpoints are read-only (no state mutations)
"""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.profile import Profile, Resume


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_job(db: Session, *, title: str = "Data Analyst", company: str = "Acme Corp") -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"test-{title}-{company}-{id(title)}",
        url="https://www.naukri.com/job-listings/test",
        title=title,
        company=company,
        industry="IT Services & Consulting",
        discovered_at=datetime.now(UTC),
    )
    db.add(job)
    db.flush()
    return job


def _make_application(
    db: Session,
    job: Job,
    status: str = "APPLIED",
    method: str | None = "NAUKRI_NATIVE",
    needs_attention: bool | None = None,
) -> Application:
    app = Application(
        job_id=job.id,
        status=status,
        application_method=method,
        applied_at=datetime.now(UTC) if status == "APPLIED" else None,
        needs_attention=needs_attention if needs_attention is not None else status == "NEEDS_ATTENTION",
    )
    db.add(app)
    db.flush()
    return app


def _make_discovery_run(db: Session, *, jobs_discovered: int = 50, status: str = "COMPLETED") -> DiscoveryRun:
    run = DiscoveryRun(
        status=status,
        jobs_discovered=jobs_discovered,
        new_jobs=10,
        pages_processed=5,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    return run


# ── Dashboard summary — empty database ───────────────────────────────────────

class TestDashboardSummaryEmpty:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 200

    def test_schema_keys_present(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/summary").json()
        assert "discovery" in data
        assert "applications" in data
        assert "profile" in data

    def test_empty_discovery_has_zero_counts(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/summary").json()
        assert data["discovery"]["total_runs"] == 0
        assert data["discovery"]["jobs_discovered"] == 0

    def test_empty_applications_has_zero_counts(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/summary").json()
        apps = data["applications"]
        assert apps["total"] == 0
        assert apps["applied"] == 0
        assert apps["needs_attention"] == 0
        assert apps["skipped"] == 0

    def test_empty_profile_returns_empty_status(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/summary").json()
        assert data["profile"]["status"] == "EMPTY"
        assert data["profile"]["confirmed"] is False


# ── Dashboard summary — with data ────────────────────────────────────────────

class TestDashboardSummaryWithData:
    def test_discovery_counts_reflect_db(self, client: TestClient, db: Session) -> None:
        _make_discovery_run(db, jobs_discovered=103)
        db.commit()

        data = client.get("/api/dashboard/summary").json()
        assert data["discovery"]["jobs_discovered"] == 103
        assert data["discovery"]["total_runs"] == 1

    def test_application_counts_reflect_db(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        _make_application(db, job, status="APPLIED")
        _make_application(db, job, status="SKIPPED")
        _make_application(db, job, status="NEEDS_ATTENTION")
        _make_application(db, job, status="EXTERNAL_APPLICATION")
        db.commit()

        data = client.get("/api/dashboard/summary").json()
        apps = data["applications"]
        assert apps["total"] == 4
        assert apps["applied"] == 1
        assert apps["skipped"] == 1
        assert apps["needs_attention"] == 1
        assert apps["external_application"] == 1

    def test_multiple_discovery_runs_count(self, client: TestClient, db: Session) -> None:
        _make_discovery_run(db)
        _make_discovery_run(db)
        _make_discovery_run(db)
        db.commit()

        data = client.get("/api/dashboard/summary").json()
        assert data["discovery"]["total_runs"] == 3


# ── Recent applications — empty database ─────────────────────────────────────

class TestRecentApplicationsEmpty:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/dashboard/recent-applications")
        assert response.status_code == 200

    def test_empty_list_when_no_applications(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/recent-applications").json()
        assert data["applications"] == []
        assert data["total"] == 0


# ── Recent applications — with data ──────────────────────────────────────────

class TestRecentApplicationsWithData:
    def test_returns_application_with_job_details(self, client: TestClient, db: Session) -> None:
        job = _make_job(db, title="Python Developer", company="Test Corp")
        _make_application(db, job, status="APPLIED")
        db.commit()

        data = client.get("/api/dashboard/recent-applications").json()
        assert data["total"] == 1
        item = data["applications"][0]
        assert item["job_title"] == "Python Developer"
        assert item["company"] == "Test Corp"
        assert item["status"] == "APPLIED"

    def test_limit_parameter_respected(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        for _ in range(5):
            _make_application(db, job, status="SKIPPED")
        db.commit()

        data = client.get("/api/dashboard/recent-applications?limit=3").json()
        assert len(data["applications"]) == 3

    def test_limit_capped_at_50(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        for _ in range(60):
            _make_application(db, job, status="SKIPPED")
        db.commit()

        data = client.get("/api/dashboard/recent-applications?limit=100").json()
        assert len(data["applications"]) <= 50

    def test_required_fields_present(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        _make_application(db, job, status="NEEDS_ATTENTION")
        db.commit()

        data = client.get("/api/dashboard/recent-applications").json()
        item = data["applications"][0]
        # All required fields must be present
        for field in ("application_id", "job_id", "job_title", "company", "status",
                      "application_method", "applied_at", "skip_reason",
                      "needs_attention", "is_dry_run", "created_at"):
            assert field in item, f"Missing field: {field}"

    def test_needs_attention_flag(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        _make_application(db, job, status="NEEDS_ATTENTION")
        db.commit()

        data = client.get("/api/dashboard/recent-applications").json()
        assert data["applications"][0]["needs_attention"] is True


# ── Security: no secrets in responses ────────────────────────────────────────

class TestDashboardNoSecretsExposed:
    FORBIDDEN_KEYS = {
        "api_key", "gemini_api_key", "password", "secret", "token",
        "cookie", "session", "credential", "auth", "database_url",
        "resume_hash",
    }

    def _check_no_secrets(self, data: object) -> None:
        """Recursively verify no forbidden keys appear in the response."""
        if isinstance(data, dict):
            for key in data:
                assert key.lower() not in self.FORBIDDEN_KEYS, (
                    f"Forbidden key '{key}' found in dashboard response"
                )
                self._check_no_secrets(data[key])
        elif isinstance(data, list):
            for item in data:
                self._check_no_secrets(item)

    def test_summary_contains_no_secrets(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/summary").json()
        self._check_no_secrets(data)

    def test_recent_applications_contains_no_secrets(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        _make_application(db, job, status="APPLIED")
        db.commit()

        data = client.get("/api/dashboard/recent-applications").json()
        self._check_no_secrets(data)

    def test_summary_profile_has_no_resume_hash(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/summary").json()
        profile = data["profile"]
        assert "resume_hash" not in profile

    def test_confirmation_evidence_not_in_recent_apps(self, client: TestClient, db: Session) -> None:
        """confirmation_evidence is internal — must not appear in recent-applications."""
        job = _make_job(db)
        app = _make_application(db, job, status="APPLIED")
        app.confirmation_evidence = "Applied (internal evidence)"
        db.commit()

        data = client.get("/api/dashboard/recent-applications").json()
        item = data["applications"][0]
        assert "confirmation_evidence" not in item


# ── Read-only: no mutations ───────────────────────────────────────────────────

class TestDashboardReadOnly:
    def test_summary_is_get_only(self, client: TestClient) -> None:
        """Dashboard summary must not accept POST/PUT/DELETE."""
        assert client.post("/api/dashboard/summary").status_code == 405
        assert client.put("/api/dashboard/summary").status_code == 405
        assert client.delete("/api/dashboard/summary").status_code == 405

    def test_recent_applications_is_get_only(self, client: TestClient) -> None:
        assert client.post("/api/dashboard/recent-applications").status_code == 405
        assert client.put("/api/dashboard/recent-applications").status_code == 405

    def test_needs_attention_is_get_only(self, client: TestClient) -> None:
        """Needs-attention endpoint must not accept POST/PUT/DELETE."""
        assert client.post("/api/dashboard/needs-attention").status_code == 405
        assert client.put("/api/dashboard/needs-attention").status_code == 405
        assert client.delete("/api/dashboard/needs-attention").status_code == 405


# ── Needs Attention endpoint (Checkpoint E2) ───────────────────────────────────

class TestNeedsAttentionEmpty:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/dashboard/needs-attention")
        assert response.status_code == 200

    def test_empty_list_when_no_applications(self, client: TestClient) -> None:
        data = client.get("/api/dashboard/needs-attention").json()
        assert data["applications"] == []
        assert data["total"] == 0


class TestNeedsAttentionWithData:
    def test_returns_needs_attention_applications(self, client: TestClient, db: Session) -> None:
        job = _make_job(db, title="Python Developer", company="Test Corp")
        _make_application(db, job, status="NEEDS_ATTENTION")
        db.commit()

        data = client.get("/api/dashboard/needs-attention").json()
        assert data["total"] == 1
        item = data["applications"][0]
        assert item["job_title"] == "Python Developer"
        assert item["company"] == "Test Corp"
        assert item["status"] == "NEEDS_ATTENTION"
        assert item["needs_attention"] is True

    def test_filters_by_needs_attention_flag(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        _make_application(db, job, status="APPLIED", needs_attention=False)
        _make_application(db, job, status="SKIPPED", needs_attention=True)
        db.commit()

        data = client.get("/api/dashboard/needs-attention").json()
        assert data["total"] == 1
        assert data["applications"][0]["status"] == "SKIPPED"

    def test_limit_parameter_respected(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        for _ in range(5):
            _make_application(db, job, status="NEEDS_ATTENTION")
        db.commit()

        data = client.get("/api/dashboard/needs-attention?limit=3").json()
        assert len(data["applications"]) == 3

    def test_limit_capped_at_50(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        for _ in range(60):
            _make_application(db, job, status="NEEDS_ATTENTION")
        db.commit()

        data = client.get("/api/dashboard/needs-attention?limit=100").json()
        assert len(data["applications"]) <= 50

    def test_required_fields_present(self, client: TestClient, db: Session) -> None:
        job = _make_job(db)
        app = _make_application(db, job, status="NEEDS_ATTENTION")
        app.skip_reason = "Test reason"
        db.commit()

        data = client.get("/api/dashboard/needs-attention").json()
        item = data["applications"][0]
        for field in ("application_id", "job_id", "job_title", "company", "status",
                      "skip_reason", "failure_reason", "needs_attention", "created_at"):
            assert field in item, f"Missing field: {field}"

    def test_no_secrets_exposed(self, client: TestClient, db: Session) -> None:
        """Verify needs-attention endpoint does not expose secrets."""
        job = _make_job(db)
        _make_application(db, job, status="NEEDS_ATTENTION")
        db.commit()

        data = client.get("/api/dashboard/needs-attention").json()
        FORBIDDEN_KEYS = {
            "api_key", "gemini_api_key", "password", "secret", "token",
            "cookie", "session", "credential", "auth", "database_url",
            "resume_hash", "confirmation_evidence", "external_url",
        }

        def check_no_secrets(obj: object) -> None:
            if isinstance(obj, dict):
                for key in obj:
                    assert key.lower() not in FORBIDDEN_KEYS, f"Forbidden key '{key}' found"
                    check_no_secrets(obj[key])
            elif isinstance(obj, list):
                for item in obj:
                    check_no_secrets(item)

        check_no_secrets(data)
