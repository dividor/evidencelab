"""Pipeline orchestration logic."""

import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

import pipeline.orchestrator.env  # noqa: F401
from pipeline.db import get_db, load_datasources_config
from pipeline.orchestrator.core_docs import (
    apply_filters,
    collect_docs_by_stage,
    dedupe_docs_by_id,
    get_docs_by_status,
    get_documents_recent_first,
    get_partition_slice,
    sort_recent_first,
)
from pipeline.orchestrator.core_processing import mark_as_stopped, run_processing
from pipeline.orchestrator.log_config import setup_logging
from pipeline.processors import ScanProcessor
from pipeline.utilities.embedding_server import EmbeddingServerManager

logger = setup_logging()


class PipelineOrchestrator:
    """
    Unified pipeline orchestrator using processor classes.
    Uses ProcessPoolExecutor for parallel execution.
    """

    def __init__(
        self,
        data_source: str,
        skip_download: bool = False,
        skip_scan: bool = False,
        skip_parse: bool = False,
        skip_summarize: bool = False,
        skip_index: bool = False,
        skip_tag: bool = False,
        save_chunks: bool = False,
        num_records: int = 10,
        workers: int = 1,
        recent_first: bool = False,
        partition: str = None,
        report: str = None,
        agency: str = None,
        clear_db: bool = False,
        model_mode: str = "remote",
        year: int = None,
        from_year: int = None,
        to_year: int = None,
        doc_id: str = None,
    ):
        self.data_source = data_source
        self.doc_id = doc_id
        base_data_dir = os.getenv("DATA_MOUNT_PATH", "./data")
        self.data_dir = f"{base_data_dir}/{data_source}"
        self.skip_download = skip_download
        self.skip_scan = skip_scan
        self.skip_parse = skip_parse
        self.skip_summarize = skip_summarize
        self.skip_index = skip_index
        self.skip_tag = skip_tag
        self.save_chunks = save_chunks
        self.num_records = num_records
        self.workers = workers
        self.model_mode = model_mode
        self.year = year
        self.from_year = from_year
        self.to_year = to_year

        if self.workers > 1:
            os.environ["EMBEDDING_WORKERS"] = "1"
        self.recent_first = recent_first
        self.partition = partition
        self.report = report
        self.agency = agency
        self.clear_db = clear_db

        self.partition_num = None
        self.partition_total = None
        if self.partition:
            try:
                m, n = self.partition.split("/")
                self.partition_num = int(m)
                self.partition_total = int(n)
                if self.partition_num < 1 or self.partition_num > self.partition_total:
                    raise ValueError("Partition number out of range")
            except ValueError as exc:
                raise ValueError(
                    f"Invalid partition format '{self.partition}'. Use 'M/N' (e.g., '2/5')"
                ) from exc

        self.db = get_db(data_source)
        self.embedding_manager = EmbeddingServerManager()

        self._scanner: Optional[ScanProcessor] = None
        self.server_started = False

        full_config = load_datasources_config()
        datasources = full_config.get("datasources", full_config)
        self.pipeline_config = {}

        for key, val in datasources.items():
            if val.get("data_subdir") == self.data_source or key == self.data_source:
                self.pipeline_config = val.get("pipeline", {})
                break

        if not self.pipeline_config:
            logger.warning(
                "No pipeline config found for data source '%s'. using defaults.",
                self.data_source,
            )

    def setup_initial(self) -> None:
        """Initialize lightweight processors (Scanner)."""
        logger.info("\n" + "=" * 60)
        logger.info("INITIALIZING LIGHTWEIGHT PROCESSORS")
        logger.info("=" * 60)

        if not self.skip_scan:
            pdfs_dir = f"{self.data_dir}/pdfs"
            self._scanner = ScanProcessor(base_dir=pdfs_dir, db=self.db)
            self._scanner.setup()
            logger.info("✓ Scanner initialized")

        if self.model_mode == "local":
            logger.info("🔧 Model Mode: LOCAL (forcing in-process model loading)")
            if "EMBEDDING_API_URL" in os.environ:
                del os.environ["EMBEDDING_API_URL"]
        else:
            is_docker = os.path.exists("/.dockerenv")
            env_url = os.getenv("EMBEDDING_API_URL")

            if env_url:
                logger.info("Using configured Embedding API URL: %s", env_url)
            elif is_docker:
                default_docker_url = "http://embedding-server:7997"
                os.environ["EMBEDDING_API_URL"] = default_docker_url
                logger.info(
                    "Running in Docker. Defaulting to Embedding API URL: %s",
                    default_docker_url,
                )
            else:
                if not self.skip_index:
                    self.embedding_manager.start()
                    self.server_started = True
                    os.environ["EMBEDDING_API_URL"] = (
                        self.embedding_manager.get_client_url()
                    )
                    logger.info(
                        "Embedding API URL set to local: %s",
                        os.environ["EMBEDDING_API_URL"],
                    )
                else:
                    logger.info(
                        "Skipping embedding server start (--skip-index is enabled)"
                    )

    def teardown(self) -> None:
        """Stop worker resources and external services."""
        if self._scanner:
            self._scanner.teardown()
        if self.embedding_manager and self.server_started:
            self.embedding_manager.stop()

    def run_download(self) -> bool:
        """Run download step via subprocess."""
        if self.skip_download:
            logger.info("\n⏭️  Skipping download step")
            return True

        logger.info("\n" + "=" * 60)
        logger.info("STEP: Download (max %s documents)", self.num_records)
        logger.info("Download directory: %s", self.data_dir)
        logger.info("=" * 60)

        try:
            download_config = self.pipeline_config.get("download", {})
            command = download_config.get("command")
            if not command:
                logger.error(
                    "No download command configured for data source '%s'.",
                    self.data_source,
                )
                return False

            cmd = [sys.executable, command]
            args_template = download_config.get("args", [])
            values = {
                "data_dir": self.data_dir,
                "num_records": self.num_records,
                "year": self.year,
                "from_year": self.from_year,
                "to_year": self.to_year,
                "agency": self.agency,
                "report": self.report,
                "doc_id": self.doc_id,
            }
            placeholder_pattern = re.compile(r"^\{(\w+)\}$")
            cmd_args = []
            for arg in args_template:
                if not isinstance(arg, str):
                    cmd_args.append(str(arg))
                    continue
                match = placeholder_pattern.match(arg)
                if match:
                    key = match.group(1)
                    value = values.get(key)
                    if value is None:
                        if cmd_args and cmd_args[-1].startswith("--"):
                            cmd_args.pop()
                        continue
                    cmd_args.append(str(value))
                else:
                    cmd_args.append(arg)
            cmd.extend(cmd_args)
            logger.info("Download command: %s", " ".join(cmd))
            subprocess.run(cmd, check=True, capture_output=False, text=True)
            logger.info("✅ Download completed successfully")
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("❌ Download failed with exit code %s", exc.returncode)
            return False
        except OSError as exc:
            logger.error("❌ Download failed: %s", exc)
            return False

    def run_scan(self) -> bool:
        """Run scan step to sync filesystem to Qdrant."""
        if self.skip_scan:
            logger.info("\n⏭️  Skipping scan step")
            return True

        if self.report or self.doc_id:
            if not self._scanner:
                pdfs_dir = f"{self.data_dir}/pdfs"
                self._scanner = ScanProcessor(base_dir=pdfs_dir, db=self.db)
                self._scanner.setup()
            logger.info("\n⏭️  Skipping full scan (targeted scan for single document)")
            return self._scanner.scan_and_sync_single(
                report_path=self.report, doc_id=self.doc_id
            )

        logger.info("\n" + "=" * 60)
        logger.info("STEP: Scan files and sync to Qdrant")
        logger.info("=" * 60)

        try:
            _ = self._scanner.scan_and_sync()
            logger.info("✅ Scan completed successfully")
            return True
        except (OSError, RuntimeError) as exc:
            logger.error("❌ Scan failed: %s", exc)
            return False

    def _get_documents_recent_first(self, status: str, limit: int = None) -> list:
        return get_documents_recent_first(self.db, status, limit=limit)

    def _get_docs_by_status(self, status: str) -> list:
        return get_docs_by_status(self.db, status, self.recent_first)

    def _collect_docs_by_stage(self) -> list:
        return collect_docs_by_stage(
            self.db,
            self.skip_index,
            self.skip_tag,
            self.skip_summarize,
            self.skip_parse,
            self.report,
            self.recent_first,
        )

    def _dedupe_docs_by_id(self, docs: list) -> list:
        return dedupe_docs_by_id(docs)

    def _apply_filters(self, docs: list) -> list:
        return apply_filters(docs, self.agency, self.report)

    def _sort_recent_first(self, docs: list) -> list:
        return sort_recent_first(docs)

    def get_partition_slice(self, docs: list) -> list:
        """Apply partitioning to a document list."""
        return get_partition_slice(docs, self.partition_num, self.partition_total)

    def run_processing(self, limit: int = None) -> Dict[str, Any]:
        """Run the main processing pipeline for selected documents."""
        return run_processing(self, limit=limit)

    def _mark_as_stopped(self, doc_id: str, reason: str) -> None:
        mark_as_stopped(self, doc_id, reason)

    def run(self) -> bool:
        """Run the complete pipeline."""
        start_time = time.time()

        logger.info("\n" + "=" * 60)
        logger.info("HUMANITARIAN EVALUATION DOCUMENT PROCESSING PIPELINE")
        logger.info("=" * 60)
        logger.info("Data source: %s", self.data_source)
        logger.info("Workers: %s", self.workers)
        logger.info("Clear DB: %s", self.clear_db)
        logger.info("Recent First: %s", self.recent_first)

        try:
            if self.clear_db:
                logger.info("\n⚠️  CLEAR-DB FLAG SET: WIPING ALL DATA")
                self.db.clear_all_data()

            self.setup_initial()

            if not self.run_download():
                return False

            if not self.run_scan():
                return False

            if not (
                self.skip_parse
                and self.skip_summarize
                and self.skip_index
                and self.skip_tag
            ):
                stats = self.run_processing(limit=self.num_records)
            else:
                stats = {"processed": 0, "success": 0, "failed": 0}

            elapsed = time.time() - start_time
            logger.info("\n" + "=" * 60)
            logger.info("PIPELINE COMPLETE")
            logger.info("=" * 60)
            logger.info("Total time: %.1fs", elapsed)

            return stats["failed"] == 0

        finally:
            self.teardown()
