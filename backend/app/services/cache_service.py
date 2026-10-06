"""
Aggressive caching service for RAG responses.
Caches at the intent + metadata level to minimize LLM calls.
"""

from typing import Optional, Dict
import time

class IntentCache:
    """Aggressive cache for normalized RAG responses."""
    
    def __init__(self, ttl_seconds: int = 86400 * 7):  # Default 7 days
        self._cache: Dict[str, Dict] = {}
        self.ttl = ttl_seconds
    
    def get(self, country: str, visa_type: str, intent: str, version: str = "2025-01") -> Optional[str]:
        """Retrieve a cached response."""
        key = self._build_key(country, visa_type, intent, version)
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
    
    def set(self, country: str, visa_type: str, intent: str, response: str, version: str = "2025-01"):
        """Store a response in the cache."""
        key = self._build_key(country, visa_type, intent, version)
        print(f"[CACHE] Storing response for key: {key}")
        self._cache[key] = {
            'response': response,
            'timestamp': time.time()
        }
    
    def _build_key(self, country: str, visa_type: str, intent: str, version: str) -> str:
        """Standardized cache key format."""
        return f"{country.upper()}_{visa_type.upper()}_{intent.upper()}_{version}"

# Global instance
intent_cache = IntentCache()
