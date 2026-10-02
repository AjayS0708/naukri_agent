from pathlib import Path
from unittest.mock import Mock

import pytest

import phase10_live_apply_launcher as launcher


def test_forbidden_sp_global_job_is_rejected():
    with pytest.raises(RuntimeError, match="300926927428"):
        launcher.reject_forbidden_job("300926927428")


def test_wrong_proceed_confirmation_aborts():
    assert not launcher.exact_confirmation("PROCEED wrong", "PROCEED", "240926500723")


def test_wrong_submit_confirmation_aborts():
    assert not launcher.exact_confirmation("SUBMIT 240926500000", "SUBMIT", "240926500723")


def test_backup_failure_aborts_before_write(tmp_path):
    def fail_copy(_source, _destination):
        raise OSError("disk full")

    with pytest.raises(RuntimeError, match="Database backup failed"):
        launcher.backup_database(
            tmp_path / "source.db",
            tmp_path / "backup.db",
            copier=fail_copy,
        )


@pytest.mark.asyncio
async def test_ambiguous_classification_aborts_without_runner(monkeypatch):
    class FakeAdapter:
        async def detect_application_type(self, _page):
            return "AMBIGUOUS"

    runner = Mock()
    first, second = await launcher.classify_twice(FakeAdapter(), object())
    assert (first, second) == ("AMBIGUOUS", "AMBIGUOUS")
    runner.run_applications.assert_not_called()


def test_backup_success_creates_copy(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    source.write_bytes(b"sqlite")
    assert launcher.backup_database(source, destination) == destination
    assert destination.read_bytes() == b"sqlite"
