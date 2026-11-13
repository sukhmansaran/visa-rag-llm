"""M7 policy watch: a sweep over the registry pages queues a changed page for review with an analysis that names
the changed figures, the ircc_rules.yaml keys they belong to and the stored chunks; the model's summary is kept only
if code finds every number of it in the diff. Nothing edits the rules or the knowledge base. Network, embeddings and
the model are faked; the Chroma store is the throwaway one."""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.fetched_page import FetchedPageReview
from app.models.notification import Notification
from app.models.source import Source
from app.models.user import User
from app.services import ingestion as ingestion_pkg
from app.services import live_fetch, policy_watch, review_queue
from app.services.ingestion import ingestion_service
from app.services.rule_engine import load_ircc_rules
from app.services.source_registry import load_registry

FUNDS_PAGE = load_ircc_rules()["proof_of_funds"]["source_url"]
OTHER_PAGE = next(url for url in load_registry().by_url() if url != FUNDS_PAGE)
CURRENT = load_ircc_rules()["proof_of_funds"]["schedules"][0]["rates_by_family_size"][1]  # the figure in the rules
INTRO = "Proof of financial support. You must prove that you can support yourself while you study in Canada. " * 3
OLD = INTRO + f"A single student must show CAD ${CURRENT:,} for living expenses for the first year of study."
NEW = INTRO + "A single student must show CAD $24,100 for living expenses for the first year of study."
RULES_FILE = Path(policy_watch.__file__).resolve().parents[1] / "data" / "ircc_rules.yaml"


def html(text: str) -> str:
    paragraphs = "".join(f"<p>{sentence.strip()}.</p>" for sentence in text.split(". ") if sentence.strip())
    return f"<html><head><title>Proof of funds</title></head><body><main>{paragraphs}</main></body></html>"


def extracted(text: str) -> str:
    return live_fetch._main_text(html(text))[1]


async def fake_embed(texts):
    return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]


@pytest.fixture
def store():
    vs = ingestion_pkg.vector_store
    assert "pendu_test_chroma_" in settings.CHROMA_PERSIST_DIRECTORY  # never the real knowledge base
    yield vs
    ids = vs.collection.get()["ids"]
    if ids:
        vs.collection.delete(ids=ids)


async def stored_source(db, url, text):
    source = Source(url=url, name=url.rsplit("/", 1)[-1], source_type="official", country="Canada")
    db.add(source)
    await db.commit()
    await db.refresh(source)
    body = extracted(text)
    with patch.object(ingestion_pkg, "embed_texts_batch", side_effect=fake_embed):
        result = await ingestion_service.ingest_scraped(source, {
            "title": "Proof of funds", "extracted_text": body, "content_hash": review_queue.content_hash(body),
            "scraped_at": "2026-10-19T10:00:00"}, db)
    assert result["status"] == "success"
    return source


@pytest.fixture
async def pages(db_session, store):
    """Two registry pages with stored copies: the funds page (the rules' source) and one other."""
    assert FUNDS_PAGE in load_registry().by_url()
    return {"funds": await stored_source(db_session, FUNDS_PAGE, OLD),
            "other": await stored_source(db_session, OTHER_PAGE, OLD)}


