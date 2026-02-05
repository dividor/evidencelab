"""CLI entrypoint for pipeline orchestrator."""

import argparse
import sys

import setproctitle

from pipeline.orchestrator import env
from pipeline.orchestrator.core import PipelineOrchestrator


def main() -> None:
    """Parse CLI arguments and run the pipeline orchestrator."""
    env.configure_thread_env()
    parser = argparse.ArgumentParser(description="Run the document processing pipeline")
    parser.add_argument(
        "--data-source", type=str, required=True, help="Data source name"
    )
    parser.add_argument(
        "--num-records", type=int, default=None, help="Max docs (default: all)"
    )
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-scan", action="store_true")
    parser.add_argument("--skip-parse", action="store_true")
    parser.add_argument("--skip-summarize", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--skip-tag", action="store_true")
    parser.add_argument(
        "--save-chunks", action="store_true", help="Save intermediate chunks to JSON"
    )
    parser.add_argument("--recent-first", action="store_true")
    parser.add_argument(
        "--clear-db",
        action="store_true",
        help="Clear all database content before running",
    )
    parser.add_argument("--partition", type=str, default=None)
    parser.add_argument("--report", "--file", type=str, default=None, dest="report")
    parser.add_argument("--agency", type=str, default=None)
    parser.add_argument(
        "--file-id",
        type=str,
        default=None,
        dest="file_id",
        help="Process a specific document by file ID",
    )
    parser.add_argument(
        "--model-mode",
        type=str,
        default="remote",
        choices=["local", "remote"],
        help="Model loading mode: 'remote' (server, default) or 'local' (in-process)",
    )
    parser.add_argument(
        "--year", type=int, default=None, help="Filter by specific year"
    )
    parser.add_argument(
        "--from-year", type=int, default=None, help="Filter by start year"
    )
    parser.add_argument("--to-year", type=int, default=None, help="Filter by end year")

    args = parser.parse_args()

    setproctitle.setproctitle("EvLab-Pipeline-Orchestrator")

    orchestrator = PipelineOrchestrator(
        data_source=args.data_source,
        skip_download=args.skip_download,
        skip_scan=args.skip_scan,
        skip_parse=args.skip_parse,
        skip_summarize=args.skip_summarize,
        skip_index=args.skip_index,
        skip_tag=args.skip_tag,
        save_chunks=args.save_chunks,
        num_records=args.num_records,
        workers=args.workers,
        recent_first=args.recent_first,
        partition=args.partition,
        report=args.report,
        agency=args.agency,
        clear_db=args.clear_db,
        model_mode=args.model_mode,
        year=args.year,
        from_year=args.from_year,
        to_year=args.to_year,
        doc_id=args.file_id,
    )

    success = orchestrator.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
