"""
Checkpoint E5-R5.3 / E5-R6 — Reconciliation of false external classifications.

Verifies that reconcile_stale_externals:
1. Rule 1 (E5-R5.3): reclassifies only EXTERNAL_APPLICATION rows with the
   exact page-chrome URL to SKIPPED with its audit reason
2. Rule 2 (E5-R6): reclassifies EXTERNAL_APPLICATION rows whose external_url
   matches the linked job's own canonical Naukri URL after safe
   normalization, with the recovered_pre_r5_4_native_url_misclassification
   audit reason
3. Leaves genuine external redirects, ambiguous URLs, and protected states
   unchanged
4. Leaves NEEDS_ATTENTION, APPLIED, SUBMITTED (SUBMITTED_UNCONFIRMED
   persistence), FAILED, and existing SKIPPED rows unchanged
5. Is idempotent (second call is a no-op for both rules)
6. Exposes the operation via POST /api/applications/reconcile-stale-externals
   with accurate per-rule counts, application IDs, job IDs, and signature
   reporting
7. Performs no unrelated status changes
8. Never reconciles protected job IDs 87 and 120

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
    PRE_R5_4_NATIVE_URL_RECOVERY_TOKEN,
    PRE_R5_4_NATIVE_URL_RECOVERY_SKIP_REASON,
    normalize_naukri_url_for_comparison,
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


class TestNativeUrlRecovery:
    """E5-R6: recovery of pre-R5.4 native-URL misclassifications (rule 2)."""

    def test_job_url_match_recovers_to_skipped(self, db: Session) -> None:
        """EXTERNAL_APPLICATION row whose external_url equals the job's own
        Naukri job-listing URL is recovered to SKIPPED with the audit token."""
        job = _create_job(db, "job-54")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job.url,
            needs_attention=True,
            application_method=ApplicationMethod.EXTERNAL.value,
            skip_reason="external - needs review",
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["affected_count"] == 0
        assert result["recovered_count"] == 1
        assert result["recovered_application_ids"] == [app.id]
        assert result["recovered_job_ids"] == [job.id]

        reloaded = _reload(db, app.id)
        assert reloaded.status == ApplicationStatus.SKIPPED.value
        assert reloaded.needs_attention is False
        assert PRE_R5_4_NATIVE_URL_RECOVERY_TOKEN in reloaded.skip_reason
        # History preserved for audit.
        assert reloaded.external_url == job.url
        assert reloaded.application_method == ApplicationMethod.EXTERNAL.value

    def test_safe_url_equivalent_forms_recover(self, db: Session) -> None:
        """http scheme, trailing slash, and fragment are equivalent forms."""
        job = _create_job(db, "job-eq")
        equivalent = f"http://www.naukri.com/job-listings-{job.external_job_id}/#top"
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=equivalent,
            needs_attention=True,
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 1
        assert result["recovered_application_ids"] == [app.id]
        assert _reload(db, app.id).status == ApplicationStatus.SKIPPED.value

    def test_genuine_external_redirect_unchanged(self, db: Session) -> None:
        """A genuine external destination (different host) is never recovered."""
        job = _create_job(db, "job-2")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url="https://www.facebook.com/Naukri",
            needs_attention=True,
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 0
        assert result["recovered_application_ids"] == []
        assert app.id in result["remaining_external_ids"]
        reloaded = _reload(db, app.id)
        assert reloaded.status == ApplicationStatus.EXTERNAL_APPLICATION.value
        assert reloaded.needs_attention is True

    def test_url_pointing_to_other_naukri_job_unchanged(self, db: Session) -> None:
        """A Naukri URL that does not belong to the linked job is ambiguous."""
        job = _create_job(db, "job-a")
        other_job = _create_job(db, "job-b")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=other_job.url,
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 0
        assert app.id in result["remaining_external_ids"]
        assert _reload(db, app.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value

    def test_non_job_listing_naukri_path_unchanged(self, db: Session) -> None:
        """A non-job-listing Naukri URL equal to job.url is left unchanged."""
        job = _create_job(db, "job-path")
        job.url = "https://www.naukri.com/"
        db.commit()
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url="https://www.naukri.com/",
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 0
        assert app.id in result["remaining_external_ids"]
        assert _reload(db, app.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value

    def test_submission_evidence_blocks_recovery(self, db: Session) -> None:
        """Rows carrying confirmation evidence or applied_at are never recovered."""
        job_evidence = _create_job(db, "job-evidence")
        job_applied = _create_job(db, "job-applied-at")
        app_evidence = _create_application(
            db,
            job_evidence,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job_evidence.url,
        )
        app_evidence.confirmation_evidence = "confirmation text"
        db.commit()
        app_applied = _create_application(
            db,
            job_applied,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job_applied.url,
            applied_at=datetime.now(UTC),
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 0
        assert app_evidence.id in result["remaining_external_ids"]
        assert app_applied.id in result["remaining_external_ids"]
        assert _reload(db, app_evidence.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value
        assert _reload(db, app_applied.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value

    def test_protected_job_ids_never_reconciled(self, db: Session) -> None:
        """Jobs 87 and 120 are never reconciled even with a matching URL."""
        job_87 = Job(
            id=87,
            platform="naukri",
            external_job_id="job-87",
            url="https://www.naukri.com/job-listings-job-87",
            title="Python Developer",
            company="Acme Corp",
        )
        db.add(job_87)
        db.commit()
        app = _create_application(
            db,
            job_87,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job_87.url,
        )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 0
        assert app.id in result["remaining_external_ids"]
        assert _reload(db, app.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value

    def test_protected_statuses_with_job_url_unchanged(self, db: Session) -> None:
        """APPLIED/SUBMITTED/NEEDS_ATTENTION/FAILED/SKIPPED rows are untouched
        even when their external_url equals the job's own URL."""
        cases = [
            ("applied", ApplicationStatus.APPLIED.value, False),
            ("submitted", ApplicationStatus.SUBMITTED.value, False),
            ("needs-attention", ApplicationStatus.NEEDS_ATTENTION.value, True),
            ("failed", "FAILED", False),
            ("skipped", ApplicationStatus.SKIPPED.value, False),
        ]
        apps = []
        for external_job_id, status, needs_attention in cases:
            job = _create_job(db, external_job_id)
            apps.append(
                _create_application(
                    db,
                    job,
                    status,
                    external_url=job.url,
                    needs_attention=needs_attention,
                    skip_reason="previous skip" if status == ApplicationStatus.SKIPPED.value else None,
                )
            )

        result = ApplicationService(db).reconcile_stale_externals()

        assert result["recovered_count"] == 0
        assert result["affected_count"] == 0
        for app, (external_job_id, status, needs_attention) in zip(apps, cases):
            reloaded = _reload(db, app.id)
            assert reloaded.status == status
            assert reloaded.needs_attention == needs_attention

    def test_second_call_is_noop_for_rule_2(self, db: Session) -> None:
        """Rule 2 is idempotent: the second call recovers nothing."""
        job = _create_job(db, "job-idem")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job.url,
        )
        service = ApplicationService(db)

        first = service.reconcile_stale_externals()
        second = service.reconcile_stale_externals()

        assert first["recovered_count"] == 1
        assert second["recovered_count"] == 0
        assert second["recovered_application_ids"] == []
        assert _reload(db, app.id).status == ApplicationStatus.SKIPPED.value

    def test_audit_reason_is_distinct_from_rule_1(self, db: Session) -> None:
        """Rule 2 records its own explicit audit reason."""
        job = _create_job(db, "job-audit")
        app = _create_application(
            db,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job.url,
        )

        ApplicationService(db).reconcile_stale_externals()

        reloaded = _reload(db, app.id)
        assert reloaded.skip_reason == PRE_R5_4_NATIVE_URL_RECOVERY_SKIP_REASON
        assert reloaded.skip_reason != STALE_EXTERNAL_RECONCILE_SKIP_REASON
        assert "misclassification" in reloaded.skip_reason


