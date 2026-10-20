"""
One retrievable version per page (M0.14): re-ingesting a changed page replaces its chunks instead of adding a
second set; older Document rows remain as history. Real (throwaway) Chroma store; scraping and embeddings faked.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.document import Document
from app.models.source import Source
from app.models.vector_chunk import VectorChunk
from app.services import ingestion as ingestion_pkg
from app.services.ingestion import ingestion_service

URL = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/work/work-off-campus.html"
V1 = "Students can work up to 20 hours per week off campus during regular academic sessions. " * 6
V2 = "Students can work up to 24 hours per week off campus during regular academic sessions. " * 6


def scraped(text: str) -> dict:
    import hashlib
    return {"url": URL, "title": "Work off campus", "raw_html": "<html></html>", "extracted_text": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(), "scraped_at": "2026-10-19T10:00:00Z"}


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
async def source(db_session):
    s = Source(url=URL, name="Work off campus", source_type="official", country="Canada")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


async def ingest(db_session, source, text):
    with patch.object(ingestion_pkg, "scrape_with_retry", return_value=scraped(text)), \
         patch.object(ingestion_pkg, "embed_texts_batch", side_effect=fake_embed):
        return await ingestion_service.ingest_source(source.id, db_session)


def chunk_texts(store, source_id):
    got = store.collection.get(where={"source_id": source_id}, include=["documents", "metadatas"])
    return got["documents"], {m["document_id"] for m in got["metadatas"]}


@pytest.mark.asyncio
async def test_a_changed_page_replaces_its_chunks(db_session, store, source):
    first = await ingest(db_session, source, V1)
    second = await ingest(db_session, source, V2)

    assert first["status"] == second["status"] == "success"
    assert second["superseded_chunks_removed"] == first["chunks_created"]
    texts, doc_ids = chunk_texts(store, source.id)
    assert doc_ids == {second["document_id"]} and all("24 hours" in t for t in texts)  # only the new version

    docs = (await db_session.execute(select(Document).where(Document.source_id == source.id))).scalars().all()
    assert len(docs) == 2  # history kept
    old_rows = (await db_session.execute(
        select(VectorChunk.status).where(VectorChunk.document_id == first["document_id"]))).scalars().all()
    assert old_rows and set(old_rows) == {"superseded"}


@pytest.mark.asyncio
async def test_a_page_that_reverts_gets_its_old_text_back(db_session, store, source):
    """Before M0.14 the revert matched the old copy's hash and was skipped, leaving the newer text live."""
    await ingest(db_session, source, V1)
    await ingest(db_session, source, V2)
    reverted = await ingest(db_session, source, V1)

    assert reverted["status"] == "success"
    texts, doc_ids = chunk_texts(store, source.id)
    assert doc_ids == {reverted["document_id"]} and all("20 hours" in t for t in texts)


@pytest.mark.asyncio
async def test_unchanged_page_is_skipped_and_leftovers_are_removed(db_session, store, source):
    first = await ingest(db_session, source, V1)
    # an interrupted earlier run left a stray chunk from another document of this source
    store.collection.add(ids=["stray"], documents=["old text"], embeddings=[[1.0, 1.0, 1.0, 1.0]],
                         metadatas=[{"source_id": source.id, "document_id": first["document_id"] + 999}])

    again = await ingest(db_session, source, V1)
    assert again["status"] == "skipped" and again["superseded_chunks_removed"] == 1
    _, doc_ids = chunk_texts(store, source.id)
    assert doc_ids == {first["document_id"]}


@pytest.mark.asyncio
async def test_failed_embedding_saves_nothing_and_keeps_the_current_chunks(db_session, store, source):
    source_id = source.id  # read before the rollback expires the instance
    first = await ingest(db_session, source, V1)

    async def broken(texts):
        raise RuntimeError("Ollama is down")

    with patch.object(ingestion_pkg, "scrape_with_retry", return_value=scraped(V2)), \
         patch.object(ingestion_pkg, "embed_texts_batch", side_effect=broken):
        with pytest.raises(RuntimeError):
            await ingestion_service.ingest_source(source_id, db_session)
    await db_session.rollback()

    docs = (await db_session.execute(select(Document.id).where(Document.source_id == source_id))).scalars().all()
    assert docs == [first["document_id"]]  # no orphan document
    _, doc_ids = chunk_texts(store, source_id)
    assert doc_ids == {first["document_id"]}  # the page still answers

    source = await db_session.get(Source, source_id)
    retry = await ingest(db_session, source, V2)  # and the change is picked up once Ollama is back
    assert retry["status"] == "success"


@pytest.mark.asyncio
async def test_two_versions_with_the_same_text_do_not_crash(db_session, store, source):
    """scalar_one_or_none() raised when two documents shared a hash."""
    await ingest(db_session, source, V1)
    await ingest(db_session, source, V2)
    await ingest(db_session, source, V1)
    result = await ingest(db_session, source, V1)
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_other_sources_are_untouched(db_session, store, source):
    other = Source(url="https://www.canada.ca/en/other.html", name="Other", source_type="official")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    await ingest(db_session, other, V1)

    await ingest(db_session, source, V1)
    await ingest(db_session, source, V2)
    texts, _ = chunk_texts(store, other.id)
    assert texts and all("20 hours" in t for t in texts)
