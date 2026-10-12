"""E5-R16: Stop wiring, record integrity and read-only history reconciliation.

Covers (no live browser, no Apply click, no external navigation):
1. the cycle wires a cancellation checkpoint into discovery, so Stop reaches
   the phase that previously ignored it;
2. LOGIN_REQUIRED is a legitimate terminal run status and the login probe runs
   before any application is attempted;
3. application records are idempotent (one open attempt per job) and an
   interrupted attempt is never reported as APPLIED;
4. read-only Naukri history reconciliation is idempotent, additive-only, and
   never writes to protected job IDs 81, 87, 114, 120;
5. POST /api/applications/reconcile-history refuses while a cycle is active
   and reports LOGIN_REQUIRED without reading anything when logged out.
"""
import inspect
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.models.application import Application
from backend.models.job import Job
from backend.schemas.application import (
    ApplicationCreate,
    ApplicationMethod,
    ApplicationStatus,
)
from backend.services.applications.service import (
    ApplicationService,
    PROTECTED_HISTORY_JOB_IDS,
    normalize_naukri_url_for_comparison,
)


def _make_job(db, external_job_id: str, *, job_id: int | None = None, title="Python Developer", company="Acme Corp") -> Job:
    job = Job(
        id=job_id,
        platform="naukri",
        external_job_id=external_job_id,
        url=f"https://www.naukri.com/job-listings-{external_job_id}",
        title=title,
        company=company,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _rows(db, job_id: int) -> list[Application]:
    return list(
        db.execute(select(Application).where(Application.job_id == job_id))
        .scalars()
        .all()
    )


# ── 1. Stop reaches discovery ───────────────────────────────────────────


def test_cycle_wires_cancellation_check_into_discovery() -> None:
    import inspect as _inspect

    from backend.services.autonomous_cycle import service as cycle_module
    from backend.services.discovery.service import DiscoveryService

    source = _inspect.getsource(cycle_module)
    assert "cancel_check=self._cancellation_requested" in source
    assert "cancel_check" in _inspect.signature(DiscoveryService.__init__).parameters


def test_discovery_stop_check_is_consulted_at_every_phase() -> None:
    from backend.services.discovery import service as discovery_module

    source = inspect.getsource(discovery_module)
    # The shared helper (not the raw flag) is what the loop checks, so an
    # externally supplied cancel_check from the cycle is honoured. The only
    # remaining raw-flag check is the one inside the helper itself.
    assert source.count("if self._should_stop():") >= 5
    assert source.count("if self._stop_requested:") == 1


def test_cycle_login_probe_runs_before_applications() -> None:
    from backend.services.autonomous_cycle import service as cycle_module

    source = inspect.getsource(cycle_module)
    probe_at = source.index("await self._probe_login_state()")
    applications_at = source.index("await self._run_applications(")
    assert probe_at < applications_at


# ── 2. LOGIN_REQUIRED is a real terminal status ─────────────────────────


def test_coordinator_stores_login_required_terminal_status(db) -> None:
    from backend.services.autonomous_cycle.coordinator import CycleCoordinator

    coordinator = CycleCoordinator()
    ok, token, _ = coordinator.try_acquire(db=db)
    assert ok

    payload = coordinator.complete(
        token,
        {"status": "LOGIN_REQUIRED", "run_id": None, "stats": {}, "error": None},
        db=db,
    )

    assert payload["status"] == "LOGIN_REQUIRED"
    assert coordinator.snapshot(db=db)["active_state"] == "IDLE"
    assert coordinator.snapshot(db=db)["last_run"]["status"] == "LOGIN_REQUIRED"


def test_coordinator_never_stores_unknown_terminal_status(db) -> None:
    from backend.services.autonomous_cycle.coordinator import CycleCoordinator

    coordinator = CycleCoordinator()
    ok, token, _ = coordinator.try_acquire(db=db)
    assert ok

    payload = coordinator.complete(token, {"status": "WEIRD"}, db=db)
    assert payload["status"] == "FAILED"


def test_cycle_source_probes_login_state_and_stops_on_logout() -> None:
    from backend.services.autonomous_cycle import service as cycle_module

    source = inspect.getsource(cycle_module)
    assert "Naukri session is not authenticated" in source
    assert '"LOGIN_REQUIRED"' in source


# ── 3. Record integrity ─────────────────────────────────────────────────


def test_create_application_reuses_open_attempt(db) -> None:
    job = _make_job(db, "r16-idem")
    service = ApplicationService(db)

    first = service.create_application(
        ApplicationCreate(
            job_id=job.id,
            status=ApplicationStatus.APPLICATION_STARTED,
            application_method=ApplicationMethod.NAUKRI_NATIVE,
        )
    )
    second = service.create_application(
        ApplicationCreate(
            job_id=job.id,
            status=ApplicationStatus.APPLICATION_STARTED,
            application_method=ApplicationMethod.NAUKRI_NATIVE,
        )
    )

    assert first.id == second.id
    assert len(_rows(db, job.id)) == 1


def test_resolve_open_attempt_creates_no_record_when_none_open(db) -> None:
    job = _make_job(db, "r16-noopen")
    service = ApplicationService(db)

    assert service.resolve_open_attempt(job, "Authentication required") is None
    assert _rows(db, job.id) == []


def test_resolve_open_attempt_closes_existing_attempt_only(db) -> None:
    job = _make_job(db, "r16-open")
    service = ApplicationService(db)
    service.create_application(
        ApplicationCreate(
            job_id=job.id,
            status=ApplicationStatus.APPLICATION_STARTED,
            application_method=ApplicationMethod.NAUKRI_NATIVE,
        )
    )

    resolved = service.resolve_open_attempt(job, "Authentication required")

    assert resolved is not None
    assert resolved.status == ApplicationStatus.NEEDS_ATTENTION.value
    assert len(_rows(db, job.id)) == 1


def test_reconcile_interrupted_attempts_is_never_applied_and_idempotent(db) -> None:
    job = _make_job(db, "r16-interrupted")
    applied_job = _make_job(db, "r16-applied")
    service = ApplicationService(db)

    open_row = Application(
        job_id=job.id, status=ApplicationStatus.APPLICATION_STARTED.value
    )
    applied_row = Application(
        job_id=applied_job.id,
        status=ApplicationStatus.APPLIED.value,
        applied_at=datetime(2026, 1, 1, tzinfo=UTC),
        confirmation_evidence="naukri_form_submitted",
    )
    db.add_all([open_row, applied_row])
    db.commit()

    first = service.reconcile_interrupted_attempts()
    second = service.reconcile_interrupted_attempts()

    assert first["reconciled_count"] == 1
    assert first["job_ids"] == [job.id]
    assert second["reconciled_count"] == 0

    rows = _rows(db, job.id)
    assert len(rows) == 1
    assert rows[0].status == ApplicationStatus.NEEDS_ATTENTION.value
    assert rows[0].applied_at is None
    assert "Interrupted before submission confirmation" in (rows[0].failure_reason or "")

    untouched = _rows(db, applied_job.id)
    assert len(untouched) == 1
    assert untouched[0].status == ApplicationStatus.APPLIED.value
    assert untouched[0].confirmation_evidence == "naukri_form_submitted"


# ── 4. Read-only Naukri history reconciliation ──────────────────────────


def test_history_protected_ids_cover_required_jobs() -> None:
    assert PROTECTED_HISTORY_JOB_IDS == {81, 87, 114, 120}


def test_reconcile_from_history_is_idempotent_and_protected(db) -> None:
    new_job = _make_job(db, "r16-new")
    confirmed_job = _make_job(db, "r16-confirmed")
    extra_job = _make_job(db, "r16-extra")
    protected_job = _make_job(db, "r16-protected", job_id=114)
    service = ApplicationService(db)

    confirmed_row = Application(
        job_id=confirmed_job.id,
        status=ApplicationStatus.APPLIED.value,
        applied_at=datetime(2026, 2, 2, tzinfo=UTC),
        confirmation_evidence="naukri_form_submitted",
    )
    extra_row = Application(
        job_id=extra_job.id,
        status=ApplicationStatus.APPLIED.value,
        applied_at=datetime(2026, 3, 3, tzinfo=UTC),
        confirmation_evidence="naukri_form_submitted",
    )
    db.add_all([confirmed_row, extra_row])
    db.commit()

    history = [
        {"url": new_job.url, "title": new_job.title, "company": new_job.company},
        {"url": confirmed_job.url, "title": confirmed_job.title, "company": confirmed_job.company},
        {"url": protected_job.url, "title": protected_job.title, "company": protected_job.company},
        {"url": "https://www.naukri.com/job-listings-never-seen", "title": "Unknown", "company": "Nowhere"},
    ]

    first = service.reconcile_from_history(history)
    second = service.reconcile_from_history(history)

    assert first["reconciled_count"] == 1
    assert first["reconciled_job_ids"] == [new_job.id]
    assert confirmed_job.id in first["confirmed_local_job_ids"]
    assert first["protected_job_ids"] == [114]
    assert first["unmatched"] == ["https://www.naukri.com/job-listings-never-seen"]
    assert extra_job.id in first["local_applied_without_history_evidence"]

    # Second run: nothing new, nothing duplicated.
    assert second["reconciled_count"] == 0
    assert second["reconciled_job_ids"] == []
    assert confirmed_job.id in second["confirmed_local_job_ids"]

    new_rows = _rows(db, new_job.id)
    assert len(new_rows) == 1
    assert new_rows[0].status == ApplicationStatus.APPLIED.value
    assert new_rows[0].reconciled_from_history is True
    assert (new_rows[0].confirmation_evidence or "").startswith(
        "reconciled_from_naukri_history:"
    )

    # Protected job must stay untouched: no row written for it.
    assert _rows(db, protected_job.id) == []

    # Existing applied rows are only reported, never modified.
    confirmed_rows = _rows(db, confirmed_job.id)
    assert len(confirmed_rows) == 1
    assert confirmed_rows[0].id == confirmed_row.id
    assert confirmed_rows[0].confirmation_evidence == "naukri_form_submitted"
    assert confirmed_rows[0].reconciled_from_history is False
    assert len(_rows(db, extra_job.id)) == 1


def test_reconcile_from_history_matches_by_normalized_url_and_title(db) -> None:
    job = _make_job(db, "r16-normalized")
    service = ApplicationService(db)

    http_equivalent = job.url.replace("https://", "http://") + "/"
    assert (
        normalize_naukri_url_for_comparison(http_equivalent)
        == normalize_naukri_url_for_comparison(job.url)
    )

    result = service.reconcile_from_history(
        [{"url": http_equivalent, "title": job.title, "company": job.company}]
    )

    assert result["reconciled_job_ids"] == [job.id]
    assert len(_rows(db, job.id)) == 1


def test_reconcile_from_history_never_fabricates_applied_without_evidence(db) -> None:
    job = _make_job(db, "r16-empty")
    service = ApplicationService(db)

    result = service.reconcile_from_history([])

    assert result["reconciled_count"] == 0
    assert _rows(db, job.id) == []


# ── 5. Reconciliation endpoint guards ───────────────────────────────────


def test_reconcile_history_route_reports_login_required(client: TestClient, db) -> None:
    with patch(
        "backend.services.naukri.adapter.NaukriAdapter.start_session",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "backend.services.naukri.adapter.NaukriAdapter.stop_session",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.naukri.adapter.NaukriAdapter.check_session_authenticated",
        new_callable=AsyncMock,
        return_value={"authenticated": False, "evidence": "logged_out_control:Login"},
    ), patch(
        "backend.services.naukri.adapter.NaukriAdapter.fetch_application_history",
        new_callable=AsyncMock,
    ) as fetch_history:

        response = client.post("/api/applications/reconcile-history")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "LOGIN_REQUIRED"
    assert body["history_entries"] == 0
    assert body["reconciled_count"] == 0
    fetch_history.assert_not_awaited()
    assert db.execute(select(Application)).scalars().all() == []


def test_reconcile_history_route_refuses_while_cycle_running(client: TestClient) -> None:
    with patch(
        "backend.services.autonomous_cycle.coordinator.coordinator.snapshot",
        return_value={"active_state": "RUNNING", "active_run": {}, "last_run": None},
    ):
        response = client.post("/api/applications/reconcile-history")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AUTONOMOUS_CYCLE_RUNNING"


def test_reconcile_from_history_matches_by_external_job_id(db) -> None:
    """History cards carry Naukri's numeric job id; that is the precise key."""
    job = _make_job(db, "r16-idmatch")
    service = ApplicationService(db)

    result = service.reconcile_from_history(
        [
            {
                "external_job_id": job.external_job_id,
                "title": "Immediate openings For Python Developer",
                "company": "Acme Corp Pvt Ltd",
                "url": None,
            }
        ]
    )

    assert result["reconciled_job_ids"] == [job.id]
    rows = _rows(db, job.id)
    assert len(rows) == 1
    assert rows[0].reconciled_from_history is True
    assert rows[0].confirmation_evidence == (
        f"reconciled_from_naukri_history:naukri_job_id:{job.external_job_id}"
    )


def test_reconcile_from_history_rejects_inconsistent_external_id(db) -> None:
    """An id whose card shows a different role/company is ambiguous, not a write."""
    job = _make_job(db, "r16-idmismatch")
    service = ApplicationService(db)

    result = service.reconcile_from_history(
        [
            {
                "external_job_id": job.external_job_id,
                "title": "Completely Different Role",
                "company": "Other Company",
            }
        ]
    )

    assert result["reconciled_count"] == 0
    assert result["ambiguous"] == [f"naukri_job_id:{job.external_job_id}"]
    assert _rows(db, job.id) == []


def test_reconcile_from_history_matches_decorated_title_by_company(db) -> None:
    job = _make_job(db, "r16-decorated")
    service = ApplicationService(db)

    result = service.reconcile_from_history(
        [{"title": f"Immediate openings For {job.title}", "company": job.company}]
    )

    assert result["reconciled_job_ids"] == [job.id]
    assert len(_rows(db, job.id)) == 1


def test_reconcile_from_history_unknown_id_is_never_fuzzy_matched(db) -> None:
    """A card whose Naukri id is unknown locally must not write to a lookalike."""
    job = _make_job(db, "r16-lookalike")
    service = ApplicationService(db)

    result = service.reconcile_from_history(
        [
            {
                "external_job_id": "999999999999",
                "title": job.title,
                "company": job.company,
            }
        ]
    )

    assert result["reconciled_count"] == 0
    assert result["unmatched"] == ["naukri_job_id:999999999999"]
    assert _rows(db, job.id) == []
