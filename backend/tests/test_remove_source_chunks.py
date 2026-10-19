"""
scripts/remove_source_chunks.py (M0.10b): only inactive sources, only their own documents and chunks,
and never past a reference it would have to cascade through. Test database + temporary Chroma store.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.document import Document
from app.models.source import Source
from app.models.vector_chunk import VectorChunk
from app.services.vector_store import ChromaVectorStore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import remove_source_chunks as script  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return ChromaVectorStore(persist_directory=str(tmp_path / "chroma"))


async def add_source(db, store, url, active, texts):
    source = Source(url=url, name=url, source_type="official", is_active=active)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    doc = Document(source_id=source.id, content_hash=url[-16:], extracted_text=" ".join(texts))
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    for i, chunk_text in enumerate(texts):
        vector_id = f"s{source.id}-c{i}"
        store.collection.add(ids=[vector_id], documents=[chunk_text], embeddings=[[float(i + 1), 1.0, 0.0]],
                             metadatas=[{"source_id": source.id}])
        db.add(VectorChunk(document_id=doc.id, chunk_index=i, text=chunk_text, vector_id=vector_id,
                           chunk_metadata={"source_id": source.id}))
    await db.commit()
    return source, doc


@pytest.mark.asyncio
async def test_removes_only_the_inactive_sources_content(db_session, store):
    stub, stub_doc = await add_source(db_session, store, "https://future.utoronto.ca/x/", False, ["Page not found"])
    keep, keep_doc = await add_source(db_session, store, "https://www.canada.ca/a.html", True, ["Study", "permits"])

    plan = await script.plan(db_session, store, stub.id)
    assert plan["doc_ids"] == [stub_doc.id] and plan["chroma_ids"] == [f"s{stub.id}-c0"] and not plan["blockers"]
    await script.remove(db_session, store, [plan])

    assert store.collection.get(where={"source_id": stub.id})["ids"] == []
    assert len(store.collection.get(where={"source_id": keep.id})["ids"]) == 2
    docs = (await db_session.execute(select(Document.id))).scalars().all()
    assert docs == [keep_doc.id]
    chunks = (await db_session.execute(select(VectorChunk.document_id))).scalars().all()
    assert set(chunks) == {keep_doc.id}
    assert (await db_session.get(Source, stub.id)) is not None  # the source row stays as a record


@pytest.mark.asyncio
async def test_refuses_an_active_source(db_session, store):
    source, _ = await add_source(db_session, store, "https://www.canada.ca/a.html", True, ["Study"])
    with pytest.raises(SystemExit, match="is active"):
        await script.plan(db_session, store, source.id)
    assert len(store.collection.get()["ids"]) == 1


@pytest.mark.asyncio
async def test_refuses_unknown_sources(db_session, store):
    with pytest.raises(SystemExit, match="does not exist"):
        await script.plan(db_session, store, 99999)


@pytest.mark.asyncio
async def test_stops_at_references_it_would_have_to_cascade_through(db_session, store):
    source, doc = await add_source(db_session, store, "https://future.utoronto.ca/x/", False, ["Page not found"])
    from app.models.crawled_page import CrawledPage
    db_session.add(CrawledPage(job_id="job-1", url="https://future.utoronto.ca/x/", document_id=doc.id))
    await db_session.commit()

    plan = await script.plan(db_session, store, source.id)
    assert plan["blockers"] == {"crawled_pages": 1}
    with pytest.raises(RuntimeError, match="blocking references"):
        await script.remove(db_session, store, [plan])
    assert len(store.collection.get()["ids"]) == 1  # nothing removed
