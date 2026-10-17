"""
Official source registry (M0.10): the file's rules, soft-404 detection, page verification and sync planning.
No network: verification runs against an httpx MockTransport.
"""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from app.services.source_registry import (REGISTRY_PATH, RegistryError, entry_fields, load_registry,
                                          looks_like_error_page, plan_sync, verify_entry)

LONG_TEXT = " ".join(["To study in Canada you need a study permit issued by IRCC before you arrive."] * 6)


def write_registry(tmp_path: Path, sources, excluded=None, topics=None) -> Path:
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1, "topics": topics or {"study_permit": "x", "pgwp": "y"},
        "sources": sources, "excluded": excluded or [],
    }), encoding="utf-8")
    return path


def entry(**overrides):
    base = {"id": "study-permit", "url": "https://www.canada.ca/en/study-permit.html", "title": "Study permit",
            "tier": 1, "topics": ["study_permit"], "refresh_days": 7, "max_age_days": 30}
    return {**base, **overrides}


# ---------------------------------------------------------------- the real registry

def test_the_registry_file_is_valid():
    registry = load_registry()
    assert len(registry.entries) >= 15
    assert all(e.url.startswith("https://") for e in registry.entries)
    assert {x.url for x in registry.excluded} == {"https://future.utoronto.ca/apply/international-students/"}


def test_the_registry_lives_with_the_other_reviewed_data():
    assert REGISTRY_PATH.parent.name == "data" and (REGISTRY_PATH.parent / "ircc_rules.yaml").exists()


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("bad,message", [
    (entry(url="http://www.canada.ca/x.html"), "must be https"),
    (entry(url="https://www.example.com/visa.html"), "not on the domain allowlist"),
    (entry(topics=["study_permit", "visas_in_general"]), "unknown topics"),
    (entry(topics=[]), "at least one topic"),
    (entry(tier=7), "tier must be 1-4"),
    (entry(max_age_days=3), "max_age_days must be"),
    (entry(refresh_days=0), "refresh_days must be"),
    (entry(id="Study Permit"), "lowercase words"),
    (entry(colour="blue"), "unknown fields"),
    ({"id": "x", "url": "https://www.canada.ca/x.html"}, "missing"),
])
def test_bad_entries_are_reported(tmp_path, bad, message):
    with pytest.raises(RegistryError, match=message):
        load_registry(write_registry(tmp_path, [bad]))


def test_duplicates_and_excluded_overlaps_are_reported(tmp_path):
    sources = [entry(), entry(id="study-permit"), entry(id="other", url=entry()["url"])]
    excluded = [{"url": entry()["url"], "reason": "blocked"}, {"url": "https://www.canada.ca/y.html"}]
    with pytest.raises(RegistryError) as exc:
        load_registry(write_registry(tmp_path, sources, excluded))
    for message in ("duplicate id", "duplicate url", "also a registry source", "url and reason are required"):
        assert message in str(exc.value)


# ---------------------------------------------------------------- soft-404 detection

@pytest.mark.parametrize("title,text", [
    ("Page not found", "# Page not found\nThe requested page could not be found."),  # the stored UofT stub
    ("We couldn't find that Web page (Error 404) - Canada.ca", "We couldn't find that Web page " + LONG_TEXT),
    ("Not Found", "Error 404: " + LONG_TEXT),
    ("Study permit", "Coming soon."),  # stub: real policy pages are far longer
])
def test_error_and_stub_pages_are_detected(title, text):
    assert looks_like_error_page(title, text)


@pytest.mark.parametrize("title,text", [
    ("Study permit - Canada.ca", LONG_TEXT),
    ("Biometrics", LONG_TEXT + " If your fingerprints are not found in the system, give them again."),
])
def test_real_pages_pass(title, text):
    assert looks_like_error_page(title, text) is None


# ---------------------------------------------------------------- verification

