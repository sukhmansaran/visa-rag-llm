"""
LLM gateway using Ollama (local inference).

OllamaService is the single LLM provider (chat answers, SOP generation, crawler structuring) and the one
place every model call goes through (M0.4):
- per-role models (planner / answer / verifier, falling back to OLLAMA_MODEL);
- structured_call(): JSON-schema-constrained output validated with Pydantic, one corrective retry;
- call accounting: tokens and Ollama's own timings per call, collected per request via record_llm_calls();
- a concurrency limit with queueing (a CPU serves one generation at a time well).
"""

import asyncio
import contextvars
import json
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass
from typing import Any, AsyncGenerator, Dict, Iterator, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.exceptions import AIServiceUnavailableError, LLMStructuredOutputError
from app.core.loop_local import LoopLocal

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

ROLES = ("planner", "answer", "verifier")
_NS = 1_000_000_000


@dataclass
class LLMCallStats:
    """Accounting for one model call. Durations are Ollama's own measurements, in seconds."""

    role: str
    model: str
    mode: str                          # "chat" | "stream" | "structured"
    ok: bool = True
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    load_s: Optional[float] = None     # loading the model into memory (0 when already loaded)
    prompt_s: Optional[float] = None   # reading the prompt
    generation_s: Optional[float] = None
    total_s: Optional[float] = None
    queue_wait_s: float = 0.0          # waiting for a free slot before the call started
    wall_s: float = 0.0                # client-side time including the HTTP round trip
    attempts: int = 1

    @property
    def tokens_per_second(self) -> Optional[float]:
        if self.output_tokens and self.generation_s:
            return round(self.output_tokens / self.generation_s, 2)
        return None

    def as_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "tokens_per_second": self.tokens_per_second}

    def absorb_ollama_timings(self, data: Dict[str, Any]) -> None:
        """Copy token counts and durations from Ollama's final response object."""
        def seconds(key: str) -> Optional[float]:
            value = data.get(key)
            return round(value / _NS, 3) if isinstance(value, (int, float)) else None

        if isinstance(data.get("prompt_eval_count"), int):
            self.prompt_tokens = data["prompt_eval_count"]
        if isinstance(data.get("eval_count"), int):
            self.output_tokens = data["eval_count"]
        self.load_s = seconds("load_duration")
        self.prompt_s = seconds("prompt_eval_duration")
        self.generation_s = seconds("eval_duration")
        self.total_s = seconds("total_duration")


_call_log: contextvars.ContextVar[Optional[List[LLMCallStats]]] = contextvars.ContextVar("llm_call_log", default=None)


@contextmanager
def record_llm_calls() -> Iterator[List[LLMCallStats]]:
    """Collect the stats of every model call made inside this block (on this task / request)."""
    calls: List[LLMCallStats] = []
    token = _call_log.set(calls)
    try:
        yield calls
    finally:
        _call_log.reset(token)


