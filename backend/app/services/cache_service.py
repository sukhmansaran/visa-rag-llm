"""
Aggressive caching service for RAG responses.
Caches at the intent + query fingerprint level to minimize redundant LLM calls.
"""

import logging
from typing import Any, Dict, List, Optional
import time
import hashlib

logger = logging.getLogger(__name__)


class IntentCache:
    """Cache for grounded RAG responses keyed by query fingerprint and intent."""

    def __init__(self, ttl_seconds: int = 86400):  # 24h backstop; keys are also versioned by rules + KB content (B16)
        self._cache: Dict[str, Dict] = {}
        self.ttl = ttl_seconds

    def clear(self) -> None:
        """Clear all entries from the in-memory cache."""
        self._cache.clear()
        logger.debug("[CACHE] Cleared all cache entries.")

    def get(
        self,
        country: str,
        visa_type: str,
        intent: str,
        version: str = "2025-01",
        query: Optional[str] = None,
    ) -> Optional[str]:
        """Retrieve a cached response (text only; see get_entry for its sources)."""
        entry = self.get_entry(country, visa_type, intent, version, query)
        return entry["response"] if entry else None

    def get_entry(
        self,
        country: str,
        visa_type: str,
        intent: str,
        version: str = "2025-01",
        query: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached answer with the sources it cites: {"response", "sources"}. A cached answer keeps its
        [Source N] citations, so it must come back with the same sources (hardening 3: they were dropped).
        """
        key = self._build_key(country, visa_type, intent, version, query)
        entry = self._cache.get(key)
        if entry:
            if time.time() - entry['timestamp'] < self.ttl:
                logger.debug(f"[CACHE] Hit for key: {key}")
                return {"response": entry['response'], "sources": list(entry.get('sources') or [])}
            logger.debug(f"[CACHE] Expired key: {key}")
            del self._cache[key]
        return None

    def set(
        self,
        country: str,
        visa_type: str,
        intent: str,
        response: str,
        version: str = "2025-01",
        query: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
    ):
        """Store a response, with the sources its citations refer to."""
        key = self._build_key(country, visa_type, intent, version, query)
        logger.debug(f"[CACHE] Storing response for key: {key}")
        self._cache[key] = {
            'response': response,
            'sources': list(sources or []),
            'timestamp': time.time()
        }

    def _build_key(
        self,
        country: str,
        visa_type: str,
        intent: str,
        version: str,
        query: Optional[str] = None,
    ) -> str:
        """Standardized cache key format with query fingerprint."""
        query_hash = ""
        if query:
            norm_q = " ".join(query.strip().lower().split())
            query_hash = "_" + hashlib.sha256(norm_q.encode()).hexdigest()[:12]
        return f"{country.upper()}_{visa_type.upper()}_{intent.upper()}_{version}{query_hash}"


# Global instance
intent_cache = IntentCache()
