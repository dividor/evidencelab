"""Kill a pipeline worker whose memory footprint exceeds a cap, and fail its document.

Measured on a 48 GB Mac mini (2026-10-18): a single 237-page PDFKit.NET PDF
drove one worker from ~5 GB to **41,984 MB** inside Docling's convert, silent in
the log, while an ordinary 190-page document peaked at 5,784 MB. Seven such
workers took the machine to swap exhaustion, load 400 and a kernel panic --
twice in one day. The run never noticed, because the ballooning worker emits no
log line and the document is never marked.

This watchdog runs in the orchestrator, measures every worker every few seconds,
and when one crosses ``PIPELINE_MAX_WORKER_MEMORY_MB`` it fails that document
with an explicit reason, kills the worker, and lets the pool replace it. The run
continues with the rest of the queue.

Which number is measured matters. On macOS, ``psutil`` RSS **understates** a
ballooning worker by more than an order of magnitude (218 MB RSS against a
3,821 MB footprint on a healthy worker; 1.4 GB against 40 GB on a bad one),
because compressed and swapped pages are excluded. The figure Activity Monitor
and ``top`` show is ``phys_footprint`` from ``proc_pid_rusage``, so that is what
is used on Darwin. On Linux, where there is no compressor, RSS is accurate.

``PIPELINE_MAX_WORKER_MEMORY_MB`` defaults to 12288 (12 GB, roughly twice the
steady-state footprint). ``0`` turns the cap off. Only the parallel path
(``--workers > 1``) is covered: a sequential run processes documents in the
orchestrator process itself, which cannot be killed without ending the run.
"""

import ctypes
import ctypes.util
import logging
import os
import struct
import sys
import threading
from typing import Callable, Iterable, Optional, Tuple

import psutil

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKER_MEMORY_MB = 12288
DEFAULT_POLL_SECONDS = 5.0

# Worker process titles are "EvLab-Pipeline-<pid>" at idle and
# "EvLab-Pipeline-<pid> <doc_id>" while a document is being processed.
WORKER_TITLE_PREFIX = "EvLab-Pipeline-"

# struct rusage_info_v0: uint8_t ri_uuid[16]; then ten uint64_t fields, of which
# ri_phys_footprint is the eighth (offset 16 + 7 * 8 = 72). Validated live
# against ``top`` on macOS 26.1 (3821 MB == 3821M).
_RUSAGE_INFO_V0 = 0
_PHYS_FOOTPRINT_OFFSET = 72
_RUSAGE_BUFFER_BYTES = 2048


def max_worker_memory_mb() -> int:
    """The per-worker cap in MB, from the environment; 0 means off."""
    raw = os.getenv("PIPELINE_MAX_WORKER_MEMORY_MB")
    if raw is None or not raw.strip():
        return DEFAULT_MAX_WORKER_MEMORY_MB
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"PIPELINE_MAX_WORKER_MEMORY_MB must be an integer number of MB, got {raw!r}"
        ) from exc
    if value < 0:
        raise ValueError(f"PIPELINE_MAX_WORKER_MEMORY_MB must be >= 0, got {value}")
    return value


def _darwin_phys_footprint_bytes(pid: int) -> int:
    libproc = ctypes.CDLL(ctypes.util.find_library("proc"))
    buf = ctypes.create_string_buffer(_RUSAGE_BUFFER_BYTES)
    rc = libproc.proc_pid_rusage(
        ctypes.c_int(pid), ctypes.c_int(_RUSAGE_INFO_V0), ctypes.byref(buf)
    )
    if rc != 0:
        raise psutil.NoSuchProcess(pid, msg=f"proc_pid_rusage returned {rc}")
    return struct.unpack_from("<Q", buf.raw, _PHYS_FOOTPRINT_OFFSET)[0]


def process_footprint_mb(pid: int) -> int:
    """Memory actually attributable to ``pid``, in MB, as the OS accounts it."""
    if sys.platform == "darwin":
        return _darwin_phys_footprint_bytes(pid) // (1024 * 1024)
    return psutil.Process(pid).memory_info().rss // (1024 * 1024)


def worker_doc_from_title(
    cmdline: Iterable[str],
) -> Optional[Tuple[int, Optional[str]]]:
    """Parse ``EvLab-Pipeline-<pid> [doc_id]`` from a process command line."""
    parts = list(cmdline)
    if not parts or not parts[0].startswith(WORKER_TITLE_PREFIX):
        return None
    head = parts[0].split()
    try:
        pid = int(head[0][len(WORKER_TITLE_PREFIX) :])
    except ValueError:
        return None
    doc_id = head[1] if len(head) > 1 else (parts[1] if len(parts) > 1 else None)
    return pid, doc_id


def find_workers(parent_pid: Optional[int] = None) -> list:
    """Pool workers of this orchestrator: children whose title carries the prefix.

    The embedding server and the orchestrator itself use other titles and are
    excluded by the prefix.
    """
    parent = psutil.Process(parent_pid or os.getpid())
    found = []
    for child in parent.children(recursive=True):
        try:
            parsed = worker_doc_from_title(child.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if parsed is not None:
            found.append((child, parsed[1]))
    return found


class WorkerMemoryWatchdog:
    """Background thread that kills any worker over the cap and reports it."""

    def __init__(
        self,
        cap_mb: int,
        on_breach: Callable[[int, Optional[str], int], None],
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        workers_fn: Callable[[], list] = find_workers,
    ) -> None:
        self.cap_mb = cap_mb
        self.on_breach = on_breach
        self.poll_seconds = poll_seconds
        self.workers_fn = workers_fn
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="worker-memory-watchdog", daemon=True
        )

    def start(self) -> None:
        if self.cap_mb <= 0:
            logger.info("Worker memory cap is off (PIPELINE_MAX_WORKER_MEMORY_MB=0)")
            return
        logger.info(
            "Worker memory cap armed: %s MB per worker, checked every %.0fs",
            self.cap_mb,
            self.poll_seconds,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.poll_seconds * 2)

    def check_once(self) -> int:
        """Measure every worker; kill and report those over the cap. Returns kills."""
        kills = 0
        for proc, doc_id in self.workers_fn():
            try:
                footprint = process_footprint_mb(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if footprint <= self.cap_mb:
                continue
            logger.error(
                "🛑 Worker %s exceeded the memory cap: %s MB > %s MB while on document %s"
                " — killing it and failing the document",
                proc.pid,
                footprint,
                self.cap_mb,
                doc_id or "(unknown)",
            )
            self.on_breach(proc.pid, doc_id, footprint)
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
            kills += 1
        return kills

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.check_once()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Worker memory watchdog check failed")
