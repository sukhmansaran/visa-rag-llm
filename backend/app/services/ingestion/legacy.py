"""
Legacy Ingestion Service (preserved for backward compatibility with tasks/workers).
"""

from typing import Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import app.services.ingestion as ingestion_pkg
from app.models.source import Source
from app.models.document import Document
from app.models.vector_chunk import VectorChunk


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
        
        # Check if content changed (compare hash)
        result = await db.execute(
            select(Document)
            .where(Document.source_id == source_id)
            .where(Document.content_hash == scraped_data['content_hash'])
            .order_by(Document.scraped_at.desc())
        )
        existing_doc = result.scalar_one_or_none()
        
        if existing_doc:
            return {
                'status': 'skipped',
                'reason': 'content_unchanged',
                'source_id': source_id,
                'url': source.url,
            }
        
        # Step 2: Save document snapshot
        document = Document(
            source_id=source_id,
            content_hash=scraped_data['content_hash'],
            raw_html=scraped_data.get('raw_html'),
            extracted_text=scraped_data['extracted_text'],
            storage_url=None,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        
        # Step 2a: Factual Summary
        from app.services.llm import llm_service
        try:
            text_to_summarize = scraped_data['extracted_text'][:30000]
            summary_text = await llm_service.factual_summarize(text_to_summarize)
            print(f"[INGESTION] Factual summary generated: {len(summary_text)} chars")
        except Exception as e:
            print(f"[INGESTION] Error during factual summarization: {e}")
            summary_text = scraped_data['extracted_text']

        # Step 3: Chunk
        chunks = ingestion_pkg.chunk_document(
            text=summary_text,
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
        
        # Step 4: Embed
        chunk_texts = [chunk['text'] for chunk in chunks]
        embeddings = await ingestion_pkg.embed_texts_batch(chunk_texts)
        
        for chunk, embedding in zip(chunks, embeddings):
            chunk['embedding'] = embedding
            chunk['metadata']['source_id'] = source_id
            chunk['metadata']['document_id'] = document.id
            if source.country:
                chunk['metadata']['country'] = source.country
            chunk['metadata']['source_type'] = source.source_type
        
        # Step 5: Store in vector DB
        vector_ids = await ingestion_pkg.vector_store.upsert_chunks(chunks)
        
        # Step 6: Save vector chunk metadata to DB
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
        
        return {
            'status': 'success',
            'source_id': source_id,
            'url': source.url,
            'document_id': document.id,
            'chunks_created': len(chunks),
            'content_hash': document.content_hash,
        }
    
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
