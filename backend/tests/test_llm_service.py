"""
Unit tests for LLM service (OllamaService) and algorithmic confidence scoring.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import httpx
from app.services.llm import llm_service, LLMService, OllamaService
from app.services.rag_pipeline import RAGPipeline


class TestLLMService:
    """Test Ollama LLM service functionality."""
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_success(self, mock_post):
        """Test successful answer generation via Ollama /api/chat."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "content": "This is a generated answer with [Source 1] citation."
            }
        }
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
        call_args = mock_post.call_args
        assert call_args[1]['json']['options']['temperature'] == 0.3
        assert call_args[1]['json']['options']['num_predict'] == 1500
        assert call_args[1]['json']['stream'] is False
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_with_context(self, mock_post):
        """Test answer generation with regulatory context formatting."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Answer with context"}
        }
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System prompt",
            user_prompt="User question",
            context="Retrieved context from vector store"
        )
        
        # Verify regulatory context wrapping
        call_args = mock_post.call_args
        messages = call_args[1]['json']['messages']
        user_message = messages[-1]['content']
        
        assert "Verified Regulatory Context (Authoritative IRCC Rules):" in user_message
        assert "Retrieved context from vector store" in user_message
        assert "User question" in user_message
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_without_context(self, mock_post):
        """Test answer generation without context."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Answer without context"}
        }
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System prompt",
            user_prompt="User question",
            context=""
        )
        
        call_args = mock_post.call_args
        messages = call_args[1]['json']['messages']
        user_message = messages[-1]['content']
        
        # Should only contain user prompt without wrapper
        assert user_message == "User question"
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_custom_temperature(self, mock_post):
        """Test answer generation with custom temperature."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Answer"}
        }
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System",
            user_prompt="Question",
            temperature=0.8
        )
        
        call_args = mock_post.call_args
        assert call_args[1]['json']['options']['temperature'] == 0.8
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_custom_max_tokens(self, mock_post):
        """Test answer generation with custom max tokens (num_predict)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Answer"}
        }
        mock_post.return_value = mock_response
        
        await llm_service.generate_answer(
            system_prompt="System",
            user_prompt="Question",
            max_tokens=2000
        )
        
        call_args = mock_post.call_args
        assert call_args[1]['json']['options']['num_predict'] == 2000
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_http_error(self, mock_post):
        """Test error handling when Ollama returns non-200 status code."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Model Error"
        mock_post.return_value = mock_response
        
        with pytest.raises(Exception, match=r"Ollama error \(500\)"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_connection_error(self, mock_post):
        """Test error handling when Ollama daemon is unreachable."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")
        
        with pytest.raises(Exception, match="Cannot connect to Ollama"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_timeout_error(self, mock_post):
        """Test error handling when Ollama request times out."""
        mock_post.side_effect = httpx.TimeoutException("Timed out")
        
        with pytest.raises(Exception, match="Ollama request timed out"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_invalid_response(self, mock_post):
        """Test error handling for empty / malformed response payload."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"invalid": "response"}
        mock_post.return_value = mock_response
        
        with pytest.raises(Exception, match="Ollama returned an empty response"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )
    
    @pytest.mark.asyncio
    @patch('httpx.AsyncClient.post')
    async def test_generate_answer_empty_content(self, mock_post):
        """Test error handling for empty string content in message."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": ""}}
        mock_post.return_value = mock_response
        
        with pytest.raises(Exception, match="Ollama returned an empty response"):
            await llm_service.generate_answer(
                system_prompt="System",
                user_prompt="Question"
            )


class TestConfidenceCalculation:
    """
    Test algorithmic confidence score calculation in RAGPipeline.
    Confidence formula: similarity * 0.4 + authority * 0.4 + freshness * 0.2.
    """
    
    def test_calculate_confidence_base_insufficient(self):
        """Test confidence when no chunks and no tourist db are present."""
        result = RAGPipeline.calculate_algorithmic_confidence(
            chunks=[],
            has_tourist_db=False,
        )
        assert result["score"] == 0.0
        assert result["level"] == "INSUFFICIENT"
    
    def test_calculate_confidence_with_tourist_db(self):
        """Test confidence boost from official tourist DB."""
        result = RAGPipeline.calculate_algorithmic_confidence(
            chunks=[],
            has_tourist_db=True,
        )
        # similarity 0.85*0.4 (0.34) + authority 0.95*0.4 (0.38) + freshness 1.0*0.2 (0.2) = 0.92
        assert result["score"] >= 0.75
        assert result["level"] == "HIGH"
    
    def test_calculate_confidence_with_tier1_sources(self):
        """Test confidence calculation with official Tier-1 IRCC sources."""
        chunks = [
            {
                "score": 0.85,
                "authority_tier": 1,
                "freshness_weight": 0.9,
            }
        ]
        result = RAGPipeline.calculate_algorithmic_confidence(chunks)
        # similarity 0.85*0.4 + authority 1.0*0.4 + freshness 0.9*0.2 = 0.34 + 0.40 + 0.18 = 0.92
        assert result["score"] >= 0.75
        assert result["level"] == "HIGH"
    
    def test_calculate_confidence_with_low_quality_sources(self):
        """Test confidence calculation with low-tier / low-similarity sources."""
        chunks = [
            {
                "score": 0.30,
                "authority_tier": 4,  # tier 4 weight 0.3
                "freshness_weight": 0.4,
            }
        ]
        result = RAGPipeline.calculate_algorithmic_confidence(chunks)
        # similarity 0.30*0.4 (0.12) + authority 0.3*0.4 (0.12) + freshness 0.4*0.2 (0.08) = 0.32
        assert result["score"] < 0.35
        assert result["level"] == "INSUFFICIENT"
    
    def test_calculate_confidence_max_score(self):
        """Test that confidence score properly reflects upper boundary."""
        chunks = [
            {
                "score": 1.0,
                "authority_tier": 1,
                "freshness_weight": 1.0,
            }
        ]
        result = RAGPipeline.calculate_algorithmic_confidence(chunks)
        assert result["score"] == 1.0
        assert result["level"] == "HIGH"
    
    def test_calculate_confidence_combined_factors(self):
        """Test exact calculation of combined multi-factor weighting."""
        chunks = [
            {
                "score": 0.75,
                "authority_tier": 2,  # tier 2 weight 0.8
                "freshness_weight": 0.8,
            }
        ]
        result = RAGPipeline.calculate_algorithmic_confidence(chunks)
        # 0.75 * 0.4 + 0.8 * 0.4 + 0.8 * 0.2 = 0.30 + 0.32 + 0.16 = 0.78
        assert result["score"] == 0.78
        assert result["level"] == "HIGH"


class TestLLMServiceConfiguration:
    """Test LLM service configuration."""
    
    def test_llm_service_initialization(self):
        """Test Ollama service initializes with correct config fields."""
        service = OllamaService()
        
        assert service.base_url is not None
        assert service.model is not None
        assert service.base_url.startswith("http")
    
    @patch('app.services.llm.settings')
    def test_llm_service_uses_config(self, mock_settings):
        """Test Ollama service uses settings from config."""
        mock_settings.OLLAMA_BASE_URL = "http://custom-ollama:11434"
        mock_settings.OLLAMA_MODEL = "llama3.2:3b"
        
        service = OllamaService()
        
        assert service.base_url == "http://custom-ollama:11434"
        assert service.model == "llama3.2:3b"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
