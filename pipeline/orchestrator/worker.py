"""Worker helpers for orchestrator processing."""

import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

import psutil
import setproctitle
from fastembed import TextEmbedding

from pipeline.db import Database, get_db
from pipeline.orchestrator import env
from pipeline.orchestrator.logging import setup_logging
from pipeline.processors import (
    IndexProcessor,
    ParseProcessor,
    SummarizeProcessor,
    TaggerProcessor,
)
from pipeline.utilities.embedding_client import RemoteEmbeddingClient
from pipeline.utilities.logging_utils import _log_context

logger = setup_logging()

# Global context for worker processes
_worker_context: Dict[str, Any] = {}


def _get_context_component(key: str, component_type):
    if key in _worker_context:
        return cast(component_type, _worker_context[key])
    return None


def _wait_for_available_memory() -> Optional[str]:
    start_wait = time.time()
    while True:
        mem = psutil.virtual_memory()
        if mem.available > 2 * 1024 * 1024 * 1024:  # 2GB
            return None
        if time.time() - start_wait > 600:  # 10 min timeout
            return "OOM Protection: Timeout waiting for memory"
        time.sleep(random.uniform(5, 15))


def _reload_document(db: Database, doc_id: str) -> Optional[Dict[str, Any]]:
    reloaded = db.get_document(doc_id)
    if reloaded:
        reloaded["id"] = doc_id
    return reloaded


def _set_stage_elapsed(
    stage_result: Dict[str, Any], stage: str, stage_start: float
) -> None:
    if "updates" in stage_result and "sys_stages" in stage_result["updates"]:
        if stage in stage_result["updates"]["sys_stages"]:
            stage_result["updates"]["sys_stages"][stage]["elapsed_seconds"] = round(
                time.time() - stage_start, 1
            )


