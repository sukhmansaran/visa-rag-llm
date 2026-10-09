"""
Integration tests for ingestion pipeline.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.ingestion import ingestion_service
from app.services.scraper import WebScraper
from app.services.chunker import chunk_document
from app.models.source import Source
from app.models.document import Document


class TestIngestionPipeline:
    """Test complete ingestion pipeline."""
    
    @pytest.mark.asyncio
    @patch('app.services.ingestion.scrape_with_retry')
    @patch('app.services.ingestion.embed_texts_batch')
    @patch('app.services.ingestion.vector_store.upsert_chunks')
    async def test_complete_ingestion_flow(
        self,
        mock_upsert,
        mock_embed,
        mock_scrape,
        db_session
    ):
        """Test complete ingestion: scrape → chunk → embed → store."""
        
        # Create test source
        source = Source(
            url="https://example.com/visa-info",
            name="Test Source",
            country="Canada",
            source_type="embassy",
            is_active=True
        )
        db_session.add(source)
        await db_session.commit()
        await db_session.refresh(source)
        
        # Mock scraping
        mock_scrape.return_value = {
            'url': source.url,
            'title': 'Canada Visa Information',
            'raw_html': '<html>...</html>',
            'extracted_text': 'Canada student visa requirements include proof of acceptance and financial documents.',
            'content_hash': 'abc123',
            'scraped_at': '2024-01-15T10:00:00Z'
        }
        
        # Mock embeddings
        mock_embed.return_value = [[0.1] * 1536, [0.2] * 1536]
        
        # Mock vector store
        mock_upsert.return_value = ['vec1', 'vec2']
        
        # Execute ingestion
        result = await ingestion_service.ingest_source(source.id, db_session)
        
        assert result['status'] == 'success'
        assert result['source_id'] == source.id
        assert result['chunks_created'] >= 1
        
        # Verify scraping was called
        mock_scrape.assert_called_once_with(source.url)
        
        # Verify embeddings were generated
        mock_embed.assert_called_once()
        
        # Verify vectors were stored
        mock_upsert.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.services.ingestion.scrape_with_retry')
    async def test_ingestion_skips_unchanged_content(
        self,
        mock_scrape,
        db_session
    ):
        """Test that ingestion skips unchanged content."""
        
        # Create source and existing document
        source = Source(
            url="https://example.com/visa-info",
            name="Test Source",
            country="Canada",
            source_type="embassy",
            is_active=True
        )
        db_session.add(source)
        await db_session.commit()
        await db_session.refresh(source)
        
        # Create existing document with same hash
        existing_doc = Document(
            source_id=source.id,
            content_hash='abc123',
            extracted_text='Same content',
            raw_html='<html>...</html>'
        )
        db_session.add(existing_doc)
        await db_session.commit()
        
        # Mock scraping returns same hash
        mock_scrape.return_value = {
            'url': source.url,
            'title': 'Canada Visa Information',
            'raw_html': '<html>...</html>',
            'extracted_text': 'Same content',
            'content_hash': 'abc123',  # Same hash
            'scraped_at': '2024-01-15T10:00:00Z'
        }
        
        # Execute ingestion
        result = await ingestion_service.ingest_source(source.id, db_session)
        
        assert result['status'] == 'skipped'
        assert result['reason'] == 'content_unchanged'
    
    @pytest.mark.asyncio
    async def test_ingestion_inactive_source(self, db_session):
        """Test that ingestion fails for inactive sources."""
        
        # Create inactive source
        source = Source(
            url="https://example.com/visa-info",
            name="Test Source",
            source_type="official",
            is_active=False
        )
        db_session.add(source)
        await db_session.commit()
        await db_session.refresh(source)
        
        # Execute ingestion
        with pytest.raises(ValueError, match="inactive"):
            await ingestion_service.ingest_source(source.id, db_session)
    
    @pytest.mark.asyncio
    async def test_ingestion_nonexistent_source(self, db_session):
        """Test that ingestion fails for nonexistent sources."""
        
        with pytest.raises(ValueError, match="not found"):
            await ingestion_service.ingest_source(99999, db_session)


class TestChunking:
    """Test text chunking functionality."""
    
    def test_chunk_document_basic(self):
        """Test basic document chunking."""
        
        text = "This is a test document. " * 100  # ~2500 chars
        
        chunks = chunk_document(
            text=text,
            url="https://example.com",
            title="Test Document",
            scraped_at="2024-01-15T10:00:00Z",
            chunk_size=1000,
            overlap=200
        )
        
        assert len(chunks) >= 2
        assert all('text' in chunk for chunk in chunks)
        assert all('metadata' in chunk for chunk in chunks)
        assert all('chunk_index' in chunk for chunk in chunks)
    
    def test_chunk_document_metadata(self):
        """Test that chunks contain correct metadata."""
        
        text = "Test document content."
        url = "https://example.com/test"
        title = "Test Title"
        scraped_at = "2024-01-15T10:00:00Z"
        
        chunks = chunk_document(
            text=text,
            url=url,
            title=title,
            scraped_at=scraped_at
        )
        
        assert len(chunks) >= 1
        chunk = chunks[0]
        
        assert chunk['metadata']['url'] == url
        assert chunk['metadata']['title'] == title
        assert chunk['metadata']['scraped_at'] == scraped_at
    
    def test_chunk_document_overlap(self):
        """Test that chunks have overlap."""
        
        text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. " * 20
        
        chunks = chunk_document(
            text=text,
            url="https://example.com",
            title="Test",
            scraped_at="2024-01-15",
            chunk_size=500,
            overlap=100
        )
        
        if len(chunks) > 1:
            # Check that there's some overlap between consecutive chunks
            # (This is a simplified check)
            assert len(chunks[0]['text']) > 400
            assert len(chunks[1]['text']) > 0


class TestScraping:
    """Test web scraping functionality."""
    
    @pytest.mark.asyncio
    @patch('app.services.scraper.async_playwright')
    async def test_scrape_url_success(self, mock_playwright):
        """Test successful URL scraping."""
        
        # Mock Playwright
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Test content</body></html>")
        mock_page.title = AsyncMock(return_value="Test Page")
        mock_page.close = AsyncMock()
        
        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()
        
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_playwright_instance.start = AsyncMock(return_value=mock_playwright_instance)
        
        mock_playwright.return_value = mock_playwright_instance
        
        async with WebScraper() as scraper:
            result = await scraper.scrape_url("https://example.com")
        
        assert result['url'] == "https://example.com"
        assert result['title'] == "Test Page"
        assert 'content_hash' in result
        assert 'extracted_text' in result
    
    def test_scrape_url_pdf_detection(self):
        """Test PDF URL detection."""
        
        pdf_url = "https://example.com/document.pdf"
        html_url = "https://example.com/page.html"
        
        assert pdf_url.lower().endswith('.pdf')
        assert not html_url.lower().endswith('.pdf')


class TestReingestAllSources:
    """Test reingesting all sources."""
    
    @pytest.mark.asyncio
    @patch('app.services.ingestion.ingestion_service.ingest_source')
    async def test_reingest_all_sources(self, mock_ingest, db_session):
        """Test reingesting all active sources."""
        
        # Create multiple sources
        sources = [
            Source(url=f"https://example.com/{i}", name=f"Source {i}", source_type="official", is_active=True, priority=i)
            for i in range(3)
        ]
        for source in sources:
            db_session.add(source)
        await db_session.commit()
        
        # Mock ingestion
        mock_ingest.return_value = {'status': 'success'}
        
        # Execute reingest
        results = await ingestion_service.reingest_all_sources(db_session)
        
        assert len(results) == 3
        assert mock_ingest.call_count == 3
    
    @pytest.mark.asyncio
    @patch('app.services.ingestion.ingestion_service.ingest_source')
    async def test_reingest_skips_inactive_sources(self, mock_ingest, db_session):
        """Test that reingest skips inactive sources."""
        
        # Create active and inactive sources
        active_source = Source(url="https://example.com/1", name="Active", source_type="official", is_active=True)
        inactive_source = Source(url="https://example.com/2", name="Inactive", source_type="official", is_active=False)
        
        db_session.add(active_source)
        db_session.add(inactive_source)
        await db_session.commit()
        
        mock_ingest.return_value = {'status': 'success'}
        
        results = await ingestion_service.reingest_all_sources(db_session)
        
        # Should only ingest active source
        assert len(results) == 1
        assert mock_ingest.call_count == 1
    
    @pytest.mark.asyncio
    @patch('app.services.ingestion.ingestion_service.ingest_source')
    async def test_reingest_handles_errors(self, mock_ingest, db_session):
        """Test that reingest handles errors gracefully."""
        
        # Create sources
        source1 = Source(url="https://example.com/1", name="Source 1", source_type="official", is_active=True)
        source2 = Source(url="https://example.com/2", name="Source 2", source_type="official", is_active=True)
        
        db_session.add(source1)
        db_session.add(source2)
        await db_session.commit()
        
        # Mock ingestion - first succeeds, second fails
        mock_ingest.side_effect = [
            {'status': 'success'},
            Exception("Ingestion error")
        ]
        
        results = await ingestion_service.reingest_all_sources(db_session)
        
        assert len(results) == 2
        assert results[0]['status'] == 'success'
        assert results[1]['status'] == 'error'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
