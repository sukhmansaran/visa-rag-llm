"""
Official source registry (M0.10).

`app/data/official_sources.yaml` is the hand-curated list of pages the knowledge base may be built from:
URL, title, topic tags, authority tier and freshness policy. It is reviewed like code; nothing writes to it.

- `load_registry()` validates the file (unique ids and URLs, allowlisted https URLs, known topics).
- `verify_entry()` fetches one page through the DNS-pinned client and checks HTTP 200, robots.txt, that the
  final URL is still allowlisted, and that the page is not an error page served with HTTP 200 (a soft 404:
  the University of Toronto source was ingested as "Page not found").
- `scripts/verify_registry.py` and `scripts/sync_sources.py` are the command-line entry points.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import yaml

from app.services.crawler.safe_http import BlockedDestinationError
from app.services.crawler.ssrf_validator import is_safe_url

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "official_sources.yaml"

USER_AGENT = "PenduBot/1.0 (+registry verification)"
MAX_REDIRECTS = 5
MIN_MAIN_TEXT_CHARS = 200  # a real policy page has far more; error and stub pages have less

# Phrases error pages use in their title or heading (canada.ca, universities, common CMSs)
_ERROR_PAGE_PATTERNS = [
    r"\bpage not found\b", r"\bnot found\b.*\b404\b", r"\b404\b.*\bnot found\b", r"\berror 404\b",
    r"we couldn.t find that (web )?page", r"\bpage (you requested )?(could not|cannot|can.t) be found\b",
    r"\bthis page (does not|doesn.t) exist\b", r"\bpage (is )?no longer available\b",
]
_ERROR_RE = re.compile("|".join(_ERROR_PAGE_PATTERNS), re.IGNORECASE)


class RegistryError(ValueError):
    """The registry file is malformed."""


@dataclass(frozen=True)
class RegistryEntry:
    id: str
    url: str
    title: str
    tier: int
    topics: List[str]
    refresh_days: int
    max_age_days: int
    source_type: str = "official"
    priority: int = 2
    notes: str = ""
    replaces: str = ""  # the entry's previous URL, so a moved page updates its source instead of duplicating it


@dataclass(frozen=True)
class ExcludedSource:
    """A page deliberately not used (e.g. it blocks automated access). Sync deactivates its source."""
    url: str
    reason: str


@dataclass
class Registry:
    version: int
    topics: Dict[str, str]
    entries: List[RegistryEntry]
    excluded: List[ExcludedSource] = field(default_factory=list)

    def by_url(self) -> Dict[str, RegistryEntry]:
        return {e.url: e for e in self.entries}


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    """Load and validate the registry. Raises RegistryError listing every problem found."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    topics = data.get("topics") or {}
    problems: List[str] = []
    entries: List[RegistryEntry] = []
    seen_ids, seen_urls = set(), set()

    for i, raw in enumerate(data.get("sources") or []):
        where = f"sources[{i}] ({raw.get('id', '?')})"
        missing = [k for k in ("id", "url", "title", "tier", "topics", "refresh_days", "max_age_days") if k not in raw]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
            continue
        unknown = sorted(set(raw) - set(RegistryEntry.__dataclass_fields__))
        if unknown:
            problems.append(f"{where}: unknown fields {unknown}")
        entry = RegistryEntry(**{k: v for k, v in raw.items() if k in RegistryEntry.__dataclass_fields__})
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", entry.id):
            problems.append(f"{where}: id must be lowercase words joined by hyphens")
        if entry.id in seen_ids:
            problems.append(f"{where}: duplicate id")
        if entry.url in seen_urls:
            problems.append(f"{where}: duplicate url")
        seen_ids.add(entry.id)
        seen_urls.add(entry.url)
        if urlparse(entry.url).scheme != "https":
            problems.append(f"{where}: url must be https")
        if not is_safe_url(entry.url, resolve_dns=False):
            problems.append(f"{where}: url is not on the domain allowlist")
        if entry.tier not in (1, 2, 3, 4):
            problems.append(f"{where}: tier must be 1-4")
        if not entry.topics or not isinstance(entry.topics, list):
            problems.append(f"{where}: at least one topic is required")
        else:
            bad = [t for t in entry.topics if t not in topics]
            if bad:
                problems.append(f"{where}: unknown topics {bad} (add them to the topics list first)")
        if not (isinstance(entry.refresh_days, int) and entry.refresh_days >= 1):
            problems.append(f"{where}: refresh_days must be a positive integer")
        if not (isinstance(entry.max_age_days, int) and entry.max_age_days >= entry.refresh_days):
            problems.append(f"{where}: max_age_days must be an integer >= refresh_days")
        entries.append(entry)

    excluded: List[ExcludedSource] = []
    for i, raw in enumerate(data.get("excluded") or []):
        if not raw.get("url") or not raw.get("reason"):
            problems.append(f"excluded[{i}]: url and reason are required")
            continue
        if raw["url"] in seen_urls:
            problems.append(f"excluded[{i}]: {raw['url']} is also a registry source")
        excluded.append(ExcludedSource(url=raw["url"], reason=raw["reason"]))

    if problems:
        raise RegistryError("Registry problems:\n  " + "\n  ".join(problems))
    return Registry(version=int(data.get("version", 1)), topics=topics, entries=entries, excluded=excluded)


