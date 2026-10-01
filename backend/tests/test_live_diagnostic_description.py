import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.models.job import Job
from backend.services.naukri.adapter import NaukriAdapter


def _load_diagnostic_module():
    script_path = Path(__file__).parents[2] / "diagnose_live_dry_run.py"
    original_submit = NaukriAdapter.submit_application
    spec = importlib.util.spec_from_file_location("diagnose_live_dry_run", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        NaukriAdapter.submit_application = original_submit
    return module


@pytest.mark.asyncio
async def test_live_diagnostic_fetches_and_persists_job_description():
    diagnostic = _load_diagnostic_module()
    adapter = type("Adapter", (), {})()
    adapter.fetch_job_description = AsyncMock(return_value="  Full job description  ")
    job = Job(
        platform="naukri",
        external_job_id="123",
        url="https://www.naukri.com/job-123",
        title="Data Analyst",
        company="Example",
    )

    result = await diagnostic._ensure_job_description(adapter, job)

    assert result == "Full job description"
    assert job.description == "Full job description"
    adapter.fetch_job_description.assert_awaited_once_with(job.url)


@pytest.mark.asyncio
async def test_live_diagnostic_does_not_refetch_existing_description():
    diagnostic = _load_diagnostic_module()
    adapter = type("Adapter", (), {})()
    adapter.fetch_job_description = AsyncMock()
    job = Job(
        platform="naukri",
        external_job_id="123",
        url="https://www.naukri.com/job-123",
        title="Data Analyst",
        company="Example",
        description="Existing description",
    )

    result = await diagnostic._ensure_job_description(adapter, job)

    assert result == "Existing description"
    adapter.fetch_job_description.assert_not_awaited()