def _run_parse_stage(
    parser: Optional[ParseProcessor],
    db: Database,
    doc: Dict[str, Any],
    result: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    if not parser or doc.get("sys_status") != "downloaded":
        return doc, True

    stage_start = time.time()
    db.update_document(doc["id"], {"sys_status": "parsing"})
    parse_result = parser.process_document(doc)
    _set_stage_elapsed(parse_result, "parse", stage_start)
    result["stages"]["parse"] = parse_result

    if parse_result["success"]:
        doc.update(parse_result["updates"])
        db.update_document(doc["id"], parse_result["updates"])
        logger.info("  ✓ Parsed (%s): %s", os.getpid(), result["title"])
        return doc, True

    db.update_document(doc["id"], parse_result["updates"])
    logger.error(
        "  ✗ Parse failed (%s): %s - %s",
        os.getpid(),
        result["title"],
        parse_result.get("error"),
    )
    _generate_processing_log(doc["id"], doc.get("sys_parsed_folder"))
    return doc, False


def _run_summarize_stage(
    summarizer: Optional[SummarizeProcessor],
    db: Database,
    doc: Dict[str, Any],
    result: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    if not summarizer or doc.get("sys_status") not in ["parsed", "downloaded"]:
        return doc, True

    reloaded = _reload_document(db, doc["id"])
    if reloaded:
        doc = reloaded

    stage_start = time.time()
    db.update_document(doc["id"], {"sys_status": "summarizing"})
    sum_result = summarizer.process_document(doc)
    _set_stage_elapsed(sum_result, "summarize", stage_start)
    result["stages"]["summarize"] = sum_result

    if sum_result["success"]:
        doc.update(sum_result["updates"])
        db.update_document(doc["id"], sum_result["updates"])
        return doc, True

    db.update_document(doc["id"], sum_result["updates"])
    logger.error("  ✗ Summarize failed (%s): %s", os.getpid(), result["title"])
    _generate_processing_log(doc["id"], doc.get("sys_parsed_folder"))
    return doc, False


def _run_tag_stage(
    tagger: Optional[TaggerProcessor],
    db: Database,
    doc: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    if not tagger or doc.get("sys_status") != "summarized":
        return doc

    reloaded = _reload_document(db, doc["id"])
    if reloaded:
        doc = reloaded

    stage_start = time.time()
    db.update_document(doc["id"], {"sys_status": "tagging"})
    tag_result = tagger.classify_toc_only(doc)

    elapsed = round(time.time() - stage_start, 1)
    if tag_result.get("success"):
        tag_result["elapsed_seconds"] = elapsed
        reloaded_for_timing = db.get_document(doc["id"])
        if reloaded_for_timing and reloaded_for_timing.get("sys_stages", {}).get("tag"):
            reloaded_for_timing["sys_stages"]["tag"]["elapsed_seconds"] = elapsed
            db.update_document(
                doc["id"], {"sys_stages": reloaded_for_timing["sys_stages"]}
            )

    result["stages"]["tag"] = tag_result

    if tag_result.get("success"):
        doc["sys_status"] = "tagged"
        logger.info("  ✓ TOC Classified (%s): %s", os.getpid(), result["title"])
    else:
        logger.error("  ✗ Tag failed (%s): %s", os.getpid(), result["title"])

    return doc


def _run_index_stage(
    indexer: Optional[IndexProcessor],
    tagger: Optional[TaggerProcessor],
    db: Database,
    doc: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    if not indexer or doc.get("sys_status") not in [
        "tagged",
        "summarized",
        "parsed",
        "downloaded",
    ]:
        return

    reloaded = _reload_document(db, doc["id"])
    if reloaded:
        doc = reloaded

    stage_start = time.time()
    db.update_document(doc["id"], {"sys_status": "indexing"})
    save_chunks = _worker_context.get("save_chunks", False)
    idx_result = indexer.process_document(doc, save_chunks=save_chunks)
    _set_stage_elapsed(idx_result, "index", stage_start)
    result["stages"]["index"] = idx_result

    if idx_result["success"]:
        db.update_document(doc["id"], idx_result["updates"])
        logger.info("  ✓ Indexed (%s): %s", os.getpid(), result["title"])
        if tagger:
            reloaded = _reload_document(db, doc["id"])
            if reloaded:
                chunk_tag_result = tagger.tag_chunks_only(reloaded)
                if chunk_tag_result.get("success"):
                    logger.info(
                        "  ✓ Chunks tagged (%s): %s", os.getpid(), result["title"]
                    )
    else:
        db.update_document(doc["id"], idx_result["updates"])
        logger.error(
            "  ✗ Index failed (%s): %s - %s",
            os.getpid(),
            result["title"],
            idx_result.get("error"),
        )


def _generate_processing_log(doc_id: str, parsed_folder: Optional[str]) -> None:
    """
    Generate processing.log file for a document by extracting logs from orchestrator logs.
    """
    if not parsed_folder:
        return

    try:
        data_mount_path = os.getenv("DATA_MOUNT_PATH", "./data")
        if parsed_folder.startswith("data/"):
            parsed_folder = os.path.join(data_mount_path, parsed_folder[5:])

        parsed_folder = os.path.normpath(parsed_folder)

        repo_root = Path(__file__).resolve().parents[2]
        analyze_logs_script = repo_root / "scripts" / "utils" / "analyze_logs.py"

        if not analyze_logs_script.exists():
            logger.warning("analyze_logs.py not found at %s", analyze_logs_script)
            return

        log_dir = os.getenv("LOG_DIR")
        if log_dir:
            if not os.path.isabs(log_dir):
                log_dir = str(repo_root / log_dir)
        else:
            log_dir = str(repo_root / "logs")
        if not os.path.exists(log_dir) and os.path.exists("/app/logs"):
            log_dir = "/app/logs"
        if not os.path.exists(log_dir):
            logger.warning("Log directory not found: %s", log_dir)
            return

        current_log_file = os.path.join(log_dir, "orchestrator.log")
        if not os.path.exists(current_log_file):
            logger.warning("Current orchestrator.log not found at %s", current_log_file)
            return

        doc_id_str = str(doc_id)
        result = subprocess.run(
            [
                sys.executable,
                str(analyze_logs_script),
                current_log_file,
                "--file-id",
                doc_id_str,
                "--parsed-folder",
                parsed_folder,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        if doc_id_str.isdigit():
            result = subprocess.run(
                [
                    sys.executable,
                    str(analyze_logs_script),
                    current_log_file,
                    "--file-id",
                    str(int(doc_id_str)),
                    "--parsed-folder",
                    parsed_folder,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

        log_file_path = os.path.join(parsed_folder, "processing.log")
        if os.path.exists(log_file_path):
            logger.debug("Generated processing.log for %s at %s", doc_id, log_file_path)
        elif result.stderr:
            logger.debug(
                "Log generation for %s produced stderr: %s",
                doc_id,
                result.stderr[:200],
            )

    except subprocess.TimeoutExpired:
        logger.warning("Log generation timed out for %s", doc_id)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning("Error generating processing.log for %s: %s", doc_id, exc)


def init_worker(
    data_source: str,
    skip_parse: bool,
    skip_summarize: bool,
    skip_index: bool,
    skip_tag: bool,
    save_chunks: bool = False,
    pipeline_config: Dict[str, Any] = None,
):
    """
    Initialize global processors for a worker process.
    This runs once when the worker starts.
    """
    _set_worker_env()

    global logger
    logger = setup_logging()

    global _worker_context
    _worker_context["data_source"] = data_source
    _worker_context["save_chunks"] = save_chunks

    _worker_context["db"] = get_db(data_source)

    logger.info("[Worker %s] Initializing processors...", os.getpid())

    setproctitle.setproctitle(f"EvLab-Pipeline-{os.getpid()}")

    shared_dense_model = _init_shared_model(skip_index, skip_tag, skip_summarize)
    _worker_context["shared_model"] = shared_dense_model

    if not skip_parse:
        _init_parser(data_source)
    if not skip_summarize:
        _init_summarizer(pipeline_config, shared_dense_model)
    if not skip_index:
        _init_indexer(pipeline_config, shared_dense_model)
    if not skip_tag:
        _init_tagger(data_source, pipeline_config, shared_dense_model)

    logger.info("[Worker %s] Ready.", os.getpid())


def _set_worker_env() -> None:
    env.configure_thread_env()


def _init_shared_model(
    skip_index: bool, skip_tag: bool, skip_summarize: bool
) -> Any | None:
    if skip_index and skip_tag and skip_summarize:
        return None
    try:
        model_name = os.getenv(
            "DENSE_EMBEDDING_MODEL", "intfloat/multilingual-e5-large"
        )
        embedding_api_url = os.getenv("EMBEDDING_API_URL")
        if embedding_api_url:
            logger.info(
                "[Worker %s] Connecting to embedding server at %s",
                os.getpid(),
                embedding_api_url,
            )
            return RemoteEmbeddingClient(
                base_url=embedding_api_url, model_name=model_name
            )
        logger.info(
            "[Worker %s] Loading local embedding model: %s",
            os.getpid(),
            model_name,
        )
        return TextEmbedding(model_name=model_name)
    except (RuntimeError, OSError, ValueError) as exc:
        logger.error("Failed to load embedding model: %s", exc)
        raise RuntimeError("Failed to load embedding model") from exc


def _init_parser(data_source: str) -> None:
    base_data_dir = os.getenv("DATA_MOUNT_PATH", "./data")
    data_dir = f"{base_data_dir}/{data_source}"
    parsed_dir = f"{data_dir}/parsed"
    parser = ParseProcessor(output_dir=parsed_dir)
    parser.setup()
    _worker_context["parser"] = parser


def _init_summarizer(
    pipeline_config: Dict[str, Any], shared_dense_model: Any | None
) -> None:
    sum_config = pipeline_config.get("summarize", {}) if pipeline_config else {}
    if not sum_config.get("enabled", True):
        return
    summarizer = SummarizeProcessor(config=sum_config)
    summarizer.setup(embedding_model=shared_dense_model)
    _worker_context["summarizer"] = summarizer


def _init_indexer(
    pipeline_config: Dict[str, Any], shared_dense_model: Any | None
) -> None:
    idx_config = pipeline_config.get("index", {}) if pipeline_config else {}
    chunk_config = pipeline_config.get("chunk", {}) if pipeline_config else {}
    indexer = IndexProcessor(
        db=_worker_context["db"], index_config=idx_config, chunk_config=chunk_config
    )
    indexer.setup(dense_model=shared_dense_model)
    _worker_context["indexer"] = indexer


def _init_tagger(
    data_source: str,
    pipeline_config: Dict[str, Any],
    shared_dense_model: Any | None,
) -> None:
    tag_config = pipeline_config.get("tag", {}) if pipeline_config else {}
    if not tag_config.get("enabled", True):
        return
    tagger = TaggerProcessor(data_source=data_source, config=tag_config)
    tagger.setup(embedding_model=shared_dense_model)
    if hasattr(tagger, "set_db"):
        tagger.set_db(_worker_context["db"])
    _worker_context["tagger"] = tagger


def process_document_wrapper(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Top-level wrapper function to process a document using the worker's global context.
    """
    global _worker_context
    db: Optional[Database] = _get_context_component("db", Database)
    parser: Optional[ParseProcessor] = _get_context_component("parser", ParseProcessor)
    summarizer: Optional[SummarizeProcessor] = _get_context_component(
        "summarizer", SummarizeProcessor
    )
    indexer: Optional[IndexProcessor] = _get_context_component(
        "indexer", IndexProcessor
    )
    tagger: Optional[TaggerProcessor] = _get_context_component(
        "tagger", TaggerProcessor
    )

    memory_error = _wait_for_available_memory()
    if memory_error:
        return {"error": memory_error}
    if not db:
        return {"error": "Worker not initialized"}

    doc_id = doc.get("id")
    _log_context.doc_id = doc_id

    title = doc.get("map_title", "Unknown")[:200]
    result = {"doc_id": doc_id, "title": title, "stages": {}}
    pipeline_start = time.time()

    logger.info("[Worker %s] Processing: %s", os.getpid(), title)

    doc, parse_ok = _run_parse_stage(parser, db, doc, result)
    if not parse_ok:
        return result

    doc, summarize_ok = _run_summarize_stage(summarizer, db, doc, result)
    if not summarize_ok:
        return result

    doc = _run_tag_stage(tagger, db, doc, result)
    _run_index_stage(indexer, tagger, db, doc, result)

    total_elapsed = round(time.time() - pipeline_start, 1)
    db.update_document(doc_id, {"pipeline_elapsed_seconds": total_elapsed})

    _generate_processing_log(doc_id, doc.get("sys_parsed_folder"))

    return result
