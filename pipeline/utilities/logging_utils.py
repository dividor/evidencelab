"""Logging helpers for pipeline context."""

import logging
import threading

_log_context = threading.local()


class ContextFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """
    Filter to inject document ID into log records.
    """

    def filter(self, record):
        record.doc_id = getattr(_log_context, "doc_id", "N/A")
        return True
