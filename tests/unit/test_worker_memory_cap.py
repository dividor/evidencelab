"""The orchestrator kills a worker over the memory cap and fails its document.

Measured 2026-10-18: one 237-page PDF drove a worker to 41,984 MB (control
document: 5,784 MB), silently, and seven such workers kernel-panicked a 48 GB
machine. These tests exercise the real watchdog, the real orchestrator
collector, and -- in the end-to-end case -- a real spawn Pool.
"""

import multiprocessing
import os
import sys
import time
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import patch

import psutil
import pytest

import pipeline.orchestrator.core_processing as core
import pipeline.orchestrator.worker_memory_cap as cap
from pipeline.orchestrator.worker_memory_cap import (
    DEFAULT_MAX_WORKER_MEMORY_MB,
    WORKER_TITLE_PREFIX,
    WorkerMemoryWatchdog,
    max_worker_memory_mb,
    process_footprint_mb,
    worker_doc_from_title,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PIPELINE_MAX_WORKER_MEMORY_MB", raising=False)


class TestCapSetting:
    def test_default(self):
        assert max_worker_memory_mb() == DEFAULT_MAX_WORKER_MEMORY_MB

    def test_override(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MAX_WORKER_MEMORY_MB", "20480")
        assert max_worker_memory_mb() == 20480

    def test_zero_is_off(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MAX_WORKER_MEMORY_MB", "0")
        assert max_worker_memory_mb() == 0

    def test_invalid_is_a_configuration_error(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MAX_WORKER_MEMORY_MB", "lots")
        with pytest.raises(ValueError, match="PIPELINE_MAX_WORKER_MEMORY_MB"):
            max_worker_memory_mb()

    def test_negative_is_a_configuration_error(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MAX_WORKER_MEMORY_MB", "-5")
        with pytest.raises(ValueError):
            max_worker_memory_mb()


class TestTitleParsing:
    def test_idle_worker(self):
        assert worker_doc_from_title(["EvLab-Pipeline-4242"]) == (4242, None)

    def test_worker_on_document_single_argv(self):
        assert worker_doc_from_title(["EvLab-Pipeline-4242 doc-abc"]) == (
            4242,
            "doc-abc",
        )

    def test_worker_on_document_split_argv(self):
        assert worker_doc_from_title(["EvLab-Pipeline-4242", "doc-abc"]) == (
            4242,
            "doc-abc",
        )

    def test_other_processes_are_not_workers(self):
        assert worker_doc_from_title(["EvLab-Pipeline-Orchestrator"]) is None
        assert worker_doc_from_title(["EvLab-EmbedServer-99"]) is None
        assert worker_doc_from_title(["python3.11", "-m", "x"]) is None
        assert worker_doc_from_title([]) is None


class TestFootprint:
    def test_own_process_is_measurable_and_plausible(self):
        mb = process_footprint_mb(os.getpid())
        assert 5 < mb < 50_000

    @pytest.mark.skipif(sys.platform != "darwin", reason="phys_footprint is macOS-only")
    def test_darwin_matches_what_top_reports(self):
        """The cap must use the figure Activity Monitor/top show, not RSS."""
        import subprocess

        pid = os.getpid()
        out = (
            subprocess.run(
                ["top", "-l", "1", "-stats", "pid,mem", "-pid", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            .stdout.strip()
            .splitlines()[-1]
        )
        top_mem = out.split()[-1]
        top_mb = float(top_mem[:-1]) * (1024 if top_mem.endswith("G") else 1)
        ours = process_footprint_mb(pid)
        assert abs(ours - top_mb) <= max(64, top_mb * 0.15), (ours, top_mb)

    def test_missing_process_raises(self):
        with pytest.raises(psutil.NoSuchProcess):
            process_footprint_mb(2**22 + 12345)


class _FakeProc:
    def __init__(self, pid: int):
        self.pid = pid
        self.killed = False

    def kill(self):
        self.killed = True


class TestWatchdogCheck:
    def test_kills_only_workers_over_cap_and_reports_their_doc(self):
        big, small = _FakeProc(101), _FakeProc(102)
        breaches: List[Any] = []
        footprints = {101: 15000, 102: 5000}
        dog = WorkerMemoryWatchdog(
            12288,
            on_breach=lambda pid, doc, mb: breaches.append((pid, doc, mb)),
            workers_fn=lambda: [(big, "doc-big"), (small, "doc-small")],
        )
        with patch.object(
            cap, "process_footprint_mb", side_effect=lambda pid: footprints[pid]
        ):
            assert dog.check_once() == 1
        assert breaches == [(101, "doc-big", 15000)]
        assert big.killed and not small.killed

    def test_breach_callback_runs_before_the_kill(self):
        order: List[str] = []
        proc = _FakeProc(7)
        proc.kill = lambda: order.append("kill")  # type: ignore[method-assign]
        dog = WorkerMemoryWatchdog(
            100,
            on_breach=lambda *_: order.append("mark"),
            workers_fn=lambda: [(proc, "d")],
        )
        with patch.object(cap, "process_footprint_mb", return_value=101):
            dog.check_once()
        assert order == ["mark", "kill"]

    def test_vanished_worker_is_skipped(self):
        proc = _FakeProc(9)
        dog = WorkerMemoryWatchdog(
            100, on_breach=lambda *_: None, workers_fn=lambda: [(proc, "d")]
        )
        with patch.object(
            cap, "process_footprint_mb", side_effect=psutil.NoSuchProcess(9)
        ):
            assert dog.check_once() == 0
        assert not proc.killed

    def test_cap_zero_never_starts_the_thread(self):
        dog = WorkerMemoryWatchdog(0, on_breach=lambda *_: None, workers_fn=lambda: [])
        dog.start()
        assert not dog._thread.is_alive()
        dog.stop()

    def test_thread_runs_and_stops(self):
        calls: List[int] = []
        dog = WorkerMemoryWatchdog(
            100,
            on_breach=lambda *_: None,
            poll_seconds=0.05,
            workers_fn=lambda: calls.append(1) or [],
        )
        dog.start()
        time.sleep(0.3)
        dog.stop()
        assert len(calls) >= 2
        assert not dog._thread.is_alive()


class _FakeDB:
    def __init__(self):
        self.updates: List[Any] = []

    def get_document(self, doc_id):
        return None

    def update_document(self, doc_id, fields, wait=False):
        self.updates.append((doc_id, fields))


def _orch():
    return SimpleNamespace(db=_FakeDB(), data_dir="/data", pipeline_config={})


class TestOrchestratorSide:
    def test_breach_marks_doc_parse_failed_with_measured_figure(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_MAX_WORKER_MEMORY_MB", "12288")
        orch, killed = _orch(), set()
        core._fail_memory_capped_doc(orch, killed, 4242, "doc-x", 40960)
        assert killed == {"doc-x"}
        doc_id, fields = orch.db.updates[0]
        assert doc_id == "doc-x" and fields["sys_status"] == "parse_failed"
        assert "40960 MB > 12288 MB" in fields["sys_error_message"]

    def test_breach_without_doc_id_marks_nothing(self):
        orch, killed = _orch(), set()
        core._fail_memory_capped_doc(orch, killed, 4242, None, 40960)
        assert killed == set() and orch.db.updates == []

    def test_collector_returns_promptly_for_a_killed_doc(self):
        """A killed task never completes; the collector must not wait the full timeout."""
        orch = _orch()
        stats = {"processed": 0, "success": 0, "failed": 0}
        never = SimpleNamespace(
            ready=lambda: False, wait=lambda t: time.sleep(min(t, 0.01)), get=None
        )
        t0 = time.time()
        out = core._collect_result(
            orch, "doc-k", never, worker_timeout=3600, stats=stats, killed={"doc-k"}
        )
        assert out is None and time.time() - t0 < 2
        assert stats == {"processed": 1, "success": 0, "failed": 1}

    def test_collector_still_times_out_for_a_hung_doc(self):
        orch = _orch()
        stats = {"processed": 0, "success": 0, "failed": 0}
        never = SimpleNamespace(
            ready=lambda: False, wait=lambda t: time.sleep(min(t, 0.01))
        )
        with patch.object(core, "mark_as_stopped") as mark:
            out = core._collect_result(
                orch, "doc-h", never, worker_timeout=0, stats=stats, killed=set()
            )
        assert out is None and stats["failed"] == 1
        mark.assert_called_once()

    def test_collector_returns_a_ready_result(self):
        orch = _orch()
        stats = {"processed": 0, "success": 0, "failed": 0}
        res = SimpleNamespace(
            ready=lambda: True,
            get=lambda timeout: {"stages": {"parse": {"success": True}}},
        )
        out = core._collect_result(orch, "doc-ok", res, 5, stats, killed=set())
        assert out["stages"]["parse"]["success"] and stats["success"] == 1


def _hog(doc_id: str) -> str:
    """Pool task: take the worker title, then hold ~400 MB until killed."""
    import setproctitle  # imported in the child on purpose

    setproctitle.setproctitle(f"{WORKER_TITLE_PREFIX}{os.getpid()} {doc_id}")
    blob = bytearray(400 * 1024 * 1024)
    blob[::4096] = b"x" * len(blob[::4096])  # touch pages so they are really resident
    time.sleep(30)
    return "finished"


def _quick(doc_id: str) -> str:
    return f"ok-{doc_id}"


def test_end_to_end_real_pool_worker_over_cap_is_killed_and_pool_survives():
    """A real spawn Pool: the hog is killed by the watchdog, its document is failed,
    the collector returns promptly, and the pool still runs the next task."""
    ctx = multiprocessing.get_context("spawn")
    orch = _orch()
    killed: set = set()
    with ctx.Pool(processes=1) as pool:
        hog = pool.apply_async(_hog, ("doc-hog",))
        dog = WorkerMemoryWatchdog(
            cap_mb=200,
            on_breach=lambda pid, doc, mb: core._fail_memory_capped_doc(
                orch, killed, pid, doc, mb
            ),
            poll_seconds=0.5,
        )
        with patch.object(core, "max_worker_memory_mb", return_value=200):
            dog.start()
            stats = {"processed": 0, "success": 0, "failed": 0}
            t0 = time.time()
            out = core._collect_result(
                orch, "doc-hog", hog, worker_timeout=60, stats=stats, killed=killed
            )
            elapsed = time.time() - t0
            dog.stop()
    assert out is None, "the hog's task must be treated as failed, not awaited"
    assert "doc-hog" in killed
    assert (
        elapsed < 30
    ), f"collector waited {elapsed:.0f}s; it must return once the worker is killed"
    assert orch.db.updates and orch.db.updates[0][1]["sys_status"] == "parse_failed"
    assert "MB > 200 MB" in orch.db.updates[0][1]["sys_error_message"]
    # the pool replaced the dead worker and keeps working
    with ctx.Pool(processes=1) as pool2:
        assert pool2.apply_async(_quick, ("after",)).get(timeout=30) == "ok-after"