@pytest.fixture
def web(monkeypatch, db_session):
    """The live site: url -> text (None = HTTP 500). Queueing uses the test session; no cache; no waiting."""
    monkeypatch.setattr(settings, "LIVE_FETCH_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(live_fetch, "_robots_cache", {})

    async def no_cache(*_):
        return None

    monkeypatch.setattr(live_fetch, "_cache_get", no_cache)
    monkeypatch.setattr(live_fetch, "_cache_set", no_cache)

    @asynccontextmanager
    async def session():
        yield db_session

    monkeypatch.setattr(review_queue, "_sessions", lambda: session)
    site = {FUNDS_PAGE: NEW, OTHER_PAGE: OLD}
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"User-agent: *\nAllow: /")
        text = site.get(str(request.url))
        if text is None:
            return httpx.Response(500, headers={"content-type": "text/html"}, content=b"down")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html(text).encode())

    monkeypatch.setattr("app.services.crawler.safe_http.pinned_client",
                        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    site["requests"] = requests
    return site


async def items(db):
    return (await db.execute(select(FetchedPageReview).order_by(FetchedPageReview.id))).scalars().all()


# ---------------------------------------------------------------- what changed (code)

def test_numbers_are_read_without_currency_signs_and_separators():
    assert policy_watch.numbers_in("CAD $23,448, up to 24 hours, 8.5%, in 2026.") == {"23448", "24", "8.5", "2026"}
    removed, added = policy_watch.changed_lines("a\nfunds 22,895\nc", "a\nfunds 23,448\nc\nd")
    assert removed == ["funds 22,895"] and added == ["funds 23,448", "d"]


def test_a_rule_is_named_when_its_figure_left_the_page_it_is_sourced_from():
    rules = {"off_campus_work": {"source_url": "https://x/work.html", "max_hours_per_week": 24},
             "proof_of_funds": {"source_url": "https://x/funds.html", "schedules": [{"rates": {1: 23448, 2: 29192}}]},
             "version": "1"}
    funds = policy_watch.affected_rules("https://x/funds.html", {"23448", "24"}, rules)
    assert [(r["key"], r["value"]) for r in funds] == [("proof_of_funds.schedules[0].rates.1", "23448")]
    # "24" on the funds page is not the work-hours rule; on the work page it is
    work = policy_watch.affected_rules("https://x/work.html", {"24"}, rules)
    assert [r["key"] for r in work] == ["off_campus_work.max_hours_per_week"]
    # a distinctive figure is named even from another page, marked as such
    elsewhere = policy_watch.affected_rules("https://x/other.html", {"29192"}, rules)
    assert elsewhere[0]["key"].endswith("rates.2") and elsewhere[0]["sourced_from_this_page"] is False
    assert policy_watch.affected_rules("https://x/funds.html", {"99999"}, rules) == []


# ---------------------------------------------------------------- the sweep, end to end

@pytest.mark.asyncio
async def test_a_changed_funds_figure_becomes_a_review_item_naming_the_rules_key(db_session, pages, store, web,
                                                                                 fake_llm):
    fake_llm.when(r"review a change to an official", {
        "summary": f"The amount a single student must show changed from {CURRENT:,} to 24,100.", "kind": "figures"})
    rules_before = RULES_FILE.read_bytes()
    admin = User(email="watch-admin@example.com", hashed_password="x", is_admin=True)
    db_session.add_all([admin, User(email="watch-user@example.com", hashed_password="x")])
    await db_session.commit()

    report = await policy_watch.sweep(db_session)

    assert report["pages"] == 2 and report["fetched"] == 2 and report["failed"] == []
    [item] = await items(db_session)  # only the page that changed
    assert item.url == FUNDS_PAGE and item.status == "pending" and item.origin == "policy_watch"
    analysis = item.analysis
    assert analysis["numbers_removed"] == [str(CURRENT)] and analysis["numbers_added"] == ["24100"]
    assert analysis["rules"][0] == {"key": "proof_of_funds.schedules[0].rates_by_family_size.1",
                                    "value": str(CURRENT), "section": "proof_of_funds", "sourced_from_this_page": True}
    assert analysis["chunks"] and analysis["kind"] == "figures"
    assert analysis["summary_by"] == "model" and "24,100" in analysis["summary"]
    assert analysis["prompt"].startswith("policy_change@1")
    assert report["analysed"] == [{"id": item.id, "url": FUNDS_PAGE, "kind": "figures",
                                   "rules": ["proof_of_funds.schedules[0].rates_by_family_size.1"]}]

    # nothing was edited: the rules file and the stored chunks are as before
    assert RULES_FILE.read_bytes() == rules_before
    texts = store.collection.get(where={"source_id": pages["funds"].id}, include=["documents"])["documents"]
    assert texts and all("24,100" not in t for t in texts)

    # the admin is told; the ordinary user is not
    notes = (await db_session.execute(select(Notification))).scalars().all()
    assert [n.user_id for n in notes] == [admin.id]
    assert "24,100" in notes[0].message and "proof_of_funds" in notes[0].message and notes[0].related_url == "/admin"

    # the requests carried the fixed headers only
    page_requests = [r for r in web["requests"] if r.url.path != "/robots.txt"]
    assert page_requests and all(r.headers["user-agent"] == live_fetch.HEADERS["User-Agent"] for r in page_requests)
    assert all(not r.url.query and not r.content for r in web["requests"])

    again = await policy_watch.sweep(db_session)  # the same change is not queued or announced twice
    assert again["analysed"] == [] and len(await items(db_session)) == 1
    assert len((await db_session.execute(select(Notification))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_a_summary_with_a_number_that_is_not_in_the_diff_is_replaced_by_codes(db_session, pages, web, fake_llm):
    fake_llm.when(r"review a change to an official", {
        "summary": "The amount changed to 30,000 dollars for a single student.", "kind": "figures"})
    await policy_watch.sweep(db_session)
    [item] = await items(db_session)
    assert item.analysis["summary_by"] == "code" and "30,000" not in item.analysis["summary"]
    assert "24100" in item.analysis["summary"] and item.analysis["prompt"] is None
    assert item.analysis["rules"]  # the facts found by code don't depend on the model


@pytest.mark.asyncio
async def test_without_the_model_the_analysis_is_still_made(db_session, pages, web, monkeypatch):
    from app.core.exceptions import AIServiceUnavailableError
    from app.services.llm import llm_service

    async def down(*_, **__):
        raise AIServiceUnavailableError("ollama down", details={})

    monkeypatch.setattr(llm_service, "structured_call", down)
    report = await policy_watch.sweep(db_session)
    [item] = await items(db_session)
    assert report["analysed"] and item.analysis["summary_by"] == "code" and item.analysis["rules"]


@pytest.mark.asyncio
async def test_a_page_that_cannot_be_fetched_does_not_stop_the_sweep(db_session, pages, web, fake_llm):
    web[OTHER_PAGE] = None
    fake_llm.when(r"review a change to an official", {"summary": "A figure changed on the page shown.", "kind": "figures"})
    report = await policy_watch.sweep(db_session)
    assert report["fetched"] == 1 and [f["url"] for f in report["failed"]] == [OTHER_PAGE]
    assert [i.url for i in await items(db_session)] == [FUNDS_PAGE]


@pytest.mark.asyncio
async def test_a_page_an_answer_fetched_is_analysed_too_and_a_newer_fetch_gets_a_new_analysis(db_session, pages, web):
    body = extracted(NEW)
    assert await review_queue.enqueue(db_session, FUNDS_PAGE, FUNDS_PAGE, "Proof of funds", body) == "queued"
    web[FUNDS_PAGE] = OLD  # the site went back; the queued item is from the earlier fetch
    await policy_watch.sweep(db_session, use_model=False)
    [item] = await items(db_session)
    assert item.origin == "agent_fetch" and item.analysis["numbers_added"] == ["24100"]

    newer = extracted(NEW.replace("24,100", "25,000"))
    assert await review_queue.enqueue(db_session, FUNDS_PAGE, FUNDS_PAGE, "Proof of funds", newer,
                                      origin="policy_watch") == "replaced"
    await db_session.refresh(item)
    assert item.analysis is None  # the old analysis described the old text
    await policy_watch.analyse(db_session, item, use_model=False)
    assert item.analysis["numbers_added"] == ["25000"]


@pytest.mark.asyncio
async def test_the_admin_sees_the_analysis_with_the_item(client, db_session, pages, web):
    from sqlalchemy import update

    await policy_watch.sweep(db_session, use_model=False)
    [item] = await items(db_session)
    token = (await client.post("/api/v1/auth/signup", json={"email": "watch-api@example.com",
                                                            "password": "testpass123"})).json()["access_token"]
    await db_session.execute(update(User).where(User.email == "watch-api@example.com").values(is_admin=True))
    await db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    listed = (await client.get("/api/v1/admin/review-queue", headers=headers)).json()["items"][0]
    assert listed["origin"] == "policy_watch" and listed["analysed"] is True and "analysis" not in listed
    shown = (await client.get(f"/api/v1/admin/review-queue/{item.id}", headers=headers)).json()
    assert shown["analysis"]["rules"][0]["key"] == "proof_of_funds.schedules[0].rates_by_family_size.1"
