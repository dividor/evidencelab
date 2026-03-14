import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from typing import Optional, Set

from pipeline.db import Database, get_db
from pipeline.db.postgres_client import PostgresClient

_db_cache: dict[str, Database] = {}
_pg_cache: dict[str, PostgresClient] = {}


@lru_cache(maxsize=1)
def _get_valid_data_sources() -> Set[str]:
    """Load valid data sources from config.json (cached)."""
    config_paths = [
        os.path.join(os.path.dirname(__file__), "../../../config.json"),
        "/app/config.json",
        "config.json",
    ]

    for config_path in config_paths:
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                datasources = config.get("datasources", {})
                # Extract both the key and the data_subdir as valid sources
                valid_sources: Set[str] = set()
                for key, value in datasources.items():
                    valid_sources.add(key)
                    if isinstance(value, dict) and "data_subdir" in value:
                        valid_sources.add(value["data_subdir"])
                return valid_sources
        except (FileNotFoundError, json.JSONDecodeError):
            continue

    # Fallback to known defaults if config can't be loaded
    return {"uneg", "worldbank"}


def _validate_data_source(data_source: Optional[str]) -> str:
    """Validate and normalize data source parameter."""
    source = data_source or "uneg"
    valid_sources = _get_valid_data_sources()

    if source not in valid_sources:
        raise ValueError(
            f"Invalid data_source: {source}. " f"Valid sources: {sorted(valid_sources)}"
        )
    return source


def get_db_for_source(data_source: str = None) -> Database:
    """Get or create a Database instance for a specific data source."""
    source = _validate_data_source(data_source)
    if source not in _db_cache:
        _db_cache[source] = get_db(source)
    return _db_cache[source]


def get_pg_for_source(data_source: str = None) -> PostgresClient:
    """Get or create a PostgresClient instance for a specific data source."""
    source = _validate_data_source(data_source)
    if source not in _pg_cache:
        _pg_cache[source] = PostgresClient(source)
    return _pg_cache[source]


class JSONLogFormatter(logging.Formatter):
    """Structured JSON log formatter for SIEM ingestion (ASVS V7.1.3)."""

    # Extra fields that are included in output when present on the LogRecord.
    _EXTRA_FIELDS = ("user_id", "user_email", "ip_address", "event_type", "request_id")

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        entry: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        for key in self._EXTRA_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, default=str)


def setup_logging() -> logging.Logger:
    """Setup logging to file and console.

    Set ``LOG_FORMAT=json`` for structured JSON output (SIEM-friendly).
    """
    log_file = None
    log_format = os.environ.get("LOG_FORMAT", "text").lower()

    # Determine log directory
    if os.path.exists("/app/logs"):
        log_file = "/app/logs/api.log"
    elif os.path.exists("logs"):
        log_file = "logs/api.log"

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        # Rotate logs: keep 3 backups, max 10MB each
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
        )

    if log_format == "json":
        formatter: logging.Formatter = JSONLogFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        force=True,
    )
    return logging.getLogger(__name__)


logger = setup_logging()
