"""
Unit tests for retrieval service.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
from app.services.retrieval import retrieval_service, RetrievalService


class TestRetrievalService:
    """Test retrieval service functionality."""
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_retrieve_basic(self, mock_search, mock_embed):
        """Test basic retrieval without filters."""
        
        # Mock embedding
        mock_embed.return_value = [0.1] * 1536
        
        # Mock vector store results
        mock_search.return_value = [
            {
                'id': '1',
                'text': 'Canada student visa requirements...',
                'metadata': {'url': 'https://canada.ca', 'source_type': 'embassy'},
                'score': 0.9
            },
            {
                'id': '2',
                'text': 'Application process for Canada visa...',
                'metadata': {'url': 'https://canada.ca/apply', 'source_type': 'official'},
                'score': 0.8
            }
        ]
        
        results = await retrieval_service.retrieve(
            query="Canada student visa requirements",
            top_k=10
        )
        
        assert len(results) == 2
        assert results[0]['text'] == 'Canada student visa requirements...'
        mock_embed.assert_called_once_with("Canada student visa requirements")
        mock_search.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_retrieve_with_country_filter(self, mock_search, mock_embed):
        """Test retrieval with country filter."""
        
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = []
        
        await retrieval_service.retrieve(
            query="visa requirements",
            country="Canada",
            top_k=5
        )
        
        # Verify filters were passed
        call_args = mock_search.call_args
        assert call_args[1]['filters'] == {'country': 'Canada'}
        # a deeper pool, so merged repeats can be refilled (repeated_chunks.py); the answer still gets top_k
        assert call_args[1]['top_k'] == 5 * 3

    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_retrieve_returns_top_k_from_the_deeper_pool(self, mock_search, mock_embed):
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = [
            {'id': str(i), 'text': f'chunk {i}', 'metadata': {'url': 'https://canada.ca', 'document_id': i},
             'score': 0.9 - i / 100}
            for i in range(12)
        ]
        results = await retrieval_service.retrieve(query="q", country="Canada", top_k=4)
        assert [r['id'] for r in results] == ['0', '1', '2', '3']

    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_merging_repeats_can_be_switched_off(self, mock_search, mock_embed, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "RAG_COLLAPSE_REPEATS", False)
        monkeypatch.setattr(settings, "RAG_LEXICAL_WEIGHT", 0.0)
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = []
        await retrieval_service.retrieve(query="q", country="Canada", top_k=5)
        assert mock_search.call_args[1]['top_k'] == 5

    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_a_rare_word_of_the_question_lifts_its_chunk_into_the_top_k(self, mock_search, mock_embed,
                                                                             monkeypatch):
        """M8.5: "refused" decides the answer; the chunk with it ranked 5th by similarity alone."""
        from app.core.config import settings
        from app.services import lexical
        monkeypatch.setattr(settings, "RAG_COLLAPSE_REPEATS", False)

        async def corpus():
            return 400, {"refus": 12, "campu": 120, "permit": 300, "applic": 250, "job": 90, "happen": 3}

        monkeypatch.setattr(lexical, "corpus_frequencies", corpus)
        mock_embed.return_value = [0.1] * 1536
        common = "Students may work off campus with a study permit while the application is processed."
        mock_search.return_value = [
            {'id': str(i), 'text': f'{common} Section {i}.', 'metadata': {'url': 'https://canada.ca'},
             'score': 0.77 - i / 100} for i in range(4)
        ] + [{'id': 'refused', 'text': 'If we refuse your study permit application, you must stop working and leave.',
              'metadata': {'url': 'https://canada.ca'}, 'score': 0.735}]
        query = "What happens to my off-campus job if my study permit application is refused?"
        monkeypatch.setattr(settings, "RAG_LEXICAL_WEIGHT", 0.0)
        assert 'refused' not in [r['id'] for r in await retrieval_service.retrieve(query=query, top_k=4)]
        monkeypatch.setattr(settings, "RAG_LEXICAL_WEIGHT", 0.04)
        assert 'refused' in [r['id'] for r in await retrieval_service.retrieve(query=query, top_k=4)]

    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_retrieve_with_university_filter(self, mock_search, mock_embed):
        """Test retrieval with university filter."""
        
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = []
        
        await retrieval_service.retrieve(
            query="admission requirements",
            university="UofT",
            top_k=10
        )
        
        call_args = mock_search.call_args
        assert call_args[1]['filters'] == {'university': 'UofT'}


class TestReranking:
    """Test reranking functionality."""
    
    def test_rerank_embassy_boost(self):
        """Test that embassy sources get boosted."""
        
        results = [
            {
                'text': 'News article',
                'metadata': {'source_type': 'news'},
                'score': 0.9
            },
            {
                'text': 'Embassy info',
                'metadata': {'source_type': 'embassy'},
                'score': 0.8
            }
        ]
        
        reranked = retrieval_service._rerank(results, "test query", None)
        
        # Embassy source should be ranked higher despite lower initial score
        assert reranked[0]['metadata']['source_type'] == 'embassy'
        assert reranked[0]['rerank_score'] > reranked[1]['rerank_score']
    
    def test_rerank_official_boost(self):
        """Test that official sources get boosted."""
        
        results = [
            {
                'text': 'Blog post',
                'metadata': {'source_type': 'blog'},
                'score': 0.9
            },
            {
                'text': 'Official document',
                'metadata': {'source_type': 'official'},
                'score': 0.85
            }
        ]
        
        reranked = retrieval_service._rerank(results, "test query", None)
        
        assert reranked[0]['metadata']['source_type'] == 'official'
    
    def test_rerank_recency_boost(self):
        """Test that recent content gets boosted."""
        
        recent_date = datetime.now().isoformat()
        old_date = (datetime.now() - timedelta(days=365)).isoformat()
        
        results = [
            {
                'text': 'Old content',
                'metadata': {'scraped_at': old_date},
                'score': 0.9
            },
            {
                'text': 'Recent content',
                'metadata': {'scraped_at': recent_date},
                'score': 0.85
            }
        ]
        
        reranked = retrieval_service._rerank(results, "test query", None)
        
        # Recent content should be ranked higher
        assert reranked[0]['text'] == 'Recent content'
    
    def test_rerank_country_match_boost(self):
        """Test that country match gets boosted."""
        
        results = [
            {
                'text': 'US visa info',
                'metadata': {'country': 'US'},
                'score': 0.8
            },
            {
                'text': 'Canada visa info',
                'metadata': {'country': 'Canada'},
                'score': 0.85
            }
        ]
        
        reranked = retrieval_service._rerank(results, "test query", country="Canada")
        
        # Canada result should be ranked higher due to country match
        assert reranked[0]['metadata']['country'] == 'Canada'
    
    def test_rerank_combined_boosts(self):
        """Test multiple boost factors combined."""
        
        recent_date = datetime.now().isoformat()
        
        results = [
            {
                'text': 'Generic content',
                'metadata': {'source_type': 'news', 'country': 'US'},
                'score': 1.0
            },
            {
                'text': 'Embassy content',
                'metadata': {
                    'source_type': 'embassy',
                    'country': 'Canada',
                    'scraped_at': recent_date
                },
                'score': 0.7
            }
        ]
        
        reranked = retrieval_service._rerank(results, "test query", country="Canada")
        
        # Embassy + country match + recency should win
        assert reranked[0]['text'] == 'Embassy content'


class TestContextPreparation:
    """Test context preparation functionality."""
    
    def test_prepare_context_basic(self):
        """Test basic context preparation."""
        
        chunks = [
            {
                'text': 'First chunk of information',
                'metadata': {'url': 'https://example.com', 'scraped_at': '2024-01-01'}
            },
            {
                'text': 'Second chunk of information',
                'metadata': {'url': 'https://example.org', 'scraped_at': '2024-01-02'}
            }
        ]
        
        context = retrieval_service.prepare_context(chunks)
        
        assert '[Source 1]' in context
        assert '[Source 2]' in context
        assert 'First chunk' in context
        assert 'Second chunk' in context
        assert 'https://example.com' in context
    
    def test_prepare_context_max_length(self):
        """Test context respects max length."""
        
        chunks = [
            {
                'text': 'A' * 2000,
                'metadata': {'url': 'https://example.com', 'scraped_at': '2024-01-01'}
            },
            {
                'text': 'B' * 2000,
                'metadata': {'url': 'https://example.org', 'scraped_at': '2024-01-02'}
            },
            {
                'text': 'C' * 2000,
                'metadata': {'url': 'https://example.net', 'scraped_at': '2024-01-03'}
            }
        ]
        
        context = retrieval_service.prepare_context(chunks, max_context_length=3000)
        
        # Should not exceed max length
        assert len(context) <= 3000
        # Should include at least first chunk
        assert '[Source 1]' in context
    
    def test_prepare_context_empty_chunks(self):
        """Test context preparation with empty chunks."""
        
        context = retrieval_service.prepare_context([])
        
        assert context == ''
    
    def test_prepare_context_missing_metadata(self):
        """Test context preparation with missing metadata."""
        
        chunks = [
            {
                'text': 'Chunk without metadata',
                'metadata': {}
            }
        ]
        
        context = retrieval_service.prepare_context(chunks)
        
        assert '[Source 1]' in context
        assert 'Chunk without metadata' in context
        assert 'N/A' in context  # For missing URL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
