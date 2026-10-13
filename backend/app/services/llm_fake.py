"""
Deterministic stand-in for OllamaService, for unit tests of agent and pipeline logic (M0.4).

Responses are scripted per prompt pattern; the first rule whose regex matches the prompt text
(system prompt + context + user prompt) answers. Unmatched prompts raise, so a test never passes
on an accidental default. Every call is recorded in `calls`.

    fake = FakeLLM()
    fake.when(r"decompose", {"sub_questions": ["a", "b"]})      # dict -> JSON / validated model
    fake.when(r"proof of funds", "You need 23,448 CAD [Source 1].")
    fake.when(r"flaky", ["not json", {"ok": True}])               # list = one response per call, in order
    fake.when(r"down", AIServiceUnavailableError("down"))         # exceptions are raised

In tests, use the `fake_llm` fixture (tests/conftest.py), which routes the shared llm_service to it.
"""

import json
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

from app.core.exceptions import LLMStructuredOutputError

T = TypeVar("T", bound=BaseModel)
Response = Union[str, Dict[str, Any], BaseModel, Exception, List[Any]]


class FakeLLM:
    def __init__(self, default: Optional[Response] = None):
        self._rules: List[Dict[str, Any]] = []
        self._default = default
        self.calls: List[Dict[str, Any]] = []

    def when(self, pattern: str, response: Response) -> "FakeLLM":
        """Answer prompts matching `pattern` (case-insensitive regex) with `response`."""
        queue = list(response) if isinstance(response, list) else None
        self._rules.append({"regex": re.compile(pattern, re.IGNORECASE | re.DOTALL), "response": response, "queue": queue})
        return self

    # ------------------------------------------------------------------ matching

    def _respond(self, kind: str, system_prompt: str, user_prompt: str, context: str, extra: Dict[str, Any]) -> Any:
        text = f"{system_prompt}\n{context}\n{user_prompt}"
        self.calls.append({"kind": kind, "system_prompt": system_prompt, "user_prompt": user_prompt,
                           "context": context, **extra})
        for rule in self._rules:
            if rule["regex"].search(text):
                if rule["queue"] is not None:
                    if not rule["queue"]:
                        raise AssertionError(f"FakeLLM: scripted responses for /{rule['regex'].pattern}/ are used up")
                    response = rule["queue"].pop(0)
                else:
                    response = rule["response"]
                break
        else:
            if self._default is None:
                raise AssertionError(f"FakeLLM: no rule matches prompt: {user_prompt[:200]!r}")
            response = self._default
        if isinstance(response, Exception):
            raise response
        return response

    @staticmethod
    def _as_text(response: Any) -> str:
        if isinstance(response, BaseModel):
            return response.model_dump_json()
        if isinstance(response, (dict, list)):
            return json.dumps(response)
        return str(response)

    # ------------------------------------------------------------------ OllamaService interface

    async def generate_answer(self, system_prompt: str, user_prompt: str, context: str = "",
                              chat_history: Optional[List[Dict[str, Any]]] = None, temperature: float = 0.7,
                              max_tokens: int = 2000, role: str = "answer", model: Optional[str] = None, **_: Any) -> str:
        response = self._respond("chat", system_prompt, user_prompt, context,
                                 {"role": role, "model": model, "chat_history": chat_history,
                                  "temperature": temperature, "max_tokens": max_tokens})
        return self._as_text(response)

    async def generate_answer_stream(self, system_prompt: str, user_prompt: str, context: str = "",
                                     chat_history: Optional[List[Dict[str, Any]]] = None, temperature: float = 0.7,
                                     max_tokens: int = 2000, role: str = "answer", model: Optional[str] = None,
                                     **_: Any) -> AsyncGenerator[str, None]:
        response = self._respond("stream", system_prompt, user_prompt, context,
                                 {"role": role, "model": model, "chat_history": chat_history,
                                  "temperature": temperature, "max_tokens": max_tokens})
        words = self._as_text(response).split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

    async def structured_call(self, schema: Type[T], system_prompt: str, user_prompt: str, context: str = "",
                              role: str = "planner", model: Optional[str] = None, max_attempts: int = 2,
                              **_: Any) -> T:
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            response = self._respond("structured", system_prompt, user_prompt, context,
                                     {"role": role, "model": model, "schema": schema.__name__, "attempt": attempt})
            try:
                if isinstance(response, schema):
                    return response
                return schema.model_validate_json(self._as_text(response))
            except ValidationError as e:
                last_error = str(e)
        raise LLMStructuredOutputError(schema.__name__, max_attempts, last_error)

    async def close(self) -> None:
        return None
