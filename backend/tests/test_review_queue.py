"""M5.5b review queue (D2): a live-fetched page that differs from the stored copy waits for an admin; nothing enters
the knowledge base without approval. Approving backs up first and stores exactly the reviewed text; rejecting deletes
it. Real (throwaway) Chroma store; network, embeddings and the backup are faked."""

from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.models.document import Document
from app.models.fetched_page import FetchedPageReview
from app.models.source import Source
from app.models.user import User
from app.services import ingestion as ingestion_pkg
from app.services import live_fetch, review_queue
from app.services.ingestion import ingestion_service
from app.services.source_registry import load_registry

PAGE = next(iter(load_registry().by_url()))  # a real registry URL
HOST = httpx.URL(PAGE).host
OLD = "Students can work up to 20 hours per week off campus during regular academic sessions. " * 6
NEW = "Students can work up to 24 hours per week off campus during regular academic sessions. " * 6
API = "/api/v1/admin/review-queue"


def html(text: str) -> str:
    return f"<html><head><title>Work off campus</title></head><body><main><p>{text}</p></main></body></html>"


def extracted(text: str) -> str:
    return live_fetch._main_text(html(text))[1]  # what the fetcher reads from that page


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


@pytest.fixture
async def source(db_session, store):
    """A registry page whose stored copy is the OLD text."""
    s = Source(url=PAGE, name="Work off campus", source_type="official", country="Canada")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    text = extracted(OLD)
    with patch.object(ingestion_pkg, "embed_texts_batch", side_effect=fake_embed):
        result = await ingestion_service.ingest_scraped(s, {
            "title": "Work off campus", "extracted_text": text, "content_hash": review_queue.content_hash(text),
            "scraped_at": "2026-10-19T10:00:00"}, db_session)
    assert result["status"] == "success"
    return s


@pytest.fixture
def backups(monkeypatch):
    made = []
    monkeypatch.setattr(review_queue, "_backup", lambda label: made.append(label) or f"{label}.dump")
    return made


@pytest.fixture
def embed():
    with patch.object(ingestion_pkg, "embed_texts_batch", side_effect=fake_embed):
        yield


@pytest.fixture
def web(monkeypatch, db_session):
    """Fetches go to a fake site; queueing uses the test session."""
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
    site = {"text": NEW}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html(site["text"]).encode())

    async def fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await live_fetch.fetch(PAGE, client=client)

    site["fetch"] = fetch
    return site


async def items(db):
    return (await db.execute(select(FetchedPageReview).order_by(FetchedPageReview.id))).scalars().all()


def stored_texts(store, source_id):
    return store.collection.get(where={"source_id": source_id}, include=["documents"])["documents"]


async def admin_headers(client, db_session, email="queue-admin@example.com", admin=True):
    token = (await client.post("/api/v1/auth/signup", json={"email": email, "password": "testpass123"})).json()["access_token"]
    if admin:
        await db_session.execute(update(User).where(User.email == email).values(is_admin=True))
        await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- queueing

