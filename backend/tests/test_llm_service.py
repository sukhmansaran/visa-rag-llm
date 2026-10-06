"""
Unit tests for LLM service.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import httpx
from app.services.llm import llm_service, LLMService


class TestLLMService:
    """Test LLM service functionality."""
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_success(self, mock_post):
        """Test successful answer generation."""
        
        # Mock successful API response
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "This is a generated answer with [Source 1] citation."
                    }
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        result = await llm_service.generate_answer(
            system_prompt="You are a helpful assistant",
            user_prompt="What is the capital of Canada?",
            context="Ottawa is the capital of Canada.",
            temperature=0.3,
            max_tokens=1500
        )
        
        assert result == "This is a generated answer with [Source 1] citation."
        mock_post.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_with_context(self, mock_post):
        """Test answer generation with context."""
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Answer with context"}}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System prompt",
            user_prompt="User question",
            context="Retrieved context from vector store"
        )
        
        # Verify context was included in the request
        call_args = mock_post.call_args
        messages = call_args[1]['json']['messages']
        user_message = messages[1]['content']
        
        assert "Retrieved context from vector store" in user_message
        assert "User question" in user_message
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_without_context(self, mock_post):
        """Test answer generation without context."""
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Answer without context"}}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System prompt",
            user_prompt="User question",
            context=""
        )
        
        call_args = mock_post.call_args
        messages = call_args[1]['json']['messages']
        user_message = messages[1]['content']
        
        # Should only contain user prompt
        assert user_message == "User question"
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_custom_temperature(self, mock_post):
        """Test answer generation with custom temperature."""
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Answer"}}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System",
            user_prompt="Question",
            temperature=0.8
        )
        
        call_args = mock_post.call_args
        assert call_args[1]['json']['temperature'] == 0.8
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_custom_max_tokens(self, mock_post):
        """Test answer generation with custom max tokens."""
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Answer"}}]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System",
            user_prompt="Question",
            max_tokens=2000
        )
        
        call_args = mock_post.call_args
        assert call_args[1]['json']['max_tokens'] == 2000
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_http_error(self, mock_post):
        """Test error handling for HTTP errors."""
        
        mock_post.side_effect = httpx.HTTPError("API Error")
        
        with pytest.raises(httpx.HTTPError):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_invalid_response(self, mock_post):
        """Test error handling for invalid response format."""
        
        mock_response = Mock()
        mock_response.json.return_value = {"invalid": "response"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        with pytest.raises(Exception, match="Invalid response format"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_empty_choices(self, mock_post):
        """Test error handling for empty choices."""
        
        mock_response = Mock()
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        with pytest.raises(Exception, match="Invalid response format"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )


class TestConfidenceCalculation:
    """Test confidence score calculation."""
    
    @pytest.mark.asyncio
    async def test_calculate_confidence_base(self):
        """Test base confidence without citations or sources."""
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer="Answer without citations",
            sources=[]
        )
        
        assert confidence == 0.5  # Base confidence
    
    @pytest.mark.asyncio
    async def test_calculate_confidence_with_citations(self):
        """Test confidence boost from citations."""
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer="Answer with [Source 1] and [Source 2] citations",
            sources=[]
        )
        
        # Base (0.5) + citations (0.2)
        assert confidence == 0.7
    
    @pytest.mark.asyncio
    async def test_calculate_confidence_with_many_citations(self):
        """Test confidence cap with many citations."""
        
        answer = "Answer with " + " ".join([f"[Source {i}]" for i in range(1, 10)])
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer=answer,
            sources=[]
        )
        
        # Base (0.5) + max citations (0.3)
        assert confidence == 0.8
    
    @pytest.mark.asyncio
    async def test_calculate_confidence_with_high_quality_sources(self):
        """Test confidence boost from high-quality sources."""
        
        sources = [
            {"source_type": "embassy"},
            {"source_type": "official"},
            {"source_type": "news"}
        ]
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer="Answer without citations",
            sources=sources
        )
        
        # Base (0.5) + high quality sources (0.2)
        assert confidence == 0.7
    
    @pytest.mark.asyncio
    async def test_calculate_confidence_max_score(self):
        """Test confidence caps at 1.0."""
        
        answer = "Answer with " + " ".join([f"[Source {i}]" for i in range(1, 10)])
        sources = [{"source_type": "embassy"} for _ in range(5)]
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer=answer,
            sources=sources
        )
        
        # Should cap at 1.0
        assert confidence == 1.0
    
    @pytest.mark.asyncio
    async def test_calculate_confidence_combined_factors(self):
        """Test confidence with multiple factors."""
        
        sources = [
            {"source_type": "embassy"},
            {"source_type": "official"}
        ]
        
        confidence = await llm_service.calculate_confidence(
            query="Test query",
            answer="Answer with [Source 1] citation",
            sources=sources
        )
        
        # Base (0.5) + citation (0.1) + sources (0.2)
        assert confidence == 0.8


class TestLLMServiceConfiguration:
    """Test LLM service configuration."""
    
    def test_llm_service_initialization(self):
        """Test LLM service initializes with correct config."""
        
        service = LLMService()
        
        assert service.api_key is not None
        assert service.base_url is not None
        assert service.model is not None
    
    @patch('app.services.llm.settings')
    def test_llm_service_uses_config(self, mock_settings):
        """Test LLM service uses settings from config."""
        
        mock_settings.OPENROUTER_API_KEY = "test-key"
        mock_settings.OPENROUTER_BASE_URL = "https://test.api"
        mock_settings.OPENROUTER_MODEL = "test-model"
        
        service = LLMService()
        
        assert service.api_key == "test-key"
        assert service.base_url == "https://test.api"
        assert service.model == "test-model"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
