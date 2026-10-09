"""
Ingestion Orchestration Service: Milestone B2.2

Orchestrates the authoritative Canadian immigration ingestion lifecycle:
1. Fetch and Normalize (AsyncOfficialFetcher + CanadaNormalizer)
2. Content Hash Change Detection (Zero duplicate versions for unchanged content)
3. Transactional Candidate Version & Outbox Enqueue (VersionIndexingOperation)
4. Two-Phase Index, Verification Gate, and Atomic Current-Pointer Promotion
5. Lease fencing, retry policies, and resilient failure recovery
"""

import datetime
import enum
import hashlib
import logging
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update, func, text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select as sm_select

from app.models.source import Source
from app.models.document import Document
from app.models.logical_document import LogicalDocument
from app.models.document_version import DocumentVersion
from app.models.current_document_pointer import CurrentDocumentPointer
from app.models.version_indexing_operation import VersionIndexingOperation
from app.models.vector_chunk import VectorChunk
from app.models.ingestion_run import IngestionRun

from app.services.official_fetcher import (
    AsyncOfficialFetcher,
    FetchResult,
    FetcherError,
    HTTPFetchError,
    FetchTimeoutError,
    SSRFBlockedError,
    ResponseTooLargeError,
    UnsupportedContentTypeError,
)
from app.services.canada_normalizer import (
    CanadaNormalizer,
    NormalizedDocument,
    NormalizationError,
    ContentTooShortError,
)
from app.services.chunker import TextChunker
from app.services.vector_store import VectorStore, vector_store as default_vector_store

logger = logging.getLogger(__name__)


class IngestionStepStatus(str, enum.Enum):
    SUCCESS = "success"
    UNCHANGED = "unchanged"
    FETCH_ERROR = "fetch_error"
    NORMALIZATION_ERROR = "normalization_error"
    INDEXING_ERROR = "indexing_error"
    VERIFICATION_FAILED = "verification_failed"


class IngestionOutcome:
    """Detailed result of an ingestion attempt for a single URL."""
    def __init__(
        self,
        url: str,
        status: IngestionStepStatus,
        logical_document_id: Optional[int] = None,
        version_id: Optional[int] = None,
        version_number: Optional[int] = None,
        is_new_version: bool = False,
        chunks_indexed: int = 0,
        error_message: Optional[str] = None,
        http_status: Optional[int] = None,
    ):
        self.url = url
        self.status = status
        self.logical_document_id = logical_document_id
        self.version_id = version_id
        self.version_number = version_number
        self.is_new_version = is_new_version
        self.chunks_indexed = chunks_indexed
        self.error_message = error_message
        self.http_status = http_status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status.value,
            "logical_document_id": self.logical_document_id,
            "version_id": self.version_id,
            "version_number": self.version_number,
            "is_new_version": self.is_new_version,
            "chunks_indexed": self.chunks_indexed,
            "error_message": self.error_message,
            "http_status": self.http_status,
        }


def compute_canonical_url(url: str) -> str:
    """Deterministic canonical URL string normalization."""
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    port = parsed.port
    if port and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = netloc.split(":")[0]

    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")

    query_parts = []
    if parsed.query:
        for q in parsed.query.split("&"):
            if not q:
                continue
            k = q.split("=")[0].lower()
            if not (k.startswith("utm_") or k in {"fbclid", "gclid", "_ga", "ref", "source"}):
                query_parts.append(q)
    query_parts.sort()
    norm_query = "&".join(query_parts)

    return urllib.parse.urlunparse((scheme, netloc, path, "", norm_query, ""))