def looks_like_error_page(title: str, main_text: str) -> Optional[str]:
    """A reason string if this looks like an error or stub page served with HTTP 200, else None."""
    head = f"{title or ''}\n{(main_text or '')[:300]}"
    match = _ERROR_RE.search(head)
    if match:
        return f"error page ('{match.group(0)}')"
    if len((main_text or "").strip()) < MIN_MAIN_TEXT_CHARS:
        return f"too little main text ({len((main_text or '').strip())} chars)"
    return None


@dataclass
class VerifyResult:
    entry_id: str
    url: str
    # ok | http_<code> | soft_404 | moved_to_parent | robots_disallowed | off_allowlist | redirect_loop
    # | blocked | error
    status: str = "unchecked"
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    title: str = ""
    main_text_chars: int = 0
    detail: str = ""
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _is_parent_page(original: str, final: str) -> bool:
    """True if `final` is a section page above `original` (/a/b/c.html -> /a/b.html or /a.html)."""
    a, b = urlparse(original), urlparse(final)
    if a.netloc != b.netloc:
        return False
    stem = lambda path: re.sub(r"(/index)?\.html?$", "", path).rstrip("/")  # noqa: E731
    return stem(a.path).startswith(stem(b.path) + "/")


async def _robots_allows(client: httpx.AsyncClient, url: str, cache: Dict[str, RobotFileParser]) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in cache:
        parser = RobotFileParser()
        try:
            response = await client.get(f"{origin}/robots.txt", headers={"User-Agent": USER_AGENT})
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
        except httpx.HTTPError:
            parser.parse([])  # unreachable robots.txt: same as the crawler, treated as allow-all
        cache[origin] = parser
    return cache[origin].can_fetch(USER_AGENT, url)


