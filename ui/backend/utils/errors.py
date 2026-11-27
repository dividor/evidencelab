"""What the API tells a client when a request fails on the server.

Error text can carry SQL, file paths, host names or the state of the database
connection pool, so it stays in the server log. The client gets a fixed
message, unless ``API_DEBUG`` is on (local development only).
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException

from pipeline.db.postgres_client_base import PostgresPoolTimeout

API_DEBUG = os.environ.get("API_DEBUG", "false").lower() in ("1", "true", "yes")

INTERNAL_ERROR_DETAIL = "Internal server error"
BUSY_DETAIL = "The service is busy. Please try again in a moment."
INVALID_REQUEST_DETAIL = "Invalid request parameters"

# ValueError messages that may be shown to clients: they only repeat what the
# client sent.
SAFE_VALUE_ERROR_PREFIXES = ("Invalid data_source:",)


def server_error(exc: Exception, what: str, log: logging.Logger) -> HTTPException:
    """Log EXC under WHAT and return the HTTPException a route raises for it.

    A request that waited too long for a database connection gets 503, so the
    client can tell "busy, try again" from a fault. Anything else gets 500.
    The traceback goes to the log, never to the client.
    """
    if isinstance(exc, PostgresPoolTimeout):
        log.warning("%s: %s", what, exc)
        return HTTPException(status_code=503, detail=BUSY_DETAIL)
    log.error("%s: %s", what, exc, exc_info=exc)
    return HTTPException(
        status_code=500, detail=str(exc) if API_DEBUG else INTERNAL_ERROR_DETAIL
    )


def value_error_detail(exc: ValueError) -> str:
    """The message a client may see for a rejected value."""
    msg = str(exc)
    if API_DEBUG or msg.startswith(SAFE_VALUE_ERROR_PREFIXES):
        return msg
    return INVALID_REQUEST_DETAIL
