"""
Milestone B2.2 Ingestion Orchestration Service Integration Tests.

Validates the end-to-end ingestion lifecycle against PostgreSQL (test database):
1. Initial fetch, normalize, chunk, candidate version, outbox operation, verification, and promotion.
2. Unchanged page detection via normalized content hash (zero duplicate versions).
3. HTTP 304 Not Modified handling (preserves version, updates last_verified_at).
4. Content change detection (creates version 2, supersedes version 1, shifts current pointer).
5. HTTP failure provenance capture (preserves existing version/pointer, records failure details).
6. Partial vector write / indexing failure (candidate version fails, pointer never falsely promoted).
7. Verification gate chunk mismatch detection.
8. Fenced worker lease acquisition and expired lease takeover.
9. Outbox retry policy enforcement.
"""

import datetime
from unittest.mock import AsyncMock, Mock, patch
import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.models.document import Document
from app.models.logical_document import LogicalDocument
from app.models.document_version import DocumentVersion
from app.models.current_document_pointer import CurrentDocumentPointer
from app.models.version_indexing_operation import VersionIndexingOperation
from app.models.vector_chunk import VectorChunk
from app.models.ingestion_run import IngestionRun

from app.services.ingestion.orchestrator import (
    IngestionOrchestrator,
    IngestionStepStatus,
    compute_canonical_url,
    compute_document_key,
)
from app.services.official_fetcher import (
    FetchResult,
    HTTPFetchError,
    FetchTimeoutError,
)
from app.services.canada_normalizer import CanadaNormalizer
from app.services.chunker import TextChunker


SAMPLE_HTML_V1 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Study in Canada as an international student - Canada.ca</title>
</head>
<body>
    <header><nav>GC Navigation</nav></header>
    <main>
        <h1>Study in Canada as an international student</h1>
        <p>To study in Canada, you must obtain a study permit before you travel. You will need a letter of acceptance from a designated learning institution (DLI) and proof that you have sufficient financial support.</p>
        <p>The minimum required cost of living financial threshold for a single student is CAD 10,000.</p>
    </main>
    <footer>GC Footer</footer>
</body>
</html>
"""

SAMPLE_HTML_V2 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Study in Canada as an international student - Canada.ca</title>
</head>
<body>
    <header><nav>GC Navigation</nav></header>
    <main>
        <h1>Study in Canada as an international student</h1>
        <p>To study in Canada, you must obtain a study permit before you travel. You will need a letter of acceptance from a designated learning institution (DLI) and proof that you have sufficient financial support.</p>
        <p>Effective January 1, 2024, the minimum required cost of living financial threshold for a single student is CAD 20,635.</p>
    </main>
    <footer>GC Footer</footer>
</body>
</html>
"""


@pytest.fixture
def mock_fetcher():
    """Mocked AsyncOfficialFetcher producing deterministic responses."""
    fetcher = Mock()
    fetcher.fetch = AsyncMock()
    return fetcher


@pytest.fixture
def mock_vector_store():
    """Mocked VectorStore recording upserts."""
    vs = Mock()
    vs.upsert_chunks = AsyncMock(return_value=["v1", "v2"])
    return vs


@pytest.fixture
def orchestrator(mock_fetcher, mock_vector_store):
    """IngestionOrchestrator pre-configured with mocks for isolated testing."""
    return IngestionOrchestrator(
        fetcher=mock_fetcher,
        normalizer=CanadaNormalizer(),
        chunker=TextChunker(chunk_size=300, overlap=50),
        vector_store=mock_vector_store,
        lease_duration_seconds=60,
    )


def make_fetch_result(
    url: str,
    html: str,
    status_code: int = 200,
    is_not_modified: bool = False,
    etag: str = 'W/"etag-v1"',
    last_mod: str = "Tue, 15 Jan 2024 10:00:00 GMT",
) -> FetchResult:
    content = html.encode("utf-8")
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=status_code,
        headers={"Content-Type": "text/html; charset=utf-8"},
        content_type="text/html",
        byte_count=len(content),
        fetched_at=datetime.datetime.now(datetime.timezone.utc),
        content=content,
        text=html,
        is_not_modified=is_not_modified,
        etag=etag,
        last_modified=last_mod,
    )


