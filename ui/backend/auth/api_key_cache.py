"""In-memory cache of active API key hashes.

Avoids a database query on every request by caching the set of SHA-256
hashes for all active admin-managed API keys.  The cache is invalidated
whenever keys are created, deleted, or toggled.
"""

import logging
from typing import Optional, Set

from sqlalchemy import select

from ui.backend.auth.db import async_session_factory
from ui.backend.auth.models import ApiKey

logger = logging.getLogger(__name__)

_cache: Optional[Set[str]] = None


async def get_active_key_hashes() -> Set[str]:
    """Return the set of SHA-256 hex digests for all active API keys."""
    global _cache  # noqa: PLW0603
    if _cache is not None:
        return _cache
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ApiKey.key_hash).where(ApiKey.is_active.is_(True))
            )
            _cache = {row[0] for row in result.all()}
            logger.debug("API key cache loaded: %d active keys", len(_cache))
            return _cache
    except Exception:
        logger.exception("Failed to load API key cache")
        return set()


def invalidate_cache() -> None:
    """Clear the cache so the next request reloads from the database."""
    global _cache  # noqa: PLW0603
    _cache = None
