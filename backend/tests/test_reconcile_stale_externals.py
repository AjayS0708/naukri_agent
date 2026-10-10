"""
Checkpoint E5-R5.3 — Signature-scoped reconciliation of false external classifications.

Verifies that reconcile_stale_externals:
1. Reclassifies only EXTERNAL_APPLICATION rows with the exact page-chrome URL to SKIPPED
2. Records the audit reason
3. Leaves different external URLs unchanged
4. Leaves NEEDS_ATTENTION, APPLIED, SUBMITTED (SUBMITTED_UNCONFIRMED persistence),
   FAILED, and existing SKIPPED rows unchanged
5. Is idempotent (second call is a no-op)
6. Exposes the operation via POST /api/applications/reconcile-stale-externals
   with accurate count, application IDs, job IDs, and signature reporting
7. Performs no unrelated status changes

All tests run against the isolated disposable test database provided by
conftest.py; none of them touch the real local database.
"""
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.job import Job
from backend.schemas.application import ApplicationStatus, ApplicationMethod
from backend.services.applications.service import (
    ApplicationService,
    STALE_EXTERNAL_PAGE_CHROME_URL,
    STALE_EXTERNAL_RECONCILE_SKIP_REASON,
)

OTHER_EXTERNAL_URL = "https://example.com/careers/apply/12345"


def _create_job(db: Session, external_job_id: str) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=external_job_id,
        url=f"https://www.naukri.com/job-listings-{external_job_id}",
        title="Python Developer",
        company="Acme Corp",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _create_application(
    db: Session,
    job: Job,
    status: str,
    external_url: str | None = None,
    needs_attention: bool = False,
    application_method: str | None = None,
    applied_at: datetime | None = None,
    skip_reason: str | None = None,
) -> Application:
    application = Application(
        job_id=job.id,
        status=status,
        external_url=external_url,
        needs_attention=needs_attention,
        application_method=application_method,
        applied_at=applied_at,
        skip_reason=skip_reason,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def _reload(db: Session, application_id: int) -> Application:
    db.expire_all()
    return db.get(Application, application_id)


class TestServiceReconciliation:
    def test_exact_signature_rows_become_skipped(self, db: Session) -> None:
        """Only EXTERNAL_APPLICATION rows with the exact signature URL become SKIPPED."""
        job = _create_job(db, "job-1")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
            needs_attention=True,
            application_method=ApplicationMethod.EXTERNAL.value,
        )

        service = ApplicationService(db)
        result = service.reconcile_stale_externals()

        assert result["affected_count"] == 1
        assert result["application_ids"] == [app.id]
        assert result["job_ids"] == [job.id]
        assert result["signature"] == STALE_EXTERNAL_PAGE_CHROME_URL

        reloaded = _reload(db, app.id)
        assert reloaded.status == ApplicationStatus.SKIPPED.value
        assert reloaded.needs_attention is False
        # History preserved: record not deleted, method and URL kept for audit.
        assert reloaded.external_url == STALE_EXTERNAL_PAGE_CHROME_URL
        assert reloaded.application_method == ApplicationMethod.EXTERNAL.value

    def test_audit_reason_recorded(self, db: Session) -> None:
        """The reconciliation records an explicit audit reason referencing the page-chrome URL."""
        job = _create_job(db, "job-1")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
        )

        ApplicationService(db).reconcile_stale_externals()

        reloaded = _reload(db, app.id)
        assert reloaded.skip_reason == STALE_EXTERNAL_RECONCILE_SKIP_REASON
        assert STALE_EXTERNAL_PAGE_CHROME_URL in reloaded.skip_reason
        assert "page-chrome" in reloaded.skip_reason

    def test_different_external_url_unchanged(self, db: Session) -> None:
        """EXTERNAL_APPLICATION rows with any other URL remain untouched."""
        job = _create_job(db, "job-1")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=OTHER_EXTERNAL_URL,
            needs_attention=True,
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["affected_count"] == 0
        assert result["application_ids"] == []
        reloaded = _reload(db, app.id)
        assert reloaded.status == ApplicationStatus.EXTERNAL_APPLICATION.value
        assert reloaded.external_url == OTHER_EXTERNAL_URL
        assert reloaded.needs_attention is True

    def test_protected_statuses_unchanged(self, db: Session) -> None:
        """NEEDS_ATTENTION, APPLIED, SUBMITTED (SUBMITTED_UNCONFIRMED persistence),
        FAILED, and already-SKIPPED rows remain unchanged even when carrying the
        signature URL."""
        cases = [
            ("needs-attention", ApplicationStatus.NEEDS_ATTENTION.value, True),
            ("applied", ApplicationStatus.APPLIED.value, False),
            ("submitted-unconfirmed", ApplicationStatus.SUBMITTED.value, False),
            ("failed", "FAILED", False),
            ("already-skipped", ApplicationStatus.SKIPPED.value, False),
        ]
        apps = []
        for external_job_id, status, needs_attention in cases:
            job = _create_job(db, external_job_id)
            apps.append(
                (
                    _create_application(
                        db,
                        job,
                        status,
                        external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
                        needs_attention=needs_attention,
                        applied_at=(
                            datetime.now(UTC)
                            if status == ApplicationStatus.SUBMITTED.value
                            else None
                        ),
                        skip_reason=(
                            "previous skip"
                            if status == ApplicationStatus.SKIPPED.value
                            else None
                        ),
                    ),
                    status,
                    needs_attention,
                )
            )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["affected_count"] == 0
        assert result["application_ids"] == []
        for app, status, needs_attention in apps:
            reloaded = _reload(db, app.id)
            assert reloaded.status == status
            assert reloaded.needs_attention == needs_attention
            if status == ApplicationStatus.SKIPPED.value:
                assert reloaded.skip_reason == "previous skip"
            else:
                assert reloaded.skip_reason != STALE_EXTERNAL_RECONCILE_SKIP_REASON

    def test_second_call_is_noop(self, db: Session) -> None:
        """A second reconciliation call reclassifies nothing."""
        job = _create_job(db, "job-1")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
        )
        service = ApplicationService(db)

        first = service.reconcile_stale_externals()
        second = service.reconcile_stale_externals()

        assert first["affected_count"] == 1
        assert second["affected_count"] == 0
        assert second["application_ids"] == []
        assert second["job_ids"] == []
        assert second["signature"] == STALE_EXTERNAL_PAGE_CHROME_URL
        assert _reload(db, app.id).status == ApplicationStatus.SKIPPED.value


