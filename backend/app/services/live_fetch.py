"""
Live fetch (M5.5a): one official registry page, fetched now, used for the current answer only.

Only pages in app/data/official_sources.yaml can be fetched, by their exact URL (principle 10: nothing from the
question, the profile or the conversation goes out, not even as a query string). Every request has the same fixed
headers. The fetch is hardened like the crawler: DNS-pinned connections (safe_http), robots.txt, each redirect hop
re-checked against the domain allowlist, HTML only, a size cap, a pause between requests to the same host.

The page's main text (extracted as ingestion does, so quotes match the stored pages) is cached in Redis for
LIVE_FETCH_CACHE_SECONDS. It never enters the knowledge base here (M5.5b: review queue). `passages` picks the parts
that answer the question, in memory, and drops any passage that reads like instructions to the model (fetched text
is data, never instructions). Whatever the page says, the answer still has to quote it word for word and pass the
evidence checks.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "PenduBot/1.0 (+official page check)", "Accept": "text/html"}  # fixed: never user data
MAX_REDIRECTS = 5
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_last_request: Dict[str, float] = {}
_host_locks: Dict[str, asyncio.Lock] = {}


class LiveFetchError(Exception):
    """The page could not be fetched safely; the answer goes on with the knowledge base."""


@dataclass
class FetchedPage:
    url: str            # the registry URL asked for
    final_url: str      # after redirects (each hop on the allowlist)
    title: str
    text: str
    fetched_at: str
    tier: int


# ---------------------------------------------------------------- cache (Redis; a failure only skips the cache)

def _cache_key(url: str) -> str:
    return "livefetch:v1:" + hashlib.sha256(url.encode()).hexdigest()


async def _cache_get(url: str) -> Optional[FetchedPage]:
    try:
        from app.services.answer_jobs import _redis

        raw = await _redis().get(_cache_key(url))
        return FetchedPage(**json.loads(raw)) if raw else None
    except Exception:
        return None


async def _cache_set(page: FetchedPage) -> None:
    try:
        from app.services.answer_jobs import _redis

        await _redis().set(_cache_key(page.url), json.dumps(asdict(page)), ex=settings.LIVE_FETCH_CACHE_SECONDS)
    except Exception:
        logger.debug("[LIVE FETCH] cache unavailable", exc_info=True)


# ---------------------------------------------------------------- fetching

async def _space_requests(host: str) -> None:
    """At most one request to a host per LIVE_FETCH_MIN_INTERVAL_SECONDS from this process."""
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = _last_request.get(host, 0.0) + settings.LIVE_FETCH_MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request[host] = time.monotonic()


async def _get_html(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET with the fixed headers, reading at most LIVE_FETCH_MAX_BYTES; redirects are returned, not followed."""
    await _space_requests(urlparse(url).netloc)
    async with client.stream("GET", url, headers=HEADERS) as response:
        if response.is_redirect:
            return response
        if response.status_code != 200:
            raise LiveFetchError(f"HTTP {response.status_code}")
        if "html" not in response.headers.get("content-type", "").lower():
            raise LiveFetchError("not an HTML page")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > settings.LIVE_FETCH_MAX_BYTES:
                raise LiveFetchError(f"page larger than {settings.LIVE_FETCH_MAX_BYTES} bytes")
        response._content = bytes(body)
        return response


async def fetch(url: str, client: Optional[httpx.AsyncClient] = None) -> FetchedPage:
    """The current main text of a registry page. Raises LiveFetchError when it can't be fetched safely."""
    from app.services.crawler.safe_http import BlockedDestinationError, pinned_client
    from app.services.crawler.ssrf_validator import is_safe_url
    from app.services.source_registry import _robots_allows, load_registry, looks_like_error_page

    entry = load_registry().by_url().get(url)
    if entry is None:  # tools.LiveFetchArgs refuses it first; checked again here for any other caller
        raise LiveFetchError("not a page in the official source registry")
    cached = await _cache_get(url)
    if cached is not None:
        return cached

    own_client = client is None
    client = client or pinned_client(timeout=settings.LIVE_FETCH_TIMEOUT_SECONDS)
    try:
        if not await _robots_allows(client, url, _robots_cache):
            raise LiveFetchError("robots.txt disallows this page")
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            response = await _get_html(client, current)
            location = response.headers.get("location")
            if not (response.is_redirect and location):
                break
            current = urljoin(current, location)
            if not is_safe_url(current, resolve_dns=False):  # the pinned connection checks the addresses
                raise LiveFetchError("redirects off the domain allowlist")
        else:
            raise LiveFetchError("too many redirects")
    except BlockedDestinationError as e:
        raise LiveFetchError(f"blocked destination: {e}") from e
    except httpx.HTTPError as e:
        raise LiveFetchError(f"{type(e).__name__}") from e
    finally:
        if own_client:
            await client.aclose()

    html = response.content.decode(response.encoding or "utf-8", errors="replace")
    title, text = _main_text(html)
    problem = looks_like_error_page(title, text)
    if problem:
        raise LiveFetchError(f"not a usable page: {problem}")
    page = FetchedPage(url=url, final_url=current, title=title, text=text,
                       fetched_at=datetime.utcnow().isoformat(timespec="seconds"), tier=entry.tier)
    await _cache_set(page)
    return page


_robots_cache: Dict[str, Any] = {}


def _main_text(html: str) -> tuple:
    import html2text

    from app.services.scraper import extract_main_text

    converter = html2text.HTML2Text()
    converter.ignore_links, converter.ignore_images, converter.body_width = True, True, 0
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", match.group(1)).strip()[:300] if match else ""
    text = _CONTROL.sub("", extract_main_text(html, converter))[:settings.LIVE_FETCH_MAX_CHARS]
    return _CONTROL.sub("", title), text


# ---------------------------------------------------------------- the passages for this answer

def _reads_like_instructions(text: str) -> bool:
    from app.services.guardrails.input_guardrail import input_guardrail

    return any(p.search(text) for p in input_guardrail.INJECTION_PATTERNS)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def passages(page: FetchedPage, question: str, k: int = 3) -> Dict[str, Any]:
    """
    The page's k passages closest to the question, as retrieval-style chunks ({text, score, authority_tier,
    metadata{url, title, live, fetched_at}}), embedded in memory. Passages that read like instructions to the model
    are dropped. {"chunks": [...], "dropped": n}. If embeddings are unavailable, the first k passages.
    """
    from app.services.chunker import TextChunker

    pieces = [c["text"] for c in TextChunker(chunk_size=900, overlap=150).chunk_text(page.text, {})]
    kept = [p for p in pieces if p.strip() and not _reads_like_instructions(p)]
    scores = [0.0] * len(kept)
    if kept:
        try:
            from app.services.embeddings import embed_texts_batch

            vectors = await embed_texts_batch([question] + kept)
            scores = [_cosine(vectors[0], v) for v in vectors[1:]]
        except Exception:
            logger.warning("[LIVE FETCH] embeddings unavailable: passages kept in page order", exc_info=True)
    ranked = sorted(zip(kept, scores), key=lambda pair: -pair[1])[:k] if any(scores) else list(zip(kept, scores))[:k]
    chunks = [{"text": text, "score": round(score, 4), "authority_tier": page.tier,
               "metadata": {"url": page.url, "title": page.title, "live": True, "fetched_at": page.fetched_at}}
              for text, score in ranked]
    return {"chunks": chunks, "dropped": len(pieces) - len(kept)}