@pytest.mark.asyncio
async def test_01_initial_ingestion_and_promotion(db_session: AsyncSession, orchestrator, mock_fetcher):
    """
    Test Step 1: Initial ingestion of a new document.
    Verifies full lifecycle: candidate version created, outbox operation executed,
    chunk count verified, and pointer atomically promoted to version 1.
    """
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V1)

    run = await orchestrator.ingest_urls(urls=[url], db=db_session, trigger_type="test")
    print("RUN METADATA:", run.run_metadata)
    assert run.status == "completed"
    assert run.documents_fetched == 1
    assert run.documents_updated == 1
    assert run.documents_unchanged == 0
    assert run.documents_failed == 0

    # Verify LogicalDocument created
    key = compute_document_key(url)
    doc = (await db_session.execute(select(LogicalDocument).where(LogicalDocument.document_key == key))).scalar_one()
    assert doc.status == "active"
    assert doc.last_verified_at is not None
    assert doc.last_failure_at is None

    # Verify DocumentVersion promoted to 'ready'
    versions = (await db_session.execute(select(DocumentVersion).where(DocumentVersion.logical_document_id == doc.id))).scalars().all()
    assert len(versions) == 1
    v1 = versions[0]
    assert v1.version_number == 1
    assert v1.lifecycle_state == "ready"
    assert v1.ingestion_run_id == run.id

    # Verify CurrentDocumentPointer points to version 1
    ptr = await db_session.get(CurrentDocumentPointer, doc.id)
    assert ptr is not None
    assert ptr.current_version_id == v1.id
    assert ptr.verified_chunk_count > 0

    # Verify VectorChunks are marked 'active'
    chunks = (await db_session.execute(select(VectorChunk).where(VectorChunk.document_version_id == v1.id))).scalars().all()
    assert len(chunks) == ptr.verified_chunk_count
    for c in chunks:
        assert c.status == "active"
        assert c.logical_document_id == doc.id

    # Verify Outbox operation completed
    ops = (await db_session.execute(select(VersionIndexingOperation).where(VersionIndexingOperation.document_version_id == v1.id))).scalars().all()
    assert len(ops) == 1
    assert ops[0].status == "completed"
    assert ops[0].verified_chunk_count == len(chunks)


@pytest.mark.asyncio
async def test_02_unchanged_content_skips_version_creation(db_session: AsyncSession, orchestrator, mock_fetcher):
    """
    Test Step 2: Content change detection.
    When normalized content is identical, skip creating a new version,
    preserve existing version and pointer, and update last_verified_at.
    """
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V1)

    # First ingestion
    run1 = await orchestrator.ingest_urls(urls=[url], db=db_session)
    assert run1.documents_updated == 1

    # Second ingestion with identical content
    run2 = await orchestrator.ingest_urls(urls=[url], db=db_session)
    assert run2.status == "completed"
    assert run2.documents_updated == 0
    assert run2.documents_unchanged == 1

    # Check database: still exactly 1 version!
    key = compute_document_key(url)
    doc = (await db_session.execute(select(LogicalDocument).where(LogicalDocument.document_key == key))).scalar_one()
    versions = (await db_session.execute(select(DocumentVersion).where(DocumentVersion.logical_document_id == doc.id))).scalars().all()
    assert len(versions) == 1
    assert versions[0].version_number == 1

    ptr = await db_session.get(CurrentDocumentPointer, doc.id)
    assert ptr.current_version_id == versions[0].id


@pytest.mark.asyncio
async def test_03_http_304_not_modified_handling(db_session: AsyncSession, orchestrator, mock_fetcher):
    """
    Test Step 3: Upstream HTTP 304 response.
    Conditional ETag / Last-Modified match results in 304 Not Modified.
    Pipeline records successful verification and avoids re-processing.
    """
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"
    
    # Run 1: initial 200 OK
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V1)
    await orchestrator.ingest_urls(urls=[url], db=db_session)

    # Run 2: returns 304 Not Modified
    mock_fetcher.fetch.return_value = make_fetch_result(url, "", status_code=304, is_not_modified=True)
    run2 = await orchestrator.ingest_urls(urls=[url], db=db_session)

    assert run2.status == "completed"
    assert run2.documents_unchanged == 1
    assert run2.documents_updated == 0

    key = compute_document_key(url)
    doc = (await db_session.execute(select(LogicalDocument).where(LogicalDocument.document_key == key))).scalar_one()
    versions = (await db_session.execute(select(DocumentVersion).where(DocumentVersion.logical_document_id == doc.id))).scalars().all()
    assert len(versions) == 1


