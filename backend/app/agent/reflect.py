"""
Reflection (M5.6): after the evidence step, the agent looks at what code's checks said about a part that didn't
verify and chooses what to try next.

    knowledge_base_search   search with other words
    rules                   look the figure up in the official rules
    live_fetch              fetch the current version of a page it was shown
    restate                 ask the evidence step the same thing in clearer words
    finish                  nothing more would help (the sources don't cover it)

The model only chooses the next attempt. Code's checks stay the ground truth: the pipeline runs the attempt through
the same evidence step and keeps it only if it checks out better than the first round (iteration.better). An
unreadable or unusable choice returns None and the pipeline falls back to its own retry (M4.3). At most
AGENT_REFLECT_STEPS choices per answer. Traced as `reflect` (action, valid, problem); never the query or the model's
reasoning.
"""

import logging
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from app.services.tracing import trace_step

logger = logging.getLogger(__name__)

ACTIONS = ("knowledge_base_search", "rules", "live_fetch", "restate", "finish")


class ReflectAction(BaseModel):
    thought: str = Field(default="", max_length=400)
    action: Literal["knowledge_base_search", "rules", "live_fetch", "restate", "finish"]
    query: str = Field(default="", max_length=400)


def key(action: str, query: str) -> str:
    return f"{action}|{' '.join(query.lower().split())}"


def pages_seen(chunks: Iterable[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(title, url) of the pages the passages came from, each once."""
    seen: Dict[str, str] = {}
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        if meta.get("url") and meta["url"] not in seen:
            seen[meta["url"]] = meta.get("title") or "page"
    return [(title, url) for url, title in seen.items()]


def _problem(chosen: ReflectAction, part: str, pages: List[Tuple[str, str]], tried: Iterable[str]) -> str:
    """Why code won't run the model's choice ('' if it will)."""
    query = chosen.query.strip()
    if chosen.action in ("knowledge_base_search", "rules") and len(query) < 3:
        return f"{chosen.action} needs a query"
    if chosen.action == "live_fetch" and query not in {url for _, url in pages}:
        return "live_fetch needs the exact URL of a page shown"
    if chosen.action == "restate" and (len(query) < 8 or " ".join(query.lower().split()) == " ".join(part.lower().split())):
        return "restate needs the question in different words"
    if chosen.action != "finish" and key(chosen.action, query) in set(tried):
        return f"{chosen.action} was already tried with this query"
    return ""


async def choose(part: str, status: str, problems: Iterable[str], pages: List[Tuple[str, str]],
                 tried: Iterable[str], steps_left: int) -> Optional[ReflectAction]:
    """
    The model's choice of what to try next for a part that didn't verify, or None when the choice is unreadable or
    unusable (the caller then uses code's own retry). Model-unavailable errors propagate (M4.7).
    """
    from app.core.exceptions import LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    found = {"not_covered": "the answer step said the sources shown don't cover this",
             "unverified": "an answer was written but its evidence failed the checks",
             "invalid": "the answer step's output was unreadable"}.get(status, status)
    system, user = get_prompt("agent_reflect").render(
        question=part, found=found, problems="\n".join(f"- {p}" for p in problems) or "(none reported)",
        pages="\n".join(f"- {title} <{url}>" for title, url in pages) or "(none)",
        tried="\n".join(f"- {t.replace('|', ': ')}" for t in tried) or "(nothing yet)", steps_left=steps_left)
    with trace_step("reflect") as step:
        try:
            chosen = await llm_service.structured_call(ReflectAction, system, user, role="agent", max_tokens=160)
        except LLMStructuredOutputError:
            step.update(action="unreadable", valid=False)
            return None
        problem = _problem(chosen, part, pages, tried)
        step.update(action=chosen.action, valid=not problem, **({"problem": problem} if problem else {}))
    return None if problem else chosen
