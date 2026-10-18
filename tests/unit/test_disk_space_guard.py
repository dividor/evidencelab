"""The pipeline stops itself when the data disk fills.

Measured on a UNEG backfill: disco1 reached 100% and 30 documents were failed
one by one with ``OSError: [Errno 28] No space left on device``, each marked
``parse_failed`` as though the document were bad. These tests exercise the
real guard and the real orchestrator code paths; only disk and worker I/O
are stubbed.
"""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import pipeline.orchestrator.cli as cli
import pipeline.orchestrator.core_processing as core
import pipeline.utilities.disk_space as ds
from pipeline.utilities.disk_space import (
    DEFAULT_MIN_FREE_DISK_MB,
    DiskSpaceExhausted,
    ensure_disk_space,
    min_free_disk_mb,
    result_reports_disk_full,
)

pytestmark = pytest.mark.unit

MB = 1024 * 1024
ENOSPC = "OSError: [Errno 28] No space left on device: '/Volumes/disco1/x.json'"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PIPELINE_MIN_FREE_DISK_MB", raising=False)


def _disk(free_mb: int):
    """Patch shutil.disk_usage to report ``free_mb`` free."""
    return patch.object(
        ds.shutil, "disk_usage", return_value=SimpleNamespace(free=free_mb * MB)
    )


def _orchestrator(**overrides):
    base = dict(
        data_dir="/data/uneg",
        data_source="uneg",
        skip_parse=False,
        skip_summarize=False,
        skip_index=False,
        skip_tag=False,
        save_chunks=False,
        pipeline_config={"processing_timeout": 5},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ok_result():
    return {"stages": {"parse": {"success": True}, "index": {"success": True}}}


def _enospc_result():
    return {"stages": {"parse": {"success": False, "error": ENOSPC}}}


class TestMinFreeDiskMb:
    def test_unset_uses_default(self):
        assert min_free_disk_mb() == DEFAULT_MIN_FREE_DISK_MB

    def test_blank_uses_default(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "   ")
        assert min_free_disk_mb() == DEFAULT_MIN_FREE_DISK_MB

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "20480")
        assert min_free_disk_mb() == 20480

    def test_zero_is_allowed_as_off_switch(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "0")
        assert min_free_disk_mb() == 0

    def test_non_integer_is_a_configuration_error(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "five gigs")
        with pytest.raises(ValueError, match="PIPELINE_MIN_FREE_DISK_MB"):
            min_free_disk_mb()

    def test_negative_is_a_configuration_error(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "-1")
        with pytest.raises(ValueError, match=">= 0"):
            min_free_disk_mb()