class TestUrlNormalization:
    def test_equivalent_forms_normalize_equal(self) -> None:
        base = "https://www.naukri.com/job-listings-abc-123"
        assert normalize_naukri_url_for_comparison(base) == normalize_naukri_url_for_comparison(
            "http://www.naukri.com/job-listings-abc-123/"
        )
        assert normalize_naukri_url_for_comparison(base + "#frag") == normalize_naukri_url_for_comparison(base)
        assert normalize_naukri_url_for_comparison("  " + base + "  ") == normalize_naukri_url_for_comparison(base)

    def test_different_urls_stay_different(self) -> None:
        a = normalize_naukri_url_for_comparison("https://www.naukri.com/job-listings-abc")
        b = normalize_naukri_url_for_comparison("https://www.naukri.com/job-listings-def")
        assert a != b
        external = normalize_naukri_url_for_comparison("https://example.com/job-listings-abc")
        assert external != a

    def test_missing_or_unparseable_returns_none(self) -> None:
        assert normalize_naukri_url_for_comparison(None) is None
        assert normalize_naukri_url_for_comparison("") is None
        assert normalize_naukri_url_for_comparison("   ") is None
        assert normalize_naukri_url_for_comparison("not a url") is None


class TestEndpointRule2Reporting:
    def test_endpoint_reports_both_rules_and_remaining(self, db: Session, client: TestClient) -> None:
        """Endpoint returns per-rule counts, IDs, and remaining external IDs."""
        sig_job = _create_job(db, "sig-job")
        native_job = _create_job(db, "native-job")
        genuine_job = _create_job(db, "genuine-job")
        sig_app = _create_application(
            db,
            sig_job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=STALE_EXTERNAL_PAGE_CHROME_URL,
        )
        native_app = _create_application(
            db,
            native_job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=native_job.url,
            needs_attention=True,
        )
        genuine_app = _create_application(
            db,
            genuine_job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url="https://www.facebook.com/Naukri",
        )

        response = client.post("/api/applications/reconcile-stale-externals")

        assert response.status_code == 200
        payload = response.json()
        assert payload["affected_count"] == 1
        assert payload["application_ids"] == [sig_app.id]
        assert payload["recovered_count"] == 1
        assert payload["recovered_application_ids"] == [native_app.id]
        assert payload["recovered_job_ids"] == [native_job.id]
        assert payload["remaining_external_ids"] == [genuine_app.id]

        assert _reload(db, sig_app.id).status == ApplicationStatus.SKIPPED.value
        assert _reload(db, native_app.id).status == ApplicationStatus.SKIPPED.value
        assert _reload(db, genuine_app.id).status == ApplicationStatus.EXTERNAL_APPLICATION.value
