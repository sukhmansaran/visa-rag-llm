"""
Legacy Ingestion Service (preserved for backward compatibility with tasks/workers).
"""

import logging
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

import app.services.ingestion as ingestion_pkg
from app.models.source import Source
from app.models.document import Document
from app.models.vector_chunk import VectorChunk
from app.services.source_registry import looks_like_error_page

logger = logging.getLogger(__name__)


class IngestionService:
    """Orchestrates the legacy ingestion pipeline."""
    
    async def ingest_source(
        self,
        source_id: int,
        db: AsyncSession,
    ) -> Dict:
        """
        Ingest a source: scrape → chunk → embed → store.
        """
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        
        if not source:
            raise ValueError(f"Source {source_id} not found")
        
        if not source.is_active:
            raise ValueError(f"Source {source_id} is inactive")
        
        # Step 1: Scrape
        scraped_data = await ingestion_pkg.scrape_with_retry(source.url)

        # An error page served with HTTP 200 must never become "official" text (M0.10: the University of
        # Toronto source was stored as "Page not found" and retrieved like any other chunk)
        error_page = looks_like_error_page(scraped_data.get('title', ''), scraped_data.get('extracted_text', ''))
        if error_page:
            logger.warning("Not ingesting source %s (%s): %s", source_id, source.url, error_page)
            return {
                'status': 'error',
                'reason': 'error_page',
                'detail': error_page,
                'source_id': source_id,
                'url': source.url,
            }

        # Compare with the LATEST indexed version only (M0.14). Matching any past version re-used a stale copy
        # when a page reverted, and two equal hashes made scalar_one_or_none() raise.
        latest = await self._latest_indexed_document(db, source_id)
        if latest and latest.content_hash == scraped_data['content_hash']:
            removed = await self._supersede_older_versions(db, source_id, keep_document_id=latest.id)
            return {
                'status': 'skipped',
                'reason': 'content_unchanged',
                'source_id': source_id,
                'url': source.url,
                'superseded_chunks_removed': removed,  # heals any leftovers from an interrupted run
            }

        # Step 2: Chunk the VERBATIM official text.
        # (Previously each page was squeezed into a <=150-word LLM summary and only that was indexed:
        # most facts were lost, and any small-model error was stored and cited as Tier-1 official text.)
        chunks = ingestion_pkg.chunk_document(
            text=scraped_data['extracted_text'],
            url=source.url,
            title=scraped_data['title'],
            scraped_at=scraped_data['scraped_at'],
        )

        if not chunks:
            return {
                'status': 'error',
                'reason': 'no_chunks_generated',
                'source_id': source_id,
            }

        # Step 3: Embed before anything is saved, so a failure leaves no document without chunks
        chunk_texts = [chunk['text'] for chunk in chunks]
        embeddings = await ingestion_pkg.embed_texts_batch(chunk_texts)

        # Step 4: Document snapshot (flushed for its id; committed together with its chunks below)
        document = Document(
            source_id=source_id,
            content_hash=scraped_data['content_hash'],
            raw_html=scraped_data.get('raw_html'),
            extracted_text=scraped_data['extracted_text'],
            storage_url=None,
        )
        db.add(document)
        await db.flush()

        for chunk, embedding in zip(chunks, embeddings):
            chunk['embedding'] = embedding
            chunk['metadata']['source_id'] = source_id
            chunk['metadata']['document_id'] = document.id
            if source.country:
                chunk['metadata']['country'] = source.country
            chunk['metadata']['source_type'] = source.source_type
            chunk['metadata']['authority_tier'] = source.authority_tier
            chunk['metadata']['source_name'] = source.name

        # Step 5: Store in vector DB
        vector_ids = await ingestion_pkg.vector_store.upsert_chunks(chunks)

        # Step 6: Save vector chunk metadata to DB, with the document, in one transaction
        for chunk, vector_id in zip(chunks, vector_ids):
            vector_chunk = VectorChunk(
                document_id=document.id,
                chunk_index=chunk['chunk_index'],
                text=chunk['text'],
                vector_id=vector_id,
                chunk_metadata=chunk['metadata'],
            )
            db.add(vector_chunk)

        source.last_scraped_at = document.scraped_at
        await db.commit()

        # Step 7: Only now retire the previous version's chunks: the page is never without chunks, and a crash
        # here leaves duplicates that the next run removes (see the skipped branch above)
        removed = await self._supersede_older_versions(db, source_id, keep_document_id=document.id)

        return {
            'status': 'success',
            'source_id': source_id,
            'url': source.url,
            'document_id': document.id,
            'chunks_created': len(chunks),
            'superseded_chunks_removed': removed,
            'content_hash': document.content_hash,
        }

    @staticmethod
    async def _latest_indexed_document(db: AsyncSession, source_id: int) -> Optional[Document]:
        """The newest document of this source that actually has chunks (an un-indexed one never counts)."""
        has_chunks = select(VectorChunk.id).where(VectorChunk.document_id == Document.id).exists()
        result = await db.execute(
            select(Document)
            .where(Document.source_id == source_id, has_chunks)
            .order_by(Document.scraped_at.desc(), Document.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _supersede_older_versions(db: AsyncSession, source_id: int, keep_document_id: int) -> int:
        """
        Make `keep_document_id` the only retrievable version of the source (M0.14): delete the older versions'
        chunks from the vector store and mark their vector_chunks rows superseded. Older Document rows stay as
        the page's version history (change detection and the M7 policy watch read them).
        """
        removed = await ingestion_pkg.vector_store.delete_superseded(source_id, keep_document_id)
        older_docs = select(Document.id).where(Document.source_id == source_id, Document.id != keep_document_id)
        await db.execute(
            update(VectorChunk)
            .where(VectorChunk.document_id.in_(older_docs), VectorChunk.status != "superseded")
            .values(status="superseded")
        )
        await db.commit()
        if removed:
            logger.info("Source %s: removed %s chunk(s) of older versions", source_id, removed)
        return removed

    async def reingest_all_sources(self, db: AsyncSession) -> List[Dict]:
        """Reingest all active sources."""
        result = await db.execute(
            select(Source)
            .where(Source.is_active == True)
            .order_by(Source.priority)
        )
        sources = result.scalars().all()
        
        results = []
        for source in sources:
            try:
                res = await self.ingest_source(source.id, db)
                results.append(res)
            except Exception as e:
                results.append({
                    'status': 'error',
                    'source_id': source.id,
                    'url': source.url,
                    'error': str(e),
                })
        
        return results


# Global instance for backward compatibility
ingestion_service = IngestionService()