class TestEnsureDiskSpace:
    def test_below_floor_raises_with_actionable_message(self):
        with _disk(167):
            with pytest.raises(DiskSpaceExhausted) as info:
                ensure_disk_space("/data/uneg", "before starting workers")
        msg = str(info.value)
        assert "167 MB free" in msg
        assert "/data/uneg" in msg
        assert "reset_failed_statuses.py --include-stuck" in msg

    def test_above_floor_returns_free_mb(self):
        with _disk(50_000):
            assert ensure_disk_space("/data/uneg", "x") == 50_000

    def test_floor_zero_never_raises(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "0")
        with _disk(0):
            assert ensure_disk_space("/data/uneg", "x") == 0

    def test_custom_floor_is_respected(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MIN_FREE_DISK_MB", "100")
        with _disk(99):
            with pytest.raises(DiskSpaceExhausted):
                ensure_disk_space("/d", "x")
        with _disk(100):
            ensure_disk_space("/d", "x")


class TestResultReportsDiskFull:
    def test_top_level_error(self):
        assert result_reports_disk_full({"error": ENOSPC}) is True

    def test_stage_error_no_space_phrase(self):
        assert result_reports_disk_full(_enospc_result()) is True

    def test_stage_error_errno_only(self):
        r = {"stages": {"index": {"success": False, "error": "[Errno 28] boom"}}}
        assert result_reports_disk_full(r) is True

    def test_clean_result(self):
        assert result_reports_disk_full(_ok_result()) is False

    def test_unrelated_failure(self):
        r = {"stages": {"parse": {"success": False, "error": "Empty markdown"}}}
        assert result_reports_disk_full(r) is False

    def test_non_dict_and_none(self):
        assert result_reports_disk_full(None) is False
        assert result_reports_disk_full("ENOSPC") is False

    def test_non_dict_stage_values_are_ignored(self):
        assert result_reports_disk_full({"stages": {"parse": "weird"}}) is False


class TestStopIfDiskFull:
    def test_worker_enospc_stops_even_with_free_space(self):
        """A real ENOSPC from a worker is definitive, whatever statvfs says."""
        orch = _orchestrator()
        with _disk(500_000):
            with pytest.raises(DiskSpaceExhausted, match="No space left on device"):
                core._stop_if_disk_full(orch, "doc-1", _enospc_result())

    def test_low_free_space_stops_after_clean_result(self):
        orch = _orchestrator()
        with _disk(10):
            with pytest.raises(DiskSpaceExhausted, match="after document doc-1"):
                core._stop_if_disk_full(orch, "doc-1", _ok_result())

    def test_clean_result_and_space_continues(self):
        with _disk(500_000):
            core._stop_if_disk_full(_orchestrator(), "doc-1", _ok_result())

    def test_none_result_after_crash_is_tolerated(self):
        with _disk(500_000):
            core._stop_if_disk_full(_orchestrator(), "doc-1", None)


class TestSequentialPathStopsFeeding:
    """The real _process_docs_sequential must not feed the next document."""

    def test_enospc_on_first_doc_stops_before_second(self):
        orch = _orchestrator()
        docs = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
        stats = {"processed": 0, "success": 0, "failed": 0}
        calls = []

        def fake_wrapper(doc):
            calls.append(doc["id"])
            return _enospc_result()

        with patch.object(core, "init_worker"), patch.object(
            core, "process_document_wrapper", side_effect=fake_wrapper
        ), _disk(500_000):
            with pytest.raises(DiskSpaceExhausted):
                core._process_docs_sequential(orch, docs, stats)

        assert calls == ["a"], "the second document must never be fed"
        assert stats["processed"] == 1 and stats["failed"] == 1

    def test_full_disk_at_start_feeds_nothing(self):
        orch = _orchestrator()
        stats = {"processed": 0, "success": 0, "failed": 0}
        with patch.object(core, "init_worker"), patch.object(
            core, "process_document_wrapper"
        ) as wrapper, _disk(1):
            with pytest.raises(DiskSpaceExhausted, match="before document a"):
                core._process_docs_sequential(orch, [{"id": "a"}], stats)
        wrapper.assert_not_called()

    def test_healthy_run_processes_every_document(self):
        orch = _orchestrator()
        docs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        stats = {"processed": 0, "success": 0, "failed": 0}
        with patch.object(core, "init_worker"), patch.object(
            core, "process_document_wrapper", return_value=_ok_result()
        ), _disk(500_000):
            core._process_docs_sequential(orch, docs, stats)
        assert stats == {"processed": 3, "success": 3, "failed": 0}


class TestParallelPathPieces:
    """_process_docs_parallel's per-result logic, without spawning a real pool."""

    def test_startup_check_runs_before_pool_is_built(self):
        orch = _orchestrator(workers=2)
        with patch.object(core.multiprocessing, "get_context") as ctx, _disk(1):
            with pytest.raises(DiskSpaceExhausted, match="before starting workers"):
                core._process_docs_parallel(orch, [{"id": "a"}], {})
        ctx.return_value.Pool.assert_not_called()

    def test_collect_result_records_success(self):
        orch = _orchestrator()
        stats = {"processed": 0, "success": 0, "failed": 0}
        res = SimpleNamespace(ready=lambda: True, get=lambda timeout: _ok_result())
        out = core._collect_result(orch, "a", res, 5, stats)
        assert out == _ok_result()
        assert stats == {"processed": 1, "success": 1, "failed": 0}

    def test_collect_result_records_stage_failure(self):
        orch = _orchestrator()
        stats = {"processed": 0, "success": 0, "failed": 0}
        res = SimpleNamespace(ready=lambda: True, get=lambda timeout: _enospc_result())
        out = core._collect_result(orch, "a", res, 5, stats)
        assert result_reports_disk_full(out)
        assert stats["failed"] == 1

    def test_collect_result_timeout_marks_stopped_and_returns_none(self):
        orch = _orchestrator()
        stats = {"processed": 0, "success": 0, "failed": 0}

        def boom(timeout):
            raise TimeoutError()

        with patch.object(core, "mark_as_stopped") as mark:
            out = core._collect_result(orch, "a", SimpleNamespace(get=boom), 5, stats)
        assert out is None
        mark.assert_called_once()
        assert stats["failed"] == 1


class TestCliExitCode:
    def test_disk_full_exits_with_distinct_status(self, monkeypatch):
        class _Orch:
            def __init__(self, **kwargs):
                pass

            def run(self):
                raise DiskSpaceExhausted("disk full")

        monkeypatch.setattr(sys, "argv", ["prog", "--data-source", "uneg"])
        with patch.object(cli, "PipelineOrchestrator", _Orch), patch.object(
            cli.env, "configure_thread_env"
        ), patch.object(cli.setproctitle, "setproctitle"):
            with pytest.raises(SystemExit) as info:
                cli.main()
        assert info.value.code == cli.EXIT_DISK_FULL
        assert cli.EXIT_DISK_FULL not in (
            0,
            1,
        ), "must be distinguishable from pass/fail"