def compute_document_key(url: str) -> str:
    """Deterministic SHA-256 key for a logical document from canonical URL."""
    canonical = compute_canonical_url(url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IngestionOrchestrator:
    """
    Production ingestion orchestrator for Canadian immigration sources.
    Enforces atomic lifecycle transitions, change detection, and outbox indexing.
    """

    def __init__(
        self,
        fetcher: Optional[AsyncOfficialFetcher] = None,
        normalizer: Optional[CanadaNormalizer] = None,
        chunker: Optional[TextChunker] = None,
        vector_store: Optional[VectorStore] = None,
        lease_duration_seconds: int = 300,
    ):
        self.fetcher = fetcher or AsyncOfficialFetcher()
        self.normalizer = normalizer or CanadaNormalizer()
        self.chunker = chunker or TextChunker(chunk_size=1000, overlap=200)
        self.vector_store = vector_store or default_vector_store
        self.lease_duration_seconds = lease_duration_seconds

    async def ingest_urls(
        self,
        urls: List[str],
        db: AsyncSession,
        source_id: Optional[int] = None,
        trigger_type: str = "manual",
    ) -> IngestionRun:
        """
        Orchestrate an ingestion run across a list of target URLs.
        Records an IngestionRun audit record and returns when all URLs are processed.
        """
        run_uuid = f"run_{uuid.uuid4().hex[:16]}"
        ingestion_run = IngestionRun(
            run_id=run_uuid,
            source_id=source_id,
            trigger_type=trigger_type,
            status="started",
            started_at=datetime.datetime.now(datetime.timezone.utc),
            documents_fetched=0,
            documents_updated=0,
            documents_unchanged=0,
            documents_failed=0,
            run_metadata={"urls": urls},
        )
        db.add(ingestion_run)
        await db.commit()
        run_db_id = ingestion_run.id

        outcomes: List[IngestionOutcome] = []
        docs_fetched = 0
        docs_updated = 0
        docs_unchanged = 0
        docs_failed = 0

        for target_url in urls:
            outcome = await self.ingest_single_url(
                url=target_url,
                db=db,
                run_id=run_db_id,
                source_id=source_id,
            )
            outcomes.append(outcome)

            docs_fetched += 1
            if outcome.status == IngestionStepStatus.SUCCESS:
                docs_updated += 1
            elif outcome.status == IngestionStepStatus.UNCHANGED:
                docs_unchanged += 1
            else:
                docs_failed += 1

        # Finalize run status
        if docs_failed == 0:
            final_status = "completed"
        elif docs_updated > 0 or docs_unchanged > 0:
            final_status = "partial"
        else:
            final_status = "failed"

        # Reload ingestion_run cleanly to avoid expired state
        final_run = await db.get(IngestionRun, run_db_id)
        if final_run:
            final_run.documents_fetched = docs_fetched
            final_run.documents_updated = docs_updated
            final_run.documents_unchanged = docs_unchanged
            final_run.documents_failed = docs_failed
            final_run.status = final_status
            final_run.completed_at = datetime.datetime.now(datetime.timezone.utc)
            final_run.run_metadata = {
                "urls": urls,
                "outcomes": [o.to_dict() for o in outcomes],
            }
            db.add(final_run)
            await db.commit()
            await db.refresh(final_run)
            return final_run

        return ingestion_run

    async def ingest_single_url(
        self,
        url: str,
        db: AsyncSession,
        run_id: int,
        source_id: Optional[int] = None,
    ) -> IngestionOutcome:
        """
        Processes a single URL through the full 5-stage ingestion lifecycle.
        Guarantees transactional safety and prevents dangling or falsely current versions.
        """
        canonical_url = compute_canonical_url(url)
        doc_key = compute_document_key(canonical_url)

        # 1. Resolve or Create Logical Document
        logical_doc = await self._get_or_create_logical_document(
            db=db,
            url=canonical_url,
            doc_key=doc_key,
            source_id=source_id,
        )

        # Retrieve current version pointer if present
        current_version = await self._get_current_ready_version(db=db, logical_doc_id=logical_doc.id)

        # 2. Fetch with Conditional Headers (ETag / Last-Modified)
        if_none_match = current_version.etag if current_version else None
        if_modified_since = current_version.last_modified if current_version else None

        try:
            fetch_result = await self.fetcher.fetch(
                canonical_url,
                if_none_match=if_none_match,
                if_modified_since=if_modified_since,
            )
        except Exception as exc:
            # Handle HTTP errors, timeouts, SSRF blocks
            error_cat, status_code = self._classify_fetch_error(exc)
            await self._record_failure_provenance(
                db=db,
                logical_doc=logical_doc,
                category=error_cat,
                http_status=status_code,
                error_msg=str(exc),
            )
            return IngestionOutcome(
                url=canonical_url,
                status=IngestionStepStatus.FETCH_ERROR,
                logical_document_id=logical_doc.id,
                error_message=str(exc),
                http_status=status_code,
            )

        # 3. Check HTTP 304 Not Modified
        if fetch_result.is_not_modified:
            await self._record_verification_success(db=db, logical_doc=logical_doc)
            return IngestionOutcome(
                url=canonical_url,
                status=IngestionStepStatus.UNCHANGED,
                logical_document_id=logical_doc.id,
                version_id=current_version.id if current_version else None,
                version_number=current_version.version_number if current_version else None,
                is_new_version=False,
                http_status=304,
            )

        # 4. Normalize Content
        try:
            if hasattr(self.normalizer, "normalize_html") and ("html" in (fetch_result.content_type or "").lower() or b"<html" in fetch_result.content.lower()):
                normalized_doc = self.normalizer.normalize_html(
                    fetch_result.content,
                    source_url=fetch_result.final_url or canonical_url,
                )
            elif hasattr(self.normalizer, "normalize"):
                normalized_doc = self.normalizer.normalize(
                    fetch_result.content,
                    url=fetch_result.final_url or canonical_url,
                    content_type=fetch_result.content_type,
                )
            else:
                normalized_doc = self.normalizer.normalize_text(
                    fetch_result.content,
                    source_url=fetch_result.final_url or canonical_url,
                )
        except Exception as norm_err:
            await self._record_failure_provenance(
                db=db,
                logical_doc=logical_doc,
                category="normalization_error",
                http_status=fetch_result.status_code,
                error_msg=str(norm_err),
            )
            return IngestionOutcome(
                url=canonical_url,
                status=IngestionStepStatus.NORMALIZATION_ERROR,
                logical_document_id=logical_doc.id,
                error_message=str(norm_err),
                http_status=fetch_result.status_code,
            )

        raw_hash = hashlib.sha256(fetch_result.content).hexdigest()
        norm_hash = normalized_doc.content_hash

        # 5. Change Detection: Compare normalized content hash with current ready version
        if current_version and current_version.normalized_content_hash == norm_hash:
            logger.info("Content unchanged for %s (hash: %s). Skipping version creation.", canonical_url, norm_hash)
            await self._record_verification_success(db=db, logical_doc=logical_doc)
            return IngestionOutcome(
                url=canonical_url,
                status=IngestionStepStatus.UNCHANGED,
                logical_document_id=logical_doc.id,
                version_id=current_version.id,
                version_number=current_version.version_number,
                is_new_version=False,
                http_status=fetch_result.status_code,
            )

        # 6. Content Changed or New Document: Create Candidate Version & Outbox Operation
        source = await db.get(Source, logical_doc.source_id)
        authority_tier = source.authority_tier if source else 1

        chunks = self.chunker.chunk_text(
            text=normalized_doc.text,
            metadata={
                "url": canonical_url,
                "title": normalized_doc.title or logical_doc.title,
                "authority_tier": authority_tier,
            },
        )

        candidate_version, indexing_op, legacy_doc = await self._persist_candidate_version_and_outbox(
            db=db,
            logical_doc=logical_doc,
            run_id=run_id,
            fetch_result=fetch_result,
            normalized_doc=normalized_doc,
            raw_hash=raw_hash,
            norm_hash=norm_hash,
            chunk_count=len(chunks),
        )
        cand_version_id = candidate_version.id
        cand_version_number = candidate_version.version_number
        log_doc_id = logical_doc.id
        indexing_op_id = indexing_op.id
        legacy_id = legacy_doc.id

        # 7. Execute Indexing, Verification, and Atomic Promotion
        success, err_msg = await self.execute_indexing_operation(
            db=db,
            operation_id=indexing_op_id,
            chunks=chunks,
            legacy_doc_id=legacy_id,
        )

        if not success:
            return IngestionOutcome(
                url=canonical_url,
                status=IngestionStepStatus.INDEXING_ERROR,
                logical_document_id=log_doc_id,
                version_id=cand_version_id,
                version_number=cand_version_number,
                is_new_version=True,
                error_message=err_msg,
                http_status=fetch_result.status_code,
            )

        return IngestionOutcome(
            url=canonical_url,
            status=IngestionStepStatus.SUCCESS,
            logical_document_id=log_doc_id,
            version_id=cand_version_id,
            version_number=cand_version_number,
            is_new_version=True,
            chunks_indexed=len(chunks),
            http_status=fetch_result.status_code,
        )

    async def execute_indexing_operation(
        self,
        db: AsyncSession,
        operation_id: int,
        chunks: List[Dict[str, Any]],
        legacy_doc_id: int,
        worker_lease_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Executes outbox indexing operation:
        - Claims lease with fencing token
        - Idempotently writes chunks to vector store
        - Inserts staging vector_chunks rows
        - Verifies chunk count against target_chunk_count
        - Atomically promotes candidate version to 'ready' and updates current_document_pointers
        """
        lease_token = worker_lease_id or f"worker_{uuid.uuid4().hex[:12]}"

        # Step A: Claim lease
        claimed = await self.claim_indexing_lease(
            db=db,
            operation_id=operation_id,
            lease_token=lease_token,
            ttl_seconds=self.lease_duration_seconds,
        )
        if not claimed:
            return False, f"Could not acquire lease for operation {operation_id}"

        # Fetch operation, candidate version, and logical document
        op = await db.get(VersionIndexingOperation, operation_id)
        candidate_version = await db.get(DocumentVersion, op.document_version_id)
        logical_doc = await db.get(LogicalDocument, op.logical_document_id)
        source = await db.get(Source, logical_doc.source_id)
        authority_tier = source.authority_tier if source else 1

        try:
            # Step B: Write to Vector Store & Postgres vector_chunks
            vector_items = []
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            for i, chunk in enumerate(chunks):
                chunk_id = f"c_{logical_doc.id}_v{candidate_version.id}_{i}"
                vector_id = f"vec_{logical_doc.id}_v{candidate_version.id}_{i}"

                # Prepare vector store item
                chunk_meta = {
                    "logical_document_id": logical_doc.id,
                    "document_version_id": candidate_version.id,
                    "chunk_id": chunk_id,
                    "chunk_index": i,
                    "url": logical_doc.primary_url,
                    "title": candidate_version.version_metadata.get("title", logical_doc.title),
                    "authority_tier": authority_tier,
                    "created_at": now_utc.isoformat(),
                }
                
                # Mock or generate embedding dummy if vector store requires embedding dict
                vector_items.append({
                    "id": vector_id,
                    "text": chunk["text"],
                    "embedding": [0.0] * 1536,  # VectorStore implementation or mock
                    "metadata": chunk_meta,
                })

                # Check if VectorChunk already exists (idempotency check)
                existing_vc = (
                    await db.execute(
                        select(VectorChunk).where(
                            VectorChunk.logical_document_id == logical_doc.id,
                            VectorChunk.document_version_id == candidate_version.id,
                            VectorChunk.chunk_index == i,
                        )
                    )
                ).scalar_one_or_none()

                if not existing_vc:
                    vc = VectorChunk(
                        document_id=legacy_doc_id,
                        logical_document_id=logical_doc.id,
                        document_version_id=candidate_version.id,
                        chunk_id=chunk_id,
                        status="staging",
                        chunk_index=i,
                        text=chunk["text"],
                        vector_id=vector_id,
                        authority_tier=authority_tier,
                        chunk_metadata=chunk_meta,
                    )
                    db.add(vc)

            await db.flush()

            # Write to vector store service idempotently
            if hasattr(self.vector_store, "upsert_chunks"):
                await self.vector_store.upsert_chunks(vector_items)

            # Step C: Verification Gate
            db_chunk_count = (
                await db.execute(
                    select(func.count(VectorChunk.id)).where(
                        VectorChunk.logical_document_id == logical_doc.id,
                        VectorChunk.document_version_id == candidate_version.id,
                    )
                )
            ).scalar() or 0

            if db_chunk_count != op.target_chunk_count:
                raise ValueError(
                    f"Chunk verification failed: expected {op.target_chunk_count}, persisted {db_chunk_count}"
                )

            # Step D: Atomic Promotion
            # 1. Activate newly verified chunks
            await db.execute(
                update(VectorChunk)
                .where(
                    VectorChunk.logical_document_id == logical_doc.id,
                    VectorChunk.document_version_id == candidate_version.id,
                )
                .values(status="active")
            )

            # 2. Transition candidate version to 'ready'
            candidate_version.lifecycle_state = "ready"
            db.add(candidate_version)

            # 3. Supersede previous version and chunks if pointer exists
            current_ptr = await db.get(CurrentDocumentPointer, logical_doc.id)
            if current_ptr:
                prev_version_id = current_ptr.current_version_id
                if prev_version_id != candidate_version.id:
                    prev_ver = await db.get(DocumentVersion, prev_version_id)
                    if prev_ver:
                        prev_ver.lifecycle_state = "superseded"
                        db.add(prev_ver)

                    await db.execute(
                        update(VectorChunk)
                        .where(
                            VectorChunk.logical_document_id == logical_doc.id,
                            VectorChunk.document_version_id == prev_version_id,
                        )
                        .values(status="superseded")
                    )

                # Update existing pointer
                current_ptr.current_version_id = candidate_version.id
                current_ptr.promoted_at = now_utc
                current_ptr.promoted_by = "ingestion_orchestrator"
                current_ptr.verified_chunk_count = db_chunk_count
                db.add(current_ptr)
            else:
                # Create initial pointer
                new_ptr = CurrentDocumentPointer(
                    logical_document_id=logical_doc.id,
                    current_version_id=candidate_version.id,
                    promoted_at=now_utc,
                    promoted_by="ingestion_orchestrator",
                    verified_chunk_count=db_chunk_count,
                )
                db.add(new_ptr)

            # 4. Finalize outbox operation
            op.status = "completed"
            op.completed_at = now_utc
            op.verified_chunk_count = db_chunk_count
            op.worker_lease_id = None
            op.lease_expires_at = None
            db.add(op)

            # 5. Clear logical document failure provenance and set last_verified_at
            logical_doc.last_verified_at = now_utc
            logical_doc.last_failure_at = None
            logical_doc.last_failure_category = None
            logical_doc.last_failure_http_status = None
            db.add(logical_doc)

            await db.commit()
            return True, None

        except Exception as exc:
            await db.rollback()
            logger.error("Failed executing indexing operation %s: %s", operation_id, exc)

            try:
                f_op = await db.get(VersionIndexingOperation, operation_id)
                if f_op:
                    f_op.status = "failed"
                    f_op.retry_count += 1
                    f_op.error_message = str(exc)
                    f_op.worker_lease_id = None
                    f_op.lease_expires_at = None
                    db.add(f_op)
                    f_cand = await db.get(DocumentVersion, f_op.document_version_id)
                    if f_cand:
                        f_cand.lifecycle_state = "failed"
                        db.add(f_cand)
                    await db.commit()
            except Exception as rec_err:
                await db.rollback()
                logger.error("Error updating failure status for op %s: %s", operation_id, rec_err)

            return False, str(exc)

    async def claim_indexing_lease(
        self,
        db: AsyncSession,
        operation_id: int,
        lease_token: str,
        ttl_seconds: int,
    ) -> bool:
        """
        Fenced lease acquisition.
        Succeeds only if operation is in ('pending', 'failed', 'in_progress')
        and either unowned, expired, or already owned by the same token.
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now_utc + datetime.timedelta(seconds=ttl_seconds)

        stmt = (
            update(VersionIndexingOperation)
            .where(
                VersionIndexingOperation.id == operation_id,
                or_(
                    VersionIndexingOperation.worker_lease_id.is_(None),
                    VersionIndexingOperation.lease_expires_at < now_utc,
                    VersionIndexingOperation.worker_lease_id == lease_token,
                ),
                VersionIndexingOperation.status.in_(["pending", "failed", "in_progress"]),
            )
            .values(
                worker_lease_id=lease_token,
                lease_expires_at=expires_at,
                status="in_progress",
            )
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0

    async def retry_failed_operation(
        self,
        db: AsyncSession,
        operation_id: int,
        max_retries: int = 3,
    ) -> bool:
        """
        Resets a failed indexing operation to pending if below max_retries.
        """
        stmt = (
            update(VersionIndexingOperation)
            .where(
                VersionIndexingOperation.id == operation_id,
                VersionIndexingOperation.status == "failed",
                VersionIndexingOperation.retry_count < max_retries,
            )
            .values(
                status="pending",
                worker_lease_id=None,
                lease_expires_at=None,
            )
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0

    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------

    async def _get_or_create_logical_document(
        self,
        db: AsyncSession,
        url: str,
        doc_key: str,
        source_id: Optional[int] = None,
    ) -> LogicalDocument:
        """Finds or initializes a LogicalDocument entity with referential integrity."""
        result = await db.execute(
            select(LogicalDocument).where(LogicalDocument.document_key == doc_key)
        )
        doc = result.scalar_one_or_none()
        if doc:
            return doc

        # Ensure valid source exists
        effective_source_id = source_id
        if not effective_source_id:
            src_result = await db.execute(select(Source).order_by(Source.id).limit(1))
            first_src = src_result.scalar_one_or_none()
            if first_src:
                effective_source_id = first_src.id
            else:
                new_src = Source(
                    name="Immigration, Refugees and Citizenship Canada",
                    url="https://www.canada.ca",
                    country="Canada",
                    source_type="official",
                    authority_tier=1,
                    is_active=True,
                )
                db.add(new_src)
                await db.flush()
                effective_source_id = new_src.id

        doc = LogicalDocument(
            source_id=effective_source_id,
            document_key=doc_key,
            primary_url=url,
            canonical_url=url,
            title="Canadian Immigration Policy Guide",
            document_type="policy_guide",
            status="active",
        )
        db.add(doc)
        await db.flush()
        return doc

    async def _get_current_ready_version(
        self,
        db: AsyncSession,
        logical_doc_id: int,
    ) -> Optional[DocumentVersion]:
        """Resolves currently promoted ready version through current_document_pointers."""
        stmt = (
            select(DocumentVersion)
            .join(
                CurrentDocumentPointer,
                CurrentDocumentPointer.current_version_id == DocumentVersion.id,
            )
            .where(CurrentDocumentPointer.logical_document_id == logical_doc_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _persist_candidate_version_and_outbox(
        self,
        db: AsyncSession,
        logical_doc: LogicalDocument,
        run_id: int,
        fetch_result: FetchResult,
        normalized_doc: NormalizedDocument,
        raw_hash: str,
        norm_hash: str,
        chunk_count: int,
    ) -> Tuple[DocumentVersion, VersionIndexingOperation, Document]:
        """
        Creates candidate DocumentVersion and VersionIndexingOperation in a single atomic transaction.
        The pointer is deliberately UNTOUCHED at this stage.
        """
        # Determine next version number
        max_ver = (
            await db.execute(
                select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(
                    DocumentVersion.logical_document_id == logical_doc.id
                )
            )
        ).scalar() or 0
        next_ver = max_ver + 1

        # Create legacy Document record for backward compatibility
        legacy_doc = Document(
            source_id=logical_doc.source_id,
            content_hash=raw_hash,
            raw_html=fetch_result.text,
            extracted_text=normalized_doc.text,
            storage_url=logical_doc.primary_url,
            scraped_at=datetime.datetime.utcnow(),
        )
        db.add(legacy_doc)
        await db.flush()

        # Create candidate version in 'indexing' lifecycle state
        cand_version = DocumentVersion(
            logical_document_id=logical_doc.id,
            ingestion_run_id=run_id,
            version_number=next_ver,
            lifecycle_state="indexing",
            requested_url=fetch_result.requested_url,
            final_url=fetch_result.final_url,
            raw_content_hash=raw_hash,
            normalized_content_hash=norm_hash,
            legacy_scraper_hash=raw_hash,
            etag=fetch_result.etag,
            last_modified=fetch_result.last_modified,
            content_type=fetch_result.content_type,
            raw_byte_count=fetch_result.byte_count,
            normalized_char_count=len(normalized_doc.text),
            language=normalized_doc.language or "en",
            extracted_text=normalized_doc.text,
            raw_html=fetch_result.text,
            version_metadata={
                "title": normalized_doc.title or logical_doc.title,
                "warnings": normalized_doc.warnings,
            },
        )
        db.add(cand_version)
        await db.flush()

        # Update logical document title if refined by normalizer
        if normalized_doc.title:
            logical_doc.title = normalized_doc.title
            db.add(logical_doc)

        # Create outbox record
        indexing_op = VersionIndexingOperation(
            document_version_id=cand_version.id,
            logical_document_id=logical_doc.id,
            operation_type="index_new_version",
            status="pending",
            target_chunk_count=chunk_count,
            verified_chunk_count=0,
            vector_backend="chroma",
        )
        db.add(indexing_op)
        await db.commit()

        await db.refresh(cand_version)
        await db.refresh(indexing_op)
        return cand_version, indexing_op, legacy_doc

    async def _record_verification_success(
        self,
        db: AsyncSession,
        logical_doc: LogicalDocument,
    ) -> None:
        """Records successful provenance verification when content is verified unchanged."""
        logical_doc.last_verified_at = datetime.datetime.now(datetime.timezone.utc)
        logical_doc.last_failure_at = None
        logical_doc.last_failure_category = None
        logical_doc.last_failure_http_status = None
        db.add(logical_doc)
        await db.commit()

    async def _record_failure_provenance(
        self,
        db: AsyncSession,
        logical_doc: LogicalDocument,
        category: str,
        http_status: Optional[int],
        error_msg: str,
    ) -> None:
        """Records upstream failure provenance without mutating versions or pointers."""
        logical_doc.last_failure_at = datetime.datetime.now(datetime.timezone.utc)
        logical_doc.last_failure_category = category
        logical_doc.last_failure_http_status = http_status
        db.add(logical_doc)
        await db.commit()

    def _classify_fetch_error(self, exc: Exception) -> Tuple[str, Optional[int]]:
        """Categorizes exception into provenance taxonomy."""
        if isinstance(exc, HTTPFetchError):
            return "http_error", exc.status_code
        elif isinstance(exc, FetchTimeoutError):
            return "timeout", None
        elif isinstance(exc, SSRFBlockedError):
            return "ssrf_blocked", None
        elif isinstance(exc, ResponseTooLargeError):
            return "response_too_large", None
        elif isinstance(exc, UnsupportedContentTypeError):
            return "unsupported_content_type", None
        elif isinstance(exc, FetcherError):
            return "fetcher_error", None
        return "network_error", None
