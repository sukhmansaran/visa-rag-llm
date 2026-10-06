"""
Orchestration service for the full ingestion pipeline.
Scrape → Chunk → Embed → Store
"""

from typing import Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.scraper import scrape_with_retry
from app.services.chunker import chunk_document
from app.services.embeddings import embed_texts_batch
from app.services.vector_store import vector_store
from app.models.source import Source
from app.models.document import Document
from app.models.vector_chunk import VectorChunk


class IngestionService:
    """Orchestrates the full ingestion pipeline."""
    
    async def ingest_source(
        self,
        source_id: int,
        db: AsyncSession,
    ) -> Dict:
        """
        Ingest a source: scrape → chunk → embed → store.
        
        Args:
            source_id: ID of the source to ingest
            db: Database session
            
        Returns:
            Dict with ingestion stats
        """
        # Get source from DB
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        
        if not source:
            raise ValueError(f"Source {source_id} not found")
        
        if not source.is_active:
            raise ValueError(f"Source {source_id} is inactive")
        
        # Step 1: Scrape
        scraped_data = await scrape_with_retry(source.url)
        
        # Check if content changed (compare hash)
        result = await db.execute(
            select(Document)
            .where(Document.source_id == source_id)
            .where(Document.content_hash == scraped_data['content_hash'])
            .order_by(Document.scraped_at.desc())
        )
        existing_doc = result.scalar_one_or_none()
        
        if existing_doc:
            # Content hasn't changed, skip re-ingestion
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
            # TODO: Upload raw_html to S3/Firebase and store URL
            storage_url=None,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        
        # Step 2a: Factual Summary (Pre-digest documents)
        from app.services.llm import llm_service
        try:
            # We take up to 30000 chars to avoid context limits
            text_to_summarize = scraped_data['extracted_text'][:30000]
            summary_text = await llm_service.factual_summarize(text_to_summarize)
            print(f"[INGESTION] Factual summary generated: {len(summary_text)} chars")
        except Exception as e:
            print(f"[INGESTION] Error during factual summarization: {e}")
            summary_text = scraped_data['extracted_text']

        # Step 3: Chunk
        chunks = chunk_document(
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
        embeddings = await embed_texts_batch(chunk_texts)
        
        # Combine embeddings with chunks
        for chunk, embedding in zip(chunks, embeddings):
            chunk['embedding'] = embedding
            chunk['metadata']['source_id'] = source_id
            chunk['metadata']['document_id'] = document.id
            if source.country:
                chunk['metadata']['country'] = source.country
            chunk['metadata']['source_type'] = source.source_type
        
        # Step 5: Store in vector DB
        vector_ids = await vector_store.upsert_chunks(chunks)
        
        # Step 6: Save vector chunk metadata to DB
        for chunk, vector_id in zip(chunks, vector_ids):
            vector_chunk = VectorChunk(
                document_id=document.id,
                chunk_index=chunk['chunk_index'],
                text=chunk['text'],
                vector_id=vector_id,
                metadata=chunk['metadata'],
            )
            db.add(vector_chunk)
        
        # Update source last_scraped_at
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
        """
        Reingest all active sources.
        
        Args:
            db: Database session
            
        Returns:
            List of ingestion results
        """
        result = await db.execute(
            select(Source)
            .where(Source.is_active == True)
            .order_by(Source.priority)
        )
        sources = result.scalars().all()
        
        results = []
        for source in sources:
            try:
                result = await self.ingest_source(source.id, db)
                results.append(result)
            except Exception as e:
                results.append({
                    'status': 'error',
                    'source_id': source.id,
                    'url': source.url,
                    'error': str(e),
                })
        
        return results


# Global instance
ingestion_service = IngestionService()