@pytest.mark.asyncio
async def test_a_changed_page_is_queued_and_nothing_enters_the_knowledge_base(db_session, source, store, web):
    page = await web["fetch"]()
    assert "24 hours" in page.text  # the answer it was fetched for can use it
    [item] = await items(db_session)
    assert item.status == "pending" and item.source_id == source.id and "24 hours" in item.text
    assert item.content_hash == review_queue.content_hash(item.text) and item.chars == len(item.text)
    assert all("20 hours" in t for t in stored_texts(store, source.id))  # retrieval still has only the stored copy
    assert len((await db_session.execute(select(Document))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_a_page_equal_to_the_stored_copy_is_not_queued(db_session, source, web):
    web["text"] = OLD
    await web["fetch"]()
    assert await items(db_session) == []


@pytest.mark.asyncio
async def test_one_pending_item_per_page_and_a_newer_fetch_replaces_it(db_session, source, web):
    await web["fetch"]()
    await web["fetch"]()  # same content again
    assert len(await items(db_session)) == 1
    web["text"] = NEW.replace("24", "30")
    await web["fetch"]()
    [item] = await items(db_session)
    assert "30 hours" in item.text and item.status == "pending"


@pytest.mark.asyncio
async def test_the_whole_page_is_queued_even_when_the_answer_reads_a_cut_copy(db_session, source, web, monkeypatch):
    monkeypatch.setattr(settings, "LIVE_FETCH_MAX_CHARS", 100)
    page = await web["fetch"]()
    [item] = await items(db_session)
    assert len(page.text) == 100 and item.chars > 400 and item.text.startswith(page.text)


@pytest.mark.asyncio
async def test_a_failure_to_queue_never_fails_the_fetch(source, web, monkeypatch):
    def broken():
        raise RuntimeError("database down")

    monkeypatch.setattr(review_queue, "_sessions", broken)
    assert "24 hours" in (await web["fetch"]()).text


@pytest.mark.asyncio
async def test_a_registry_page_without_a_source_row_is_not_queued(db_session, web):
    await web["fetch"]()
    assert await items(db_session) == []


# ---------------------------------------------------------------- approve / reject

@pytest.mark.asyncio
async def test_approving_backs_up_then_stores_exactly_the_reviewed_text(client, db_session, source, store, web,
                                                                        backups, embed):
    await web["fetch"]()
    [item] = await items(db_session)
    reviewed = item.text
    web["text"] = "The page changed again after the review."  # approving must not fetch a second time
    headers = await admin_headers(client, db_session)

    listed = (await client.get(API, headers=headers)).json()["items"]
    assert [i["id"] for i in listed] == [item.id] and "text" not in listed[0]
    shown = (await client.get(f"{API}/{item.id}", headers=headers)).json()
    assert shown["text"] == reviewed and "20 hours" in shown["stored_text"]
    assert any(line.startswith("-") and "20 hours" in line for line in shown["diff"])
    assert any(line.startswith("+") and "24 hours" in line for line in shown["diff"])

    approved = await client.post(f"{API}/{item.id}/approve", headers=headers)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert backups == [f"pre_review_approve_{item.id}"]
    texts = stored_texts(store, source.id)
    assert texts and all("24 hours" in t for t in texts)  # the old version's chunks are gone
    newest = (await db_session.execute(select(Document).order_by(Document.id.desc()))).scalars().first()
    assert newest.extracted_text == reviewed and newest.content_hash == review_queue.content_hash(reviewed)
    await db_session.refresh(item)
    assert item.text == "" and item.reviewed_by is not None and "chunks stored" in item.outcome
    assert (await client.get(API, headers=headers)).json()["items"] == []
    assert (await client.post(f"{API}/{item.id}/approve", headers=headers)).status_code == 409  # not twice

    web["text"] = NEW  # the stored copy now equals the page: nothing more to review
    await web["fetch"]()
    assert len(await items(db_session)) == 1


@pytest.mark.asyncio
async def test_a_failed_backup_changes_nothing(client, db_session, source, store, web, monkeypatch, embed):
    await web["fetch"]()
    [item] = await items(db_session)

    def no_backup(label):
        raise RuntimeError("pg_dump not found at C:\\secret\\path")

    monkeypatch.setattr(review_queue, "_backup", no_backup)
    headers = await admin_headers(client, db_session)
    refused = await client.post(f"{API}/{item.id}/approve", headers=headers)
    assert refused.status_code == 500 and "nothing was changed" in refused.json()["detail"]
    assert "secret" not in refused.text
    await db_session.refresh(item)
    assert item.status == "pending" and item.text
    assert all("20 hours" in t for t in stored_texts(store, source.id))


@pytest.mark.asyncio
async def test_rejecting_deletes_the_text_and_the_same_content_is_not_queued_again(client, db_session, source, store,
                                                                                    web, backups):
    await web["fetch"]()
    [item] = await items(db_session)
    headers = await admin_headers(client, db_session)
    rejected = await client.post(f"{API}/{item.id}/reject", headers=headers)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    await db_session.refresh(item)
    assert item.text == "" and item.content_hash and backups == []
    assert all("20 hours" in t for t in stored_texts(store, source.id))
    assert (await client.get(f"{API}/{item.id}", headers=headers)).json()["text"] == ""

    await web["fetch"]()  # the page still serves the rejected content
    assert [i.status for i in await items(db_session)] == ["rejected"]
    web["text"] = NEW.replace("24", "30")  # a different version is a new item
    await web["fetch"]()
    assert [i.status for i in await items(db_session)] == ["rejected", "pending"]


@pytest.mark.asyncio
async def test_a_page_that_ingestion_refuses_stays_pending(client, db_session, source, store, backups, embed):
    outcome = await review_queue.enqueue(db_session, PAGE, PAGE, "Page not found", "Page not found")
    assert outcome == "queued"
    [item] = await items(db_session)
    headers = await admin_headers(client, db_session)
    refused = await client.post(f"{API}/{item.id}/approve", headers=headers)
    assert refused.status_code == 422 and "error_page" in refused.json()["detail"]
    await db_session.refresh(item)
    assert item.status == "pending" and all("20 hours" in t for t in stored_texts(store, source.id))


@pytest.mark.asyncio
async def test_a_version_approved_earlier_can_be_reviewed_again_after_it_was_replaced(db_session, source, store,
                                                                                      backups, embed):
    first, second = extracted(NEW), extracted(NEW.replace("24", "30"))
    assert await review_queue.enqueue(db_session, PAGE, PAGE, "Work", first) == "queued"
    [item] = await items(db_session)
    await review_queue.approve(db_session, item.id)
    assert await review_queue.enqueue(db_session, PAGE, PAGE, "Work", second) == "queued"
    await review_queue.approve(db_session, (await items(db_session))[-1].id)
    assert await review_queue.enqueue(db_session, PAGE, PAGE, "Work", first) == "queued"  # the page went back
    rows = await items(db_session)
    assert [r.status for r in rows] == ["pending", "approved"] and rows[0].text == first


# ---------------------------------------------------------------- access

@pytest.mark.asyncio
async def test_only_admins_reach_the_queue(client, db_session, source, web):
    await web["fetch"]()
    [item] = await items(db_session)
    user = await admin_headers(client, db_session, "queue-user@example.com", admin=False)
    for method, path in (("GET", API), ("GET", f"{API}/{item.id}"), ("POST", f"{API}/{item.id}/approve"),
                         ("POST", f"{API}/{item.id}/reject")):
        assert (await client.request(method, path, headers=user)).status_code == 403
        assert (await client.request(method, path)).status_code in (401, 403)
    await db_session.refresh(item)
    assert item.status == "pending" and item.text
    admin = await admin_headers(client, db_session, "queue-admin2@example.com")
    assert (await client.get(f"{API}/999999", headers=admin)).status_code == 404