async def verify_entry(client: httpx.AsyncClient, entry: RegistryEntry,
                       robots_cache: Optional[Dict[str, RobotFileParser]] = None) -> VerifyResult:
    """Fetch one registry page (client: a pinned_client) and check it is a live, allowed, real page."""
    from app.services.scraper import extract_main_text  # heavy imports (bs4, html2text) only when used
    import html2text

    robots_cache = robots_cache if robots_cache is not None else {}
    result = VerifyResult(entry_id=entry.id, url=entry.url)
    url = entry.url
    try:
        if not await _robots_allows(client, url, robots_cache):
            result.status, result.detail = "robots_disallowed", "robots.txt disallows this URL"
            return result
        for _ in range(MAX_REDIRECTS + 1):
            response = await client.get(url, headers={"User-Agent": USER_AGENT})
            location = response.headers.get("location")
            if not (response.is_redirect and location):
                break
            url = urljoin(str(response.url), location)
            if not is_safe_url(url, resolve_dns=False):
                result.status, result.final_url = "off_allowlist", url
                result.detail = "redirects off the domain allowlist"
                return result
        else:
            result.status, result.detail = "redirect_loop", f"more than {MAX_REDIRECTS} redirects"
            return result
    except BlockedDestinationError as err:
        result.status, result.detail = "blocked", str(err)
        return result
    except httpx.HTTPError as err:
        result.status, result.detail = "error", f"{type(err).__name__}: {err}"
        return result

    result.http_status, result.final_url = response.status_code, url
    if response.status_code != 200:
        result.status = f"http_{response.status_code}"
        return result

    converter = html2text.HTML2Text()
    converter.ignore_links, converter.ignore_images, converter.body_width = True, True, 0
    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
    result.title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    main_text = extract_main_text(response.text, converter)
    result.main_text_chars = len(main_text)
    reason = looks_like_error_page(result.title, main_text)
    if reason:
        result.status, result.detail = "soft_404", reason
        return result
    if url != entry.url:
        if _is_parent_page(entry.url, url):
            # canada.ca sends removed pages to their section hub (the SDS page now lands on "Study in Canada"):
            # a live page, but not the one registered
            result.status = "moved_to_parent"
            result.detail = f"redirects up to its section page {url}; the page was probably removed"
            return result
        result.detail = f"redirected to {url}; consider updating the registry URL"
    result.status = "ok"
    return result


# ---------------------------------------------------------------- syncing the sources table

@dataclass
class SyncChange:
    """One planned change to the sources table. kind: create | update | deactivate | unregistered."""
    kind: str
    registry_id: Optional[str]
    url: str
    source_id: Optional[int] = None
    fields: Dict[str, object] = field(default_factory=dict)  # field -> new value
    before: Dict[str, object] = field(default_factory=dict)  # field -> current value (updates)
    note: str = ""


def entry_fields(entry: RegistryEntry) -> Dict[str, object]:
    """What a registry entry sets on its source row."""
    return {
        "registry_id": entry.id, "url": entry.url, "name": entry.title, "authority_tier": entry.tier,
        "source_type": entry.source_type, "priority": entry.priority, "scrape_frequency": entry.refresh_days * 24,
        "topics": list(entry.topics), "max_age_days": entry.max_age_days, "is_active": True,
    }


def plan_sync(registry: Registry, sources: List[object]) -> List[SyncChange]:
    """
    Compare the registry with the current Source rows. Pure: no database access, so it can be shown as a
    dry run and tested. Rows are matched by registry_id, then URL, then the entry's `replaces` URL.
    Sources not in the registry are reported (`unregistered`), never changed; `system://` rows are ignored.
    """
    by_registry_id = {s.registry_id: s for s in sources if getattr(s, "registry_id", None)}
    by_url = {s.url: s for s in sources}
    matched_ids = set()
    changes: List[SyncChange] = []

    for entry in registry.entries:
        source = (by_registry_id.get(entry.id) or by_url.get(entry.url)
                  or (by_url.get(entry.replaces) if entry.replaces else None))
        wanted = entry_fields(entry)
        if source is None:
            changes.append(SyncChange("create", entry.id, entry.url, fields={**wanted, "country": "Canada"}))
            continue
        matched_ids.add(source.id)
        diff = {k: v for k, v in wanted.items() if getattr(source, k, None) != v}
        if diff:
            changes.append(SyncChange("update", entry.id, entry.url, source.id, fields=diff,
                                      before={k: getattr(source, k, None) for k in diff},
                                      note="URL moved" if "url" in diff else ""))

    excluded_urls = {x.url: x for x in registry.excluded}
    for source in sources:
        if source.id in matched_ids or source.url.startswith("system://"):
            continue
        if source.url in excluded_urls:
            if source.is_active:
                changes.append(SyncChange("deactivate", None, source.url, source.id, fields={"is_active": False},
                                          before={"is_active": True}, note=excluded_urls[source.url].reason))
        elif source.is_active:
            changes.append(SyncChange("unregistered", None, source.url, source.id,
                                      note="active but not in the registry; add it or list it under excluded"))
    return changes
