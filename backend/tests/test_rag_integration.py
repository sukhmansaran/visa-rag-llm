"""
Integration tests for RAG pipeline.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.retrieval import retrieval_service
from app.services.llm import llm_service
from app.services.prompts import build_prompt


class TestRAGPipelineIntegration:
    """Test complete RAG pipeline flow."""
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    @patch('app.services.llm.httpx.AsyncClient.post')
    async def test_complete_rag_flow(self, mock_llm_post, mock_search, mock_embed):
        """Test complete RAG flow: query → retrieval → LLM → response."""
        
        # Step 1: Mock embedding
        mock_embed.return_value = [0.1] * 1536
        
        # Step 2: Mock vector search results
        mock_search.return_value = [
            {
                'id': '1',
                'text': 'Canada student visa requires proof of acceptance, financial documents, and English proficiency.',
                'metadata': {
                    'url': 'https://canada.ca/student-visa',
                    'source_type': 'embassy',
                    'scraped_at': '2024-01-15T10:00:00Z'
                },
                'score': 0.95
            },
            {
                'id': '2',
                'text': 'Application fee is CAD 150 and processing takes 2-4 weeks.',
                'metadata': {
                    'url': 'https://canada.ca/visa-fees',
                    'source_type': 'official',
                    'scraped_at': '2024-01-15T10:00:00Z'
                },
                'score': 0.88
            }
        ]
        
        # Step 3: Mock LLM response
        mock_llm_response = Mock()
        mock_llm_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "To apply for a Canada student visa, you need [Source 1] proof of acceptance, financial documents, and English proficiency. The application fee is [Source 2] CAD 150 and processing takes 2-4 weeks."
                }
            }]
        }
        mock_llm_response.raise_for_status = Mock()
        mock_llm_post.return_value = mock_llm_response
        
        # Execute RAG pipeline
        query = "What are Canada student visa requirements?"
        
        # Retrieve context
        chunks = await retrieval_service.retrieve(query=query, country="Canada", top_k=5)
        assert len(chunks) == 2
        assert chunks[0]['metadata']['source_type'] == 'embassy'
        
        # Prepare context
        context = retrieval_service.prepare_context(chunks)
        assert '[Source 1]' in context
        assert '[Source 2]' in context
        assert 'proof of acceptance' in context
        
        # Generate answer
        answer = await llm_service.generate_answer(
            system_prompt="You are a visa advisor",
            user_prompt=query,
            context=context
        )
        
        assert '[Source 1]' in answer
        assert '[Source 2]' in answer
        assert 'proof of acceptance' in answer
        assert 'CAD 150' in answer
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_rag_with_no_results(self, mock_search, mock_embed):
        """Test RAG pipeline when no results are found."""
        
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = []
        
        chunks = await retrieval_service.retrieve(query="Unknown query", top_k=5)
        
        assert len(chunks) == 0
        
        context = retrieval_service.prepare_context(chunks)
        assert context == ''
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_rag_with_filters(self, mock_search, mock_embed):
        """Test RAG pipeline with country and university filters."""
        
        mock_embed.return_value = [0.1] * 1536
        mock_search.return_value = [
            {
                'id': '1',
                'text': 'UofT CS program information',
                'metadata': {'country': 'Canada', 'university': 'UofT'},
                'score': 0.9
            }
        ]
        
        chunks = await retrieval_service.retrieve(
            query="UofT CS admission",
            country="Canada",
            university="UofT",
            top_k=5
        )
        
        assert len(chunks) == 1
        assert chunks[0]['metadata']['university'] == 'UofT'
        
        # Verify filters were passed to vector store
        call_args = mock_search.call_args
        assert call_args[1]['filters'] == {'country': 'Canada', 'university': 'UofT'}


class TestPromptBuilding:
    """Test prompt building for different query types."""
    
    def test_build_visa_prompt(self):
        """Test building visa-specific prompt."""
        
        context = "[Source 1] Canada visa requirements..."
        query = "What are Canada visa requirements?"
        
        prompt = build_prompt(
            query=query,
            context=context,
            query_type="visa"
        )
        
        assert "visa" in prompt.lower()
        assert context in prompt
        assert query in prompt
    
    def test_build_university_prompt(self):
        """Test building university-specific prompt."""
        
        context = "[Source 1] UofT admission requirements..."
        query = "UofT admission requirements?"
        user_profile = {
            "education_level": "bachelor",
            "gpa": 3.8
        }
        
        prompt = build_prompt(
            query=query,
            context=context,
            query_type="university",
            user_profile=user_profile
        )
        
        assert "university" in prompt.lower() or "admission" in prompt.lower()
        assert "3.8" in prompt
    
    def test_build_checklist_prompt(self):
        """Test building checklist prompt."""
        
        context = "[Source 1] Required documents..."
        query = "What documents do I need?"
        
        prompt = build_prompt(
            query=query,
            context=context,
            query_type="checklist",
            application_type="student_visa"
        )
        
        assert "checklist" in prompt.lower() or "document" in prompt.lower()
        assert context in prompt


class TestCitationValidation:
    """Test citation validation in answers."""
    
    def test_count_citations(self):
        """Test counting citations in answer."""
        
        answer = "This is [Source 1] an answer with [Source 2] multiple citations [Source 3]."
        
        citation_count = answer.count("[Source")
        
        assert citation_count == 3
    
    def test_validate_citation_numbers(self):
        """Test that citation numbers are sequential."""
        
        answer = "Answer with [Source 1] and [Source 2] citations."
        
        # Extract citation numbers
        import re
        citations = re.findall(r'\[Source (\d+)\]', answer)
        citation_numbers = [int(c) for c in citations]
        
        assert citation_numbers == [1, 2]
        assert citation_numbers == sorted(citation_numbers)


class TestConfidenceScoring:
    """Test confidence scoring in RAG pipeline."""
    
    @pytest.mark.asyncio
    async def test_confidence_with_citations_and_sources(self):
        """Test confidence calculation with both citations and sources."""
        
        answer = "Answer with [Source 1] and [Source 2] citations."
        sources = [
            {"source_type": "embassy"},
            {"source_type": "official"}
        ]
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer=answer,
            sources=sources
        )
        
        # Should have high confidence
        assert confidence >= 0.8
    
    @pytest.mark.asyncio
    async def test_confidence_without_citations(self):
        """Test confidence calculation without citations."""
        
        answer = "Answer without any citations."
        sources = [{"source_type": "news"}]
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer=answer,
            sources=sources
        )
        
        # Should have lower confidence
        assert confidence <= 0.6


class TestErrorHandling:
    """Test error handling in RAG pipeline."""
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    async def test_embedding_error_handling(self, mock_embed):
        """Test handling of embedding errors."""
        
        mock_embed.side_effect = Exception("Embedding API error")
        
        with pytest.raises(Exception):
            await retrieval_service.retrieve(query="Test query")
    
    @pytest.mark.asyncio
    @patch('app.services.retrieval.embed_text')
    @patch('app.services.retrieval.vector_store.search')
    async def test_vector_search_error_handling(self, mock_search, mock_embed):
        """Test handling of vector search errors."""
        
        mock_embed.return_value = [0.1] * 1536
        mock_search.side_effect = Exception("Vector store error")
        
        with pytest.raises(Exception):
            await retrieval_service.retrieve(query="Test query")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