class OllamaService:
    """
    LLM gateway backed by a local Ollama instance.
    Uses a pooled httpx.AsyncClient with timeouts (A14), one per event loop: a client is bound to
    the loop it was created on, and Celery tasks / tests run on fresh loops. The call queue
    (semaphore) is per event loop for the same reason.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL
        self._clients: LoopLocal[httpx.AsyncClient] = LoopLocal()
        self._slots: LoopLocal[asyncio.Semaphore] = LoopLocal()

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

    # ------------------------------------------------------------------ routing & queueing

    def model_for(self, role: str) -> str:
        """Model for a role: its LLM_MODEL_<ROLE> setting if set, otherwise the default model."""
        configured = {
            "planner": settings.LLM_MODEL_PLANNER,
            "answer": settings.LLM_MODEL_ANSWER,
            "verifier": settings.LLM_MODEL_VERIFIER,
        }.get(role)
        return configured or self.model

    @asynccontextmanager
    async def _slot(self, stats: LLMCallStats):
        """Wait for a free generation slot (FIFO), recording the wait."""
        semaphore = self._slots.get_or_create(lambda: asyncio.Semaphore(max(1, settings.LLM_MAX_CONCURRENT_CALLS)))
        started = time.perf_counter()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=settings.LLM_QUEUE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            stats.queue_wait_s = round(time.perf_counter() - started, 3)
            raise AIServiceUnavailableError(
                message="The AI service is busy with other requests. Please retry shortly.",
                details={"reason": "queue_timeout"},
            )
        stats.queue_wait_s = round(time.perf_counter() - started, 3)
        try:
            yield
        finally:
            semaphore.release()

    @staticmethod
    def _record(stats: LLMCallStats, started: float) -> None:
        stats.wall_s = round(time.perf_counter() - started, 3)
        calls = _call_log.get()
        if calls is not None:
            calls.append(stats)
        logger.info(
            f"[OLLAMA] role={stats.role} model={stats.model} mode={stats.mode} ok={stats.ok} "
            f"prompt_tokens={stats.prompt_tokens} output_tokens={stats.output_tokens} "
            f"prompt_s={stats.prompt_s} generation_s={stats.generation_s} tok/s={stats.tokens_per_second} "
            f"queue_wait_s={stats.queue_wait_s} wall_s={stats.wall_s} attempts={stats.attempts}"
            + (f" error={stats.error}" if stats.error else "")
        )

    # ------------------------------------------------------------------ request building

    @staticmethod
    def _build_messages(
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
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
        return messages

    @staticmethod
    def _payload(
        model: str,
        messages: List[Dict[str, str]],
        stream: bool,
        temperature: float,
        max_tokens: int,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": settings.OLLAMA_NUM_CTX,
            },
            "think": settings.OLLAMA_THINK,
        }
        if json_schema is not None:
            payload["format"] = json_schema
        return payload

    # ------------------------------------------------------------------ calls

    async def _chat_once(self, payload: Dict[str, Any], stats: LLMCallStats) -> str:
        """One non-streaming /api/chat call: queue, post, account. Returns the message content."""
        started = time.perf_counter()
        try:
            async with self._slot(stats):
                client = self._get_client()
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
                if isinstance(data, dict):
                    stats.absorb_ollama_timings(data)
                content = data.get("message", {}).get("content", "")

                if not content:
                    raise AIServiceUnavailableError("Ollama returned an empty response.")
                return content

        except (httpx.ConnectError, httpx.NetworkError) as e:
            stats.ok, stats.error = False, "connection_refused"
            logger.error(f"[OLLAMA] Connection to {self.base_url} failed: {e}")
            raise AIServiceUnavailableError(
                message="The AI inference service is starting or temporarily unavailable. Please retry shortly.",
                details={"reason": "connection_refused"},
            )
        except httpx.TimeoutException as e:
            stats.ok, stats.error = False, "timeout"
            logger.error(f"[OLLAMA] Request timed out: {e}")
            raise AIServiceUnavailableError(
                message=f"The AI inference service did not finish within {settings.OLLAMA_REQUEST_TIMEOUT_SECONDS:.0f} seconds. Please retry.",
                details={"reason": "timeout"},
            )
        except AIServiceUnavailableError as e:
            stats.ok, stats.error = False, e.details.get("reason") or str(e.details.get("status_code") or "unavailable")
            raise
        finally:
            self._record(stats, started)

    async def generate_answer(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        _retry_count: int = 0,  # kept for interface compatibility
        role: str = "answer",
        model: Optional[str] = None,
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
            role: Accounting / routing role ("planner", "answer", "verifier", or a free label)
            model: Explicit model; overrides the role's configured model

        Returns:
            Generated text response
        """
        model = model or self.model_for(role)
        messages = self._build_messages(system_prompt, user_prompt, context, chat_history)
        payload = self._payload(model, messages, stream=False, temperature=temperature, max_tokens=max_tokens)

        logger.info(f"[OLLAMA] Sending request - model: {model}, history_turns: {len(chat_history or [])}, max_tokens: {max_tokens}")
        content = await self._chat_once(payload, LLMCallStats(role=role, model=model, mode="chat"))
        logger.info(f"[OLLAMA] Response generated ({len(content)} chars)")
        return content

    async def generate_answer_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        chat_history: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        role: str = "answer",
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream an answer via Ollama's /api/chat endpoint with multi-turn history.
        The generation slot is held until the stream ends or the consumer stops reading.

        Yields:
            Text chunks as they are generated
        """
        model = model or self.model_for(role)
        messages = self._build_messages(system_prompt, user_prompt, context, chat_history)
        payload = self._payload(model, messages, stream=True, temperature=temperature, max_tokens=max_tokens)
        stats = LLMCallStats(role=role, model=model, mode="stream")

        logger.info(f"[OLLAMA STREAM] Starting stream - model: {model}, history_turns: {len(chat_history or [])}")

        started = time.perf_counter()
        completed = False
        try:
            async with self._slot(stats):
                client = self._get_client()
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
                        except json.JSONDecodeError:
                            continue
                        if data.get("done"):
                            stats.absorb_ollama_timings(data)
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk

                    completed = True
                    logger.info("[OLLAMA STREAM] Stream completed")

        except (httpx.ConnectError, httpx.NetworkError) as e:
            stats.ok, stats.error = False, "connection_refused"
            logger.error(f"[OLLAMA STREAM] Connection to {self.base_url} failed: {e}")
            raise AIServiceUnavailableError(
                message="The AI inference service is starting or temporarily unavailable. Please retry shortly.",
                details={"reason": "connection_refused"},
            )
        except httpx.TimeoutException as e:
            stats.ok, stats.error = False, "timeout"
            logger.error(f"[OLLAMA STREAM] Stream timed out: {e}")
            raise AIServiceUnavailableError(
                message="Ollama request timed out during streaming.",
                details={"reason": "timeout"},
            )
        except AIServiceUnavailableError as e:
            stats.ok, stats.error = False, e.details.get("reason") or "unavailable"
            raise
        finally:
            if stats.ok and not completed:
                stats.ok, stats.error = False, "stopped_by_consumer"
            self._record(stats, started)

    async def structured_call(
        self,
        schema: Type[T],
        system_prompt: str,
        user_prompt: str,
        context: str = "",
        role: str = "planner",
        model: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.0,
        max_attempts: int = 2,
    ) -> T:
        """
        Ask for JSON matching `schema` (Ollama `format` = the model's JSON schema) and validate it.

        If the reply does not validate, the model is shown the validation error once and asked again.
        Raises LLMStructuredOutputError when every attempt fails; AIServiceUnavailableError propagates.
        """
        model = model or self.model_for(role)
        messages = self._build_messages(system_prompt, user_prompt, context)
        json_schema = schema.model_json_schema()
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            stats = LLMCallStats(role=role, model=model, mode="structured", attempts=attempt)
            payload = self._payload(model, messages, stream=False, temperature=temperature,
                                    max_tokens=max_tokens, json_schema=json_schema)
            raw = await self._chat_once(payload, stats)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_error = str(e)
                stats.ok, stats.error = False, "schema_validation"
                logger.warning(f"[OLLAMA] {schema.__name__} attempt {attempt} failed validation: {last_error[:300]}")
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"Your reply did not match the required JSON schema. Error: {last_error[:500]}\n"
                        "Reply again with only a JSON object that matches the schema."
                    )},
                ]

        raise LLMStructuredOutputError(schema.__name__, max_attempts, last_error)

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
            role="ingestion",
        )


# Global singleton
llm_service = OllamaService()