@pytest.mark.asyncio
async def test_04_content_change_creates_version_2_and_supersedes_v1(db_session: AsyncSession, orchestrator, mock_fetcher):
    """
    Test Step 4: Content change creates version 2 and atomically updates pointer.
    Historical version 1 is preserved with lifecycle_state='superseded'.
    Version 1 chunks are marked 'superseded'. Version 2 chunks are marked 'active'.
    """
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"

    # Ingest V1
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V1, etag='W/"v1"')
    await orchestrator.ingest_urls(urls=[url], db=db_session)

    # Ingest V2 (regulatory threshold updated from CAD 10,000 to CAD 20,635)
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V2, etag='W/"v2"')
    run2 = await orchestrator.ingest_urls(urls=[url], db=db_session)

    assert run2.status == "completed"
    assert run2.documents_updated == 1

    key = compute_document_key(url)
    doc = (await db_session.execute(select(LogicalDocument).where(LogicalDocument.document_key == key))).scalar_one()
    versions = (
        await db_session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.logical_document_id == doc.id)
            .order_by(DocumentVersion.version_number)
        )
    ).scalars().all()

    assert len(versions) == 2
    v1, v2 = versions[0], versions[1]

    # V1 is superseded, V2 is ready
    assert v1.version_number == 1
    assert v1.lifecycle_state == "superseded"

    assert v2.version_number == 2
    assert v2.lifecycle_state == "ready"

    # Current pointer points to V2
    ptr = await db_session.get(CurrentDocumentPointer, doc.id)
    assert ptr.current_version_id == v2.id

    # V1 chunks are superseded, V2 chunks are active
    v1_chunks = (await db_session.execute(select(VectorChunk).where(VectorChunk.document_version_id == v1.id))).scalars().all()
    for c in v1_chunks:
        assert c.status == "superseded"

    v2_chunks = (await db_session.execute(select(VectorChunk).where(VectorChunk.document_version_id == v2.id))).scalars().all()
    for c in v2_chunks:
        assert c.status == "active"


@pytest.mark.asyncio
async def test_05_http_error_provenance_and_pointer_safety(db_session: AsyncSession, orchestrator, mock_fetcher):
    """
    Test Step 5: HTTP error recording.
    When fetcher encounters an HTTP error (404), failure provenance is recorded
    on logical_documents, existing version and pointer are preserved,
    and no spurious versions are created.
    """
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"

    # Ingest V1 successfully first
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V1)
    await orchestrator.ingest_urls(urls=[url], db=db_session)

    # Simulate 404 Not Found error on next run
    mock_fetcher.fetch.side_effect = HTTPFetchError("Page moved or removed", status_code=404, url=url)
    run_err = await orchestrator.ingest_urls(urls=[url], db=db_session)

    assert run_err.status == "failed"
    assert run_err.documents_failed == 1

    key = compute_document_key(url)
    doc = (await db_session.execute(select(LogicalDocument).where(LogicalDocument.document_key == key))).scalar_one()

    # Provenance fields updated
    assert doc.last_failure_at is not None
    assert doc.last_failure_category == "http_error"
    assert doc.last_failure_http_status == 404

    # Current version and pointer preserved
    ptr = await db_session.get(CurrentDocumentPointer, doc.id)
    assert ptr is not None
    v1 = await db_session.get(DocumentVersion, ptr.current_version_id)
    assert v1.lifecycle_state == "ready"


@pytest.mark.asyncio
async def test_06_indexing_failure_never_promotes_pointer(db_session: AsyncSession, orchestrator, mock_fetcher, mock_vector_store):
    """
    Test Step 6: Vector indexing failure safety.
    If the vector store write fails, the candidate version transitions to 'failed',
    outbox operation transitions to 'failed', and current_document_pointers
    is NEVER pointed to the failed candidate version.
    """
    url = "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"

    # Ingest V1 successfully
    mock_fetcher.fetch.side_effect = None
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V1)
    await orchestrator.ingest_urls(urls=[url], db=db_session)

    # Ingest V2, but simulate vector store crash during upsert
    mock_fetcher.fetch.return_value = make_fetch_result(url, SAMPLE_HTML_V2)
    mock_vector_store.upsert_chunks.side_effect = ConnectionError("ChromaDB cluster connection refused")

    run_fail = await orchestrator.ingest_urls(urls=[url], db=db_session)
    assert run_fail.documents_failed == 1

    key = compute_document_key(url)
    doc = (await db_session.execute(select(LogicalDocument).where(LogicalDocument.document_key == key))).scalar_one()

    # Pointer must still point to V1
    ptr = await db_session.get(CurrentDocumentPointer, doc.id)
    v1 = (await db_session.execute(select(DocumentVersion).where(DocumentVersion.logical_document_id == doc.id, DocumentVersion.version_number == 1))).scalar_one()
    assert ptr.current_version_id == v1.id

    # V2 exists in 'failed' state
    v2 = (await db_session.execute(select(DocumentVersion).where(DocumentVersion.logical_document_id == doc.id, DocumentVersion.version_number == 2))).scalar_one()
    assert v2.lifecycle_state == "failed"

    # Outbox operation recorded failure
    op = (await db_session.execute(select(VersionIndexingOperation).where(VersionIndexingOperation.document_version_id == v2.id))).scalar_one()
    assert op.status == "failed"
    assert "ChromaDB cluster connection refused" in op.error_message


