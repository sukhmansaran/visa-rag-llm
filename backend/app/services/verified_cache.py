"""
Verified-answer cache (M4.6): a verified answer takes 20-90 s on this CPU; the same question again comes back in under
a second from Redis (shared by the API and every worker, kept across restarts).

Key = sha256 of:
  the question as answered (follow-ups resolved, M2.4), normalised (case, spacing);
  profile facts the pipeline uses (country, university);
  every version an answer depends on: rules file hash, knowledge-base content version, every prompt's tag, the
  model pins file (which builds answer, verify and monitor) and the settings that change verified answers;
  the user's id when the question holds personal details (an email, phone, name pattern...): personal answers are
  never served to someone else. Such a question with no known user isn't cached.
So a change to the rules, the knowledge base (a re-ingest or approved review item, and registry pages through it,
M7), a model build or a prompt changes the key: old entries are never read again and expire after
VERIFIED_CACHE_TTL_SECONDS.

Only answers composed from checked evidence are stored, and only when the monitor actually ran (or is switched
off). Redis unavailable: no cache, the answer is computed as usual.
"""

import hashlib
import json
import logging
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.loop_local import LoopLocal

logger = logging.getLogger(__name__)

PREFIX = "verified_answer:"
_clients: LoopLocal = LoopLocal()


def _redis():
    import redis.asyncio as aioredis
    return _clients.get_or_create(lambda: aioredis.from_url(settings.REDIS_URL, decode_responses=True,
                                                            socket_connect_timeout=0.5, socket_timeout=2.0))


async def close() -> None:
    client = _clients.pop()
    if client is not None:
        await client.aclose()


def _normal(question: str) -> str:
    return " ".join((question or "").lower().split())


def _settings_version() -> Dict[str, Any]:
    """Settings that change what a verified answer says."""
    return {name: getattr(settings, name) for name in (
        "RAG_TOP_K", "RAG_CONTEXT_CHARS", "RAG_MULTI_PART_CONTEXT_CHARS", "RAG_TEMPERATURE", "VERIFY_CLAIMS_WITH_MODEL",
        "VERIFIED_MAX_ROUNDS", "MONITOR_ENABLED", "MONITOR_DENY_CONFIDENCE", "OLLAMA_MODEL", "LLM_MODEL_PLANNER",
        "LLM_MODEL_ANSWER", "LLM_MODEL_VERIFIER", "LLM_MODEL_MONITOR")}


async def versions() -> Dict[str, Any]:
    from app.services.model_pins import PINS_PATH
    from app.services.prompt_registry import all_prompts
    from app.services.rule_engine import get_rules_content_hash
    from app.services.vector_store import vector_store

    try:
        kb = await vector_store.content_version()
    except Exception:
        kb = None  # unknown knowledge base: not cacheable (see key)
    pins = PINS_PATH.read_bytes() if PINS_PATH.exists() else b""
    return {"rules": get_rules_content_hash(), "kb": kb,
            "prompts": sorted(p.tag for p in all_prompts().values()),
            "models": hashlib.sha256(pins).hexdigest()[:16], "settings": _settings_version()}


def is_personal(question: str) -> bool:
    from app.core.logging_config import PIIRedactor
    return PIIRedactor.redact(question) != question


async def key_for(question: str, context_metadata: Optional[Dict[str, Any]], user_id: Optional[int]) -> Optional[str]:
    """The cache key, or None if this question must not be cached (personal with no user, or unknown KB)."""
    personal = is_personal(question)
    if personal and user_id is None:
        return None
    version = await versions()
    if version["kb"] is None:
        return None
    meta = context_metadata or {}
    material = {"question": _normal(question), "country": (meta.get("country") or "").lower(),
                "university": (meta.get("university") or "").lower(), "versions": version,
                "user": user_id if personal else None}
    return PREFIX + hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


async def get(key: str) -> Optional[Dict[str, Any]]:
    try:
        raw = await _redis().get(key)
    except Exception:
        logger.warning("[VERIFIED_CACHE] Redis unavailable; answering without the cache")
        return None
    return json.loads(raw) if raw else None


async def put(key: str, answer: str, sources: list, evidence: Dict[str, Any]) -> bool:
    try:
        await _redis().set(key, json.dumps({"answer": answer, "sources": sources, "evidence": evidence}, default=str),
                           ex=settings.VERIFIED_CACHE_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("[VERIFIED_CACHE] Redis unavailable; the answer was not cached")
        return False
