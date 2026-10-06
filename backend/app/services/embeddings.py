"""
Embedding generation service using Ollama's local embedding models.
Default model: nomic-embed-text (pull with: ollama pull nomic-embed-text)
"""

from typing import List
import asyncio
import httpx

from app.core.config import settings


class EmbeddingService:
    """Generate embeddings using a local Ollama embedding model."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_EMBEDDING_MODEL

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate an embedding vector for a single text.

        Args:
            text: Text to embed (truncated to 8000 chars if too long)

        Returns:
            Embedding vector as list of floats
        """
        if len(text) > 8000:
            text = text[:8000]

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    headers={"Content-Type": "application/json"},
                    json={"model": self.model, "prompt": text},
                )

                if response.status_code != 200:
                    raise Exception(
                        f"Ollama embeddings error ({response.status_code}): {response.text}"
                    )

                data = response.json()
                embedding = data.get("embedding")

                if not embedding:
                    raise Exception(f"Ollama returned empty embedding: {data}")

                return embedding

            except httpx.ConnectError:
                raise Exception(
                    f"Cannot connect to Ollama at {self.base_url}. "
                    "Make sure Ollama is running (`ollama serve`)."
                )
            except httpx.TimeoutException:
                raise Exception("Ollama embedding request timed out.")

    async def generate_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts sequentially.

        Args:
            texts: List of texts to embed
            batch_size: Unused — kept for interface compatibility

        Returns:
            List of embedding vectors
        """
        embeddings = []

        for i, text in enumerate(texts):
            embedding = await self.generate_embedding(text)
            embeddings.append(embedding)

            # Small delay between requests to avoid overwhelming Ollama
            if i < len(texts) - 1:
                await asyncio.sleep(0.05)

        return embeddings


# Global singleton
embedding_service = EmbeddingService()


async def embed_text(text: str) -> List[float]:
    """Convenience function — embed a single text."""
    return await embedding_service.generate_embedding(text)


async def embed_texts_batch(texts: List[str]) -> List[List[float]]:
    """Convenience function — embed multiple texts."""
    return await embedding_service.generate_embeddings_batch(texts)