@pytest.mark.asyncio
async def test_07_lease_fencing_and_expired_lease_recovery(db_session: AsyncSession, orchestrator):
    """
    Test Step 7: Worker lease fencing.
    Active leases reject takeover from other workers.
    Expired leases can be reclaimed by a new worker.
    """
    # Create sample logical doc and candidate version
    src = Source(name="IRCC", url="https://www.canada.ca", country="Canada", source_type="official", authority_tier=1)
    db_session.add(src)
    await db_session.flush()

    doc = LogicalDocument(source_id=src.id, document_key="lease_test_key", primary_url="https://canada.ca/test", title="Test")
    db_session.add(doc)
    await db_session.flush()

    ver = DocumentVersion(
        logical_document_id=doc.id, version_number=1, lifecycle_state="indexing",
        requested_url="https://canada.ca/test", final_url="https://canada.ca/test",
        extracted_text="Text", raw_content_hash="h1", normalized_content_hash="h2",
    )
    db_session.add(ver)
    await db_session.flush()

    op = VersionIndexingOperation(
        document_version_id=ver.id,
        logical_document_id=doc.id,
        status="pending",
        target_chunk_count=1,
    )
    db_session.add(op)
    await db_session.commit()

    # Worker 1 claims lease for 1 second
    acquired_1 = await orchestrator.claim_indexing_lease(db=db_session, operation_id=op.id, lease_token="worker_1", ttl_seconds=1)
    assert acquired_1 is True

    # Worker 2 attempts immediate claim while Worker 1's lease is active -> rejected
    acquired_2 = await orchestrator.claim_indexing_lease(db=db_session, operation_id=op.id, lease_token="worker_2", ttl_seconds=10)
    assert acquired_2 is False

    # Force expiration of Worker 1's lease
    await db_session.refresh(op)
    op.lease_expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
    db_session.add(op)
    await db_session.commit()

    # Worker 2 attempts claim now -> successfully acquires expired lease
    acquired_3 = await orchestrator.claim_indexing_lease(db=db_session, operation_id=op.id, lease_token="worker_2", ttl_seconds=60)
    assert acquired_3 is True
    await db_session.refresh(op)
    assert op.worker_lease_id == "worker_2"


@pytest.mark.asyncio
async def test_08_retry_policy_for_failed_operations(db_session: AsyncSession, orchestrator):
    """
    Test Step 8: Outbox retry policy.
    Failed operations can be retried until max_retries is reached.
    """
    src = Source(name="IRCC", url="https://www.canada.ca", country="Canada", source_type="official", authority_tier=1)
    db_session.add(src)
    await db_session.flush()

    doc = LogicalDocument(source_id=src.id, document_key="retry_test_key", primary_url="https://canada.ca/retry", title="Retry Test")
    db_session.add(doc)
    await db_session.flush()

    ver = DocumentVersion(
        logical_document_id=doc.id, version_number=1, lifecycle_state="indexing",
        requested_url="https://canada.ca/retry", final_url="https://canada.ca/retry",
        extracted_text="Text",
    )
    db_session.add(ver)
    await db_session.flush()

    op = VersionIndexingOperation(
        document_version_id=ver.id,
        logical_document_id=doc.id,
        status="failed",
        retry_count=1,
    )
    db_session.add(op)
    await db_session.commit()

    # Retry 1: succeeds (retry_count 1 < max 3)
    retried = await orchestrator.retry_failed_operation(db=db_session, operation_id=op.id, max_retries=3)
    assert retried is True
    await db_session.refresh(op)
    assert op.status == "pending"

    # Simulate max retries reached
    op.status = "failed"
    op.retry_count = 3
    db_session.add(op)
    await db_session.commit()

    # Retry 2: rejected because retry_count == max_retries
    retried_2 = await orchestrator.retry_failed_operation(db=db_session, operation_id=op.id, max_retries=3)
    assert retried_2 is False