class TestReconcileEndpoint:
    def test_endpoint_reports_affected_rows_accurately(self, db: Session, client: TestClient) -> None:
        """POST /api/applications/reconcile-stale-externals reports count, IDs, job IDs, and signature."""
        job_a = _create_job(db, "job-a")
        job_b = _create_job(db, "job-b")
        app_a = _create_application(
            db,
            job_a,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
        )
        app_b = _create_application(
            db,
            job_b,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
        )

        response = client.post("/api/applications/reconcile-stale-externals")

        assert response.status_code == 200
        payload = response.json()
        assert payload["affected_count"] == 2
        assert sorted(payload["application_ids"]) == sorted([app_a.id, app_b.id])
        assert sorted(payload["job_ids"]) == sorted([job_a.id, job_b.id])
        assert payload["signature"] == STALE_EXTERNAL_PAGE_CHROME_URL

        assert _reload(db, app_a.id).status == ApplicationStatus.SKIPPED.value
        assert _reload(db, app_b.id).status == ApplicationStatus.SKIPPED.value

    def test_endpoint_performs_no_unrelated_status_changes(self, db: Session, client: TestClient) -> None:
        """The endpoint changes only the exact-signature EXTERNAL_APPLICATION rows."""
        matching_job = _create_job(db, "matching")
        other_url_job = _create_job(db, "other-url")
        needs_job = _create_job(db, "needs-attention")
        applied_job = _create_job(db, "applied")
        submitted_job = _create_job(db, "submitted")
        failed_job = _create_job(db, "failed")
        skipped_job = _create_job(db, "skipped")

        matching = _create_application(
            db,
            matching_job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
        )
        other_url = _create_application(
            db,
            other_url_job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=OTHER_EXTERNAL_URL,
            needs_attention=True,
        )
        needs_attention = _create_application(
            db,
            needs_job,
            ApplicationStatus.NEEDS_ATTENTION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
            needs_attention=True,
        )
        applied = _create_application(
            db,
            applied_job,
            ApplicationStatus.APPLIED.value,
            applied_at=datetime.now(UTC),
        )
        submitted_unconfirmed = _create_application(
            db,
            submitted_job,
            ApplicationStatus.SUBMITTED.value,
            applied_at=datetime.now(UTC),
        )
        failed = _create_application(db, failed_job, "FAILED")
        skipped = _create_application(
            db,
            skipped_job,
            ApplicationStatus.SKIPPED.value,
            skip_reason="previous skip",
        )

        response = client.post("/api/applications/reconcile-stale-externals")

        assert response.status_code == 200
        assert response.json()["affected_count"] == 1
        assert response.json()["application_ids"] == [matching.id]
        assert response.json()["job_ids"] == [matching_job.id]

        assert _reload(db, matching.id).status == ApplicationStatus.SKIPPED.value
        assert _reload(db, other_url.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value
        assert _reload(db, other_url.id).needs_attention is True
        assert _reload(db, needs_attention.id).status == ApplicationStatus.NEEDS_ATTENTION.value
        assert _reload(db, applied.id).status == ApplicationStatus.APPLIED.value
        assert _reload(db, submitted_unconfirmed.id).status == ApplicationStatus.SUBMITTED.value
        assert _reload(db, failed.id).status == "FAILED"
        assert _reload(db, skipped.id).status == ApplicationStatus.SKIPPED.value
        assert _reload(db, skipped.id).skip_reason == "previous skip"
