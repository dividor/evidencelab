"""In-memory cache of active API key hashes.

Avoids a database query on every request by caching the set of SHA-256
hashes for all active admin-managed API keys.  The cache is invalidated
whenever keys are created, deleted, or toggled (within the same process),
and also expires automatically after CACHE_TTL_SECONDS so that changes
made in a different process (e.g. the ui container) are picked up.
"""

import logging
import time
from typing import Optional, Set

from sqlalchemy import select

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.models import ApiKey

logger = logging.getLogger(__name__)

# Re-load from DB at least every 60 seconds so cross-process key changes
# (e.g. key created/deleted in the ui container) are picked up by the
# mcp container without requiring a restart.
CACHE_TTL_SECONDS = 60

_cache: Optional[Set[str]] = None
_cache_loaded_at: float = 0.0


async def get_active_key_hashes() -> Set[str]:
    """Return the set of SHA-256 hex digests for all active API keys."""
    global _cache, _cache_loaded_at  # noqa: PLW0603
    if _cache is not None and (time.monotonic() - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ApiKey.key_hash).where(ApiKey.is_active.is_(True))
            )
            _cache = {row[0] for row in result.all()}
            _cache_loaded_at = time.monotonic()
            logger.debug("API key cache loaded: %d active keys", len(_cache))
            return _cache
    except Exception:
        logger.exception("Failed to load API key cache")
        return set()


def invalidate_cache() -> None:
    """Clear the cache so the next request reloads from the database."""
    global _cache, _cache_loaded_at  # noqa: PLW0603
    _cache = None
    _cache_loaded_at = 0.0
