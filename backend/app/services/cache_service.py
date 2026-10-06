"""
Aggressive caching service for RAG responses.
Caches at the intent + query fingerprint level to minimize redundant LLM calls.
"""

from typing import Optional, Dict
import time
import hashlib


class IntentCache:
    """Cache for grounded RAG responses keyed by query fingerprint and intent."""
    
    def __init__(self, ttl_seconds: int = 86400 * 7):  # Default 7 days
        self._cache: Dict[str, Dict] = {}
        self.ttl = ttl_seconds
    
    def clear(self) -> None:
        """Clear all entries from the in-memory cache."""
        self._cache.clear()
        print("[CACHE] Cleared all cache entries.")

    def get(
        self, 
        country: str, 
        visa_type: str, 
        intent: str, 
        version: str = "2025-01",
        query: Optional[str] = None,
    ) -> Optional[str]:
        """Retrieve a cached response."""
        key = self._build_key(country, visa_type, intent, version, query)
        entry = self._cache.get(key)
        
        if entry:
            # Check TTL
            if time.time() - entry['timestamp'] < self.ttl:
                print(f"[CACHE] Hit for key: {key}")
                return entry['response']
            else:
                print(f"[CACHE] Expired key: {key}")
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
    ):
        """Store a response in the cache."""
        key = self._build_key(country, visa_type, intent, version, query)
        print(f"[CACHE] Storing response for key: {key}")
        self._cache[key] = {
            'response': response,
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

