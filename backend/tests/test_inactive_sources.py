"""
Deactivated sources never reach an answer (M0.10b): their chunks are excluded inside the vector search,
before anyone removes them. Uses a real temporary Chroma store; no Ollama.
"""

from unittest.mock import patch

import pytest

from app.models.source import Source
from app.services import retrieval as retrieval_module
from app.services import source_status
from app.services.vector_store import ChromaVectorStore

DIM = 8


def vec(*hot):
    return [1.0 if i in hot else 0.0 for i in range(DIM)]


@pytest.fixture
def store(tmp_path):
    s = ChromaVectorStore(persist_directory=str(tmp_path / "chroma"))
    chunks = [
        {"text": "Page not found", "embedding": vec(0), "metadata": {"source_id": 15, "country": "Canada"}},
        {"text": "Study permit documents", "embedding": vec(0, 1), "metadata": {"source_id": 4, "country": "Canada"}},
        {"text": "PAL/TAL letters", "embedding": vec(0, 2), "metadata": {"source_id": 6, "country": "Canada"}},
        {"text": "Biometrics", "embedding": vec(5), "metadata": {"source_id": 14, "country": "Canada"}},
    ]
    s.collection.add(ids=[f"c{i}" for i in range(len(chunks))], documents=[c["text"] for c in chunks],
                     embeddings=[c["embedding"] for c in chunks], metadatas=[c["metadata"] for c in chunks])
    return s


@pytest.fixture(autouse=True)
def fresh_cache():
    source_status.clear_cache()
    yield
    source_status.clear_cache()


@pytest.mark.asyncio
async def test_excluded_sources_are_filtered_inside_the_search(store):
    unfiltered = await store.search(vec(0), top_k=2)
    assert unfiltered[0]["metadata"]["source_id"] == 15  # the stub is the best match

    filtered = await store.search(vec(0), top_k=2, exclude_source_ids=[15])
    assert [r["metadata"]["source_id"] for r in filtered] == [4, 6]  # top_k still filled from active sources


@pytest.mark.asyncio
async def test_exclusion_combines_with_metadata_filters(store):
    results = await store.search(vec(0), filters={"country": "Canada"}, top_k=3, exclude_source_ids=[15, 4])
    assert [r["metadata"]["source_id"] for r in results] == [6, 14]


@pytest.mark.asyncio
async def test_retrieval_excludes_inactive_sources(store, monkeypatch):
    async def fake_embed(query):
        return vec(0)

    async def inactive():
        return [15]

    monkeypatch.setattr(retrieval_module, "vector_store", store)
    monkeypatch.setattr(retrieval_module, "embed_text", fake_embed)
    monkeypatch.setattr(retrieval_module, "inactive_source_ids", inactive)
    results = await retrieval_module.retrieval_service.retrieve("UofT", country="Canada", top_k=2)
    assert 15 not in [r["metadata"]["source_id"] for r in results] and len(results) == 2


@pytest.mark.asyncio
async def test_inactive_ids_come_from_the_database(db_session, monkeypatch):
    db_session.add_all([
        Source(url="https://www.canada.ca/a.html", name="A", source_type="official", is_active=True),
        Source(url="https://future.utoronto.ca/x/", name="UofT", source_type="university", is_active=False),
    ])
    await db_session.commit()
    _use_test_db(monkeypatch, db_session)

    ids = await source_status.inactive_source_ids()
    inactive = (await db_session.execute(Source.__table__.select().where(Source.is_active.is_(False)))).all()
    assert ids == sorted(row.id for row in inactive) and ids


@pytest.mark.asyncio
async def test_cached_and_survives_a_database_error(db_session, monkeypatch):
    db_session.add(Source(url="https://future.utoronto.ca/x/", name="UofT", source_type="university", is_active=False))
    await db_session.commit()
    _use_test_db(monkeypatch, db_session)
    first = await source_status.inactive_source_ids()

    class Broken:
        def __call__(self):
            raise RuntimeError("database down")

    with patch("app.core.database.AsyncSessionLocal", Broken()):
        assert await source_status.inactive_source_ids() == first  # served from the cache
        source_status._cache = (0.0, first)  # expired
        assert await source_status.inactive_source_ids() == first  # last known list, not an empty one


def _use_test_db(monkeypatch, db_session):
    """Point source_status at the test database's engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.core.database as database
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(db_session.bind, expire_on_commit=False))