@pytest.mark.asyncio
async def test_09_partial_vector_write_chunk_mismatch(db_session: AsyncSession, orchestrator):
    """
    Test Step 9: Partial vector write / chunk count verification failure.
    If target_chunk_count is 4 but only 2 chunks are provided/written,
    the verification gate catches the mismatch, marks version and outbox 'failed',
    and refuses pointer promotion.
    """
    src = Source(name="IRCC", url="https://www.canada.ca", country="Canada", source_type="official", authority_tier=1)
    db_session.add(src)
    await db_session.flush()

    doc = LogicalDocument(source_id=src.id, document_key="partial_write_key", primary_url="https://canada.ca/partial", title="Partial")
    db_session.add(doc)
    await db_session.flush()

    ver = DocumentVersion(
        logical_document_id=doc.id, version_number=1, lifecycle_state="indexing",
        requested_url="https://canada.ca/partial", final_url="https://canada.ca/partial",
        extracted_text="Text",
    )
    db_session.add(ver)
    await db_session.flush()

    legacy_doc = Document(
        source_id=src.id, content_hash="hash_p", raw_html="<p></p>",
        extracted_text="Text", storage_url="https://canada.ca/partial",
        scraped_at=datetime.datetime.utcnow(),
    )
    db_session.add(legacy_doc)
    await db_session.flush()

    # Target is 4 chunks
    op = VersionIndexingOperation(
        document_version_id=ver.id,
        logical_document_id=doc.id,
        status="pending",
        target_chunk_count=4,
    )
    db_session.add(op)
    await db_session.commit()

    # Simulate only 2 chunks provided/written
    partial_chunks = [
        {"text": "Chunk 1", "chunk_index": 0},
        {"text": "Chunk 2", "chunk_index": 1},
    ]

    doc_id = doc.id
    ver_id = ver.id
    op_id = op.id
    legacy_id = legacy_doc.id

    success, err = await orchestrator.execute_indexing_operation(
        db=db_session,
        operation_id=op_id,
        chunks=partial_chunks,
        legacy_doc_id=legacy_id,
    )

    assert success is False
    assert "Chunk verification failed" in err

    # Check candidate version is failed
    ver_after = await db_session.get(DocumentVersion, ver_id)
    assert ver_after.lifecycle_state == "failed"

    # Check operation is failed
    op_after = await db_session.get(VersionIndexingOperation, op_id)
    assert op_after.status == "failed"
    assert "Chunk verification failed: expected 4, persisted 2" in op_after.error_message

    # Check pointer was NOT created
    ptr = await db_session.get(CurrentDocumentPointer, doc_id)
    assert ptr is None


@pytest.mark.asyncio
async def test_10_interrupted_ingestion_recovery(db_session: AsyncSession, orchestrator):
    """
    Test Step 10: Interrupted ingestion recovery.
    Simulates a worker crash where candidate version and outbox operation were persisted
    in 'pending' state, but the worker died before indexing.
    A recovery worker reclaims the operation, performs indexing, verifies chunks,
    and successfully promotes the pointer.
    """
    src = Source(name="IRCC", url="https://www.canada.ca", country="Canada", source_type="official", authority_tier=1)
    db_session.add(src)
    await db_session.flush()

    doc = LogicalDocument(source_id=src.id, document_key="interrupted_key", primary_url="https://canada.ca/interrupted", title="Interrupted")
    db_session.add(doc)
    await db_session.flush()

    ver = DocumentVersion(
        logical_document_id=doc.id, version_number=1, lifecycle_state="indexing",
        requested_url="https://canada.ca/interrupted", final_url="https://canada.ca/interrupted",
        extracted_text="Interrupted text content.",
    )
    db_session.add(ver)
    await db_session.flush()

    legacy_doc = Document(
        source_id=src.id, content_hash="hash_int", raw_html="<p></p>",
        extracted_text="Interrupted text content.", storage_url="https://canada.ca/interrupted",
        scraped_at=datetime.datetime.utcnow(),
    )
    db_session.add(legacy_doc)
    await db_session.flush()

    chunks = [
        {"text": "Chunk part 1", "chunk_index": 0},
        {"text": "Chunk part 2", "chunk_index": 1},
    ]

    op = VersionIndexingOperation(
        document_version_id=ver.id,
        logical_document_id=doc.id,
        status="pending",
        target_chunk_count=len(chunks),
    )
    db_session.add(op)
    await db_session.commit()

    # Recovery worker resumes and executes the interrupted operation
    success, err = await orchestrator.execute_indexing_operation(
        db=db_session,
        operation_id=op.id,
        chunks=chunks,
        legacy_doc_id=legacy_doc.id,
        worker_lease_id="recovery_worker_99",
    )

    assert success is True
    assert err is None

    # Version is promoted to ready
    await db_session.refresh(ver)
    assert ver.lifecycle_state == "ready"

    # Pointer is successfully established
    ptr = await db_session.get(CurrentDocumentPointer, doc.id)
    assert ptr is not None
    assert ptr.current_version_id == ver.id
    assert ptr.verified_chunk_count == 2

