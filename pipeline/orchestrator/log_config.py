"""Logging configuration for pipeline orchestrator."""

import logging
import os
from logging.handlers import RotatingFileHandler

from pipeline.utilities.logging_utils import ContextFilter


def setup_logging() -> logging.Logger:
    """Setup logging to file and console."""
    log_file = None

    if os.path.exists("/app/logs"):
        log_file = "/app/logs/orchestrator.log"
    elif os.path.exists("logs"):
        log_file = "logs/orchestrator.log"

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=50 * 1024 * 1024, backupCount=20)
        )

    context_filter = ContextFilter()
    for handler in handlers:
        handler.addFilter(context_filter)

    log_fmt = (
        "%(asctime)s - [%(processName)s:%(process)d:%(doc_id)s] "
        "- %(levelname)s - %(message)s"
    )
    logging.basicConfig(
        level=logging.INFO,
        format=log_fmt,
        handlers=handlers,
        force=True,
    )
    return logging.getLogger(__name__)
