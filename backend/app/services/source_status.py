"""
Which sources are switched off (M0.10b).

Deactivating a source (scripts/sync_sources.py, an `excluded` registry entry) must take its chunks out of
answers immediately, before anyone removes them from the vector store. Retrieval asks for the inactive ids
and excludes them inside the vector search itself, so the top-k is filled from active sources only.

The list is tiny and changes rarely: cached per process for CACHE_SECONDS.
"""

import logging
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0

_cache: Optional[Tuple[float, List[int]]] = None


async def inactive_source_ids() -> List[int]:
    """Ids of sources with is_active = false. On a database error, the last known list (or none)."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.source import Source

        async with AsyncSessionLocal() as db:
            ids = sorted((await db.execute(select(Source.id).where(Source.is_active.is_(False)))).scalars().all())
    except Exception as err:
        logger.warning("Could not load inactive sources (%s); using the last known list", err)
        return _cache[1] if _cache else []
    _cache = (now, ids)
    return ids


def clear_cache() -> None:
    global _cache
    _cache = None