def mock_site(pages):
    """pages: path -> (status, html or location). robots.txt disallows /private/."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        status, body = pages.get(request.url.path, (404, "<title>Not found</title>"))
        if 300 <= status < 400:
            return httpx.Response(status, headers={"location": body})
        return httpx.Response(status, html=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def page(title, text=LONG_TEXT):
    return f"<html><head><title>{title}</title></head><body><nav>Menu</nav><main>{text}</main></body></html>"


def reg_entry(path, **overrides):
    return load_registry.__globals__["RegistryEntry"](**{**entry(url=f"https://www.canada.ca{path}"), **overrides})


@pytest.mark.asyncio
@pytest.mark.parametrize("path,pages,status", [
    ("/ok.html", {"/ok.html": (200, page("Study permit"))}, "ok"),
    ("/gone.html", {}, "http_404"),
    ("/soft.html", {"/soft.html": (200, page("Page not found", "The requested page could not be found."))}, "soft_404"),
    ("/private/a.html", {"/private/a.html": (200, page("Private"))}, "robots_disallowed"),
    ("/away.html", {"/away.html": (302, "https://evil.example.com/")}, "off_allowlist"),
    ("/loop.html", {"/loop.html": (301, "/loop.html")}, "redirect_loop"),
])
async def test_verify_entry_statuses(path, pages, status):
    async with mock_site(pages) as client:
        result = await verify_entry(client, reg_entry(path))
    assert result.status == status
    assert result.ok == (status == "ok")


@pytest.mark.asyncio
async def test_an_allowed_redirect_passes_and_suggests_the_new_url():
    pages = {"/old.html": (301, "/new.html"), "/new.html": (200, page("Study permit"))}
    async with mock_site(pages) as client:
        result = await verify_entry(client, reg_entry("/old.html"))
    assert result.ok and result.final_url == "https://www.canada.ca/new.html"
    assert "consider updating the registry URL" in result.detail
    assert result.title == "Study permit" and result.main_text_chars > 200


# ---------------------------------------------------------------- sync planning

def source(id, url, **fields):
    defaults = {"registry_id": None, "name": "", "authority_tier": 1, "source_type": "official", "priority": 2,
                "scrape_frequency": 168, "topics": None, "max_age_days": None, "is_active": True}
    return SimpleNamespace(id=id, url=url, **{**defaults, **fields})


def registry_with(tmp_path, sources, excluded=None):
    return load_registry(write_registry(tmp_path, sources, excluded))


def test_plan_creates_updates_deactivates_and_reports(tmp_path):
    registry = registry_with(tmp_path, [
        entry(),  # existing row, fields differ
        entry(id="pgwp", url="https://www.canada.ca/en/pgwp.html", topics=["pgwp"]),  # new
        entry(id="moved", url="https://www.canada.ca/en/new-home.html", replaces="https://www.canada.ca/en/old.html"),
    ], excluded=[{"url": "https://future.utoronto.ca/x/", "reason": "403 to bots"}])
    rows = [
        source(1, "system://legacy-unmapped-import", is_active=False),
        source(2, entry()["url"], name="Old title"),
        source(3, "https://www.canada.ca/en/old.html", name="Moved"),
        source(4, "https://future.utoronto.ca/x/", source_type="university"),
        source(5, "https://www.canada.ca/en/forgotten.html"),
    ]
    changes = {(c.kind, c.source_id or c.registry_id): c for c in plan_sync(registry, rows)}

    assert set(changes) == {("update", 2), ("create", "pgwp"), ("update", 3), ("deactivate", 4), ("unregistered", 5)}
    renamed = changes[("update", 2)]
    assert renamed.fields["name"] == "Study permit" and renamed.before["name"] == "Old title"
    assert changes[("update", 3)].fields["url"] == "https://www.canada.ca/en/new-home.html"
    assert changes[("update", 3)].note == "URL moved"
    assert changes[("create", "pgwp")].fields["scrape_frequency"] == 7 * 24
    assert changes[("deactivate", 4)].fields == {"is_active": False}


def test_plan_is_empty_once_applied(tmp_path):
    registry = registry_with(tmp_path, [entry()])
    rows = [source(2, **entry_fields(registry.entries[0]))]
    assert plan_sync(registry, rows) == []


def test_registry_id_wins_over_url(tmp_path):
    """A row already linked to an entry follows it even if the URL changed without `replaces`."""
    registry = registry_with(tmp_path, [entry(url="https://www.canada.ca/en/renamed.html")])
    rows = [source(2, "https://www.canada.ca/en/study-permit.html", registry_id="study-permit")]
    [change] = plan_sync(registry, rows)
    assert change.kind == "update" and change.source_id == 2 and "url" in change.fields


def test_an_inactive_registered_source_is_reactivated(tmp_path):
    registry = registry_with(tmp_path, [entry()])
    fields = {**entry_fields(registry.entries[0]), "is_active": False}
    [change] = plan_sync(registry, [source(2, **fields)])
    assert change.fields == {"is_active": True}
