"""
Unit tests for the Ollama-backed EmbeddingService.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestEmbeddingService:
    """Test Ollama embedding service functionality."""

    @pytest.mark.asyncio
    @patch("app.services.embeddings.httpx.AsyncClient")
    async def test_generate_embedding_success(self, mock_client_cls):
        """Test successful single embedding generation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1] * 768}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.embeddings import EmbeddingService
        service = EmbeddingService()
        result = await service.generate_embedding("test text")

        assert isinstance(result, list)
        assert len(result) == 768
        assert result[0] == 0.1

    @pytest.mark.asyncio
    @patch("app.services.embeddings.httpx.AsyncClient")
    async def test_generate_embedding_truncates_long_text(self, mock_client_cls):
        """Test that text longer than 8000 chars is truncated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1] * 768}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.embeddings import EmbeddingService
        service = EmbeddingService()
        long_text = "a" * 10000
        await service.generate_embedding(long_text)

        call_args = mock_client.post.call_args
        sent_text = call_args.kwargs["json"]["prompt"]
        assert len(sent_text) == 8000

    @pytest.mark.asyncio
    @patch("app.services.embeddings.httpx.AsyncClient")
    async def test_generate_embeddings_batch_success(self, mock_client_cls):
        """Test successful batch embedding generation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1] * 768}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.embeddings import EmbeddingService
        service = EmbeddingService()
        texts = ["text one", "text two", "text three"]
        results = await service.generate_embeddings_batch(texts)

        assert len(results) == 3
        assert all(len(r) == 768 for r in results)

    @pytest.mark.asyncio
    @patch("app.services.embeddings.httpx.AsyncClient")
    async def test_generate_embedding_empty_response(self, mock_client_cls):
        """Test that empty embedding raises an exception."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}  # No embedding key

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.embeddings import EmbeddingService
        service = EmbeddingService()

        with pytest.raises(Exception, match="empty embedding"):
            await service.generate_embedding("test")

    @pytest.mark.asyncio
    @patch("app.services.embeddings.httpx.AsyncClient")
    async def test_generate_embedding_api_error(self, mock_client_cls):
        """Test that non-200 status raises an exception."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.embeddings import EmbeddingService
        service = EmbeddingService()

        with pytest.raises(Exception, match="Ollama embeddings error"):
            await service.generate_embedding("test")

    def test_embedding_service_uses_config(self):
        """Test that EmbeddingService reads from settings."""
        from app.services.embeddings import EmbeddingService
        service = EmbeddingService()
        from app.core.config import settings
        assert service.base_url == settings.OLLAMA_BASE_URL.rstrip("/")
        assert service.model == settings.OLLAMA_EMBEDDING_MODEL
