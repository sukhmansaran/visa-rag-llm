"""
LLM service using Ollama (local inference).
OllamaService is the single LLM provider for chat, SOP generation, and summarization.
Supports both regular and streaming responses.
"""

from typing import AsyncGenerator
import httpx
import json

from app.core.config import settings


class OllamaService:
    """
    LLM service backed by a local Ollama instance.
    Handles chat completion with both streaming and non-streaming modes.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL

    async def generate_answer(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        _retry_count: int = 0,  # kept for interface compatibility
    ) -> str:
        """
        Generate a complete answer via Ollama's /api/chat endpoint.

        Args:
            system_prompt: System instruction
            user_prompt: User query
            context: Optional RAG context to prepend
            temperature: Sampling temperature (0.0–1.0)
            max_tokens: Max tokens to generate

        Returns:
            Generated text response
        """
        messages = [{"role": "system", "content": system_prompt}]

        if context:
            messages.append({
                "role": "user",
                "content": f"Context:\n{context}\n\n{user_prompt}",
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
            },
        }

        print(f"[OLLAMA] Sending request — model: {self.model}, max_tokens: {max_tokens}")

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )

                if response.status_code != 200:
                    raise Exception(
                        f"Ollama error ({response.status_code}): {response.text}"
                    )

                data = response.json()
                content = data.get("message", {}).get("content", "")

                if not content:
                    raise Exception(f"Ollama returned an empty response: {data}")

                print(f"[OLLAMA] ✓ Response generated ({len(content)} chars)")
                return content

            except httpx.ConnectError:
                raise Exception(
                    f"Cannot connect to Ollama at {self.base_url}. "
                    "Make sure Ollama is running (`ollama serve`)."
                )
            except httpx.TimeoutException:
                raise Exception("Ollama request timed out after 180 seconds.")
            except Exception:
                raise

    async def generate_answer_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> AsyncGenerator[str, None]:
        """
        Stream an answer via Ollama's /api/chat endpoint.

        Ollama returns newline-delimited JSON; each line carries a
        message.content field with the next token chunk.

        Yields:
            Text chunks as they are generated
        """
        messages = [{"role": "system", "content": system_prompt}]

        if context:
            messages.append({
                "role": "user",
                "content": f"Context:\n{context}\n\n{user_prompt}",
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
            },
        }

        print(f"[OLLAMA STREAM] Starting stream — model: {self.model}")

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    headers={"Content-Type": "application/json"},
                    json=payload,
                ) as response:

                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise Exception(
                            f"Ollama error ({response.status_code}): {error_text}"
                        )

                    print("[OLLAMA STREAM] Connected, receiving stream...")

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

                    print("[OLLAMA STREAM] Stream completed")

            except httpx.ConnectError:
                raise Exception(
                    f"Cannot connect to Ollama at {self.base_url}. "
                    "Make sure Ollama is running (`ollama serve`)."
                )
            except httpx.TimeoutException:
                raise Exception("Ollama streaming request timed out.")
            except Exception:
                raise

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

# Backward-compat alias — any code that imported gemini_service gets OllamaService
gemini_service = llm_service
