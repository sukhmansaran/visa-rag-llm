"""
LLM service using Ollama (local inference).
OllamaService is the single LLM provider for chat, SOP generation, and summarization.
Supports both regular and streaming responses.
"""

import logging
from typing import AsyncGenerator, Optional, List, Dict, Any
import httpx
import json

from app.core.config import settings
from app.core.loop_local import LoopLocal
from app.core.exceptions import AIServiceUnavailableError

logger = logging.getLogger(__name__)


class OllamaService:
    """
    LLM service backed by a local Ollama instance.
    Handles chat completion with both streaming and non-streaming modes.
    Uses a pooled httpx.AsyncClient with timeouts (A14), one per event loop: a client is bound to
    the loop it was created on, and Celery tasks / tests run on fresh loops.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL
        self._clients: LoopLocal[httpx.AsyncClient] = LoopLocal()

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client for the running event loop."""
        return self._clients.get_or_create(lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=settings.OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS, write=10.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        ))

    async def close(self):
        """Close the running loop's HTTP client (call before that loop shuts down)."""
        client = self._clients.pop()
        if client is not None and not client.is_closed:
            await client.aclose()

    async def generate_answer(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        _retry_count: int = 0,  # kept for interface compatibility
    ) -> str:
        """
        Generate a complete answer via Ollama's /api/chat endpoint with multi-turn history.

        Args:
            system_prompt: System instruction
            user_prompt: User query
            context: Optional RAG context to prepend
            chat_history: Prior conversation turns [{'role': 'user'|'assistant', 'content': '...'}]
            temperature: Sampling temperature (0.0–1.0)
            max_tokens: Max tokens to generate

        Returns:
            Generated text response
        """
        messages = [{"role": "system", "content": system_prompt}]

        # Inject conversation history for multi-turn awareness (last 4 turns)
        if chat_history:
            for turn in chat_history[-4:]:
                role = turn.get("role")
                content = (turn.get("content") or "").strip()
                if role in ["user", "assistant"] and content:
                    if role == "assistant" and len(content) > 500:
                        content = content[:500] + "..."
                    messages.append({"role": role, "content": content})

        if context:
            messages.append({
                "role": "user",
                "content": f"Verified Regulatory Context (Authoritative IRCC Rules):\n{context}\n\n{user_prompt}",
            })
        else:
            messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": settings.OLLAMA_NUM_CTX,
            },
            "think": settings.OLLAMA_THINK,
        }

        logger.info(f"[OLLAMA] Sending request - model: {self.model}, history_turns: {len(chat_history or [])}, max_tokens: {max_tokens}")

        client = self._get_client()
        try:
            # Non-streaming: the whole answer must arrive within the read timeout. On CPU
            # (~7 tokens/s) a 700-token answer takes ~100 s, so this needs a generous limit.
            response = await client.post(
                f"{self.base_url}/api/chat",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=httpx.Timeout(connect=5.0, read=settings.OLLAMA_REQUEST_TIMEOUT_SECONDS, write=10.0, pool=10.0),
            )

            if response.status_code != 200:
                logger.error(f"[OLLAMA] Service returned error {response.status_code}")
                raise AIServiceUnavailableError(
                    message=f"Ollama error ({response.status_code}): Service unavailable. Please retry in a few moments.",
                    details={"status_code": response.status_code},
                )

            data = response.json()
            content = data.get("message", {}).get("content", "")

            if not content:
                raise AIServiceUnavailableError("Ollama returned an empty response.")

            logger.info(f"[OLLAMA] Response generated ({len(content)} chars)")
            return content

        except (httpx.ConnectError, httpx.NetworkError) as e:
            logger.error(f"[OLLAMA] Connection to {self.base_url} failed: {e}")
            raise AIServiceUnavailableError(
                message="The AI inference service is starting or temporarily unavailable. Please retry shortly.",
                details={"reason": "connection_refused"},
            )
        except httpx.TimeoutException as e:
            logger.error(f"[OLLAMA] Request timed out: {e}")
            raise AIServiceUnavailableError(
                message=f"The AI inference service did not finish within {settings.OLLAMA_REQUEST_TIMEOUT_SECONDS:.0f} seconds. Please retry.",
                details={"reason": "timeout"},
            )

    async def generate_answer_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> AsyncGenerator[str, None]:
        """
        Stream an answer via Ollama's /api/chat endpoint with multi-turn history.

        Yields:
            Text chunks as they are generated
        """
        messages = [{"role": "system", "content": system_prompt}]

        # Inject conversation history for multi-turn awareness (last 4 turns)
        if chat_history:
            for turn in chat_history[-4:]:
                role = turn.get("role")
                content = (turn.get("content") or "").strip()
                if role in ["user", "assistant"] and content:
                    if role == "assistant" and len(content) > 500:
                        content = content[:500] + "..."
                    messages.append({"role": role, "content": content})

        if context:
            messages.append({
                "role": "user",
                "content": f"Verified Regulatory Context (Authoritative IRCC Rules):\n{context}\n\n{user_prompt}",
            })
        else:
            messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": settings.OLLAMA_NUM_CTX,
            },
            "think": settings.OLLAMA_THINK,
        }

        logger.info(f"[OLLAMA STREAM] Starting stream - model: {self.model}, history_turns: {len(chat_history or [])}")

        client = self._get_client()
        try:
            # Streaming: read timeout applies between chunks, so long answers are fine
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                headers={"Content-Type": "application/json"},
                json=payload,
            ) as response:

                if response.status_code != 200:
                    logger.error(f"[OLLAMA STREAM] Error {response.status_code}")
                    raise AIServiceUnavailableError(f"Ollama error ({response.status_code}): Streaming service temporarily unavailable.")

                logger.info("[OLLAMA STREAM] Connected, receiving stream...")

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        continue

                logger.info("[OLLAMA STREAM] Stream completed")

        except (httpx.ConnectError, httpx.NetworkError) as e:
            logger.error(f"[OLLAMA STREAM] Connection to {self.base_url} failed: {e}")
            raise AIServiceUnavailableError(
                message="The AI inference service is starting or temporarily unavailable. Please retry shortly.",
                details={"reason": "connection_refused"},
            )
        except httpx.TimeoutException as e:
            logger.error(f"[OLLAMA STREAM] Stream timed out: {e}")
            raise AIServiceUnavailableError(
                message="Ollama request timed out during streaming.",
                details={"reason": "timeout"},
            )

    async def factual_summarize(self, text: str) -> str:
        """
        Fact-dense bullet-point summary used at ingestion time to compress chunks.
        """
        system_prompt = (
            "You are a factual summarization engine. Your only goal is to extract "
            "hard facts, requirements, and policies from the provided text.\n\n"
            "STRICT RULES:\n"
            "- Output ONLY bullet points.\n"
            "- NO prose, NO intro, NO conclusion, NO conversational text.\n"
            "- NO interpretation, NO examples.\n"
            "- Extremely concise, dense facts.\n"
            "- Maximum 150 words total output."
        )
        return await self.generate_answer(
            system_prompt=system_prompt,
            user_prompt=f"Extract facts from this text:\n\n{text}",
            temperature=0.0,
            max_tokens=300,
        )


# Global singleton
llm_service = OllamaService()

# Backward-compat alias — any code that imported gemini_service or LLMService gets OllamaService
gemini_service = llm_service
LLMService = OllamaService

