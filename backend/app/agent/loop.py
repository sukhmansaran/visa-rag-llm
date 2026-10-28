"""
Agent loop (M5.3), a LangGraph graph on the verified path (behind AGENT_LOOP):

    decide --(tool)--> act --> decide ... --(answer | ask_user | limit)--> end
       \\--(two invalid actions in a row)--> fallback (the M5.2 router's plan) --> end

The model makes the recoverable decisions: which action next, what to look up, whether to ask the user, when to answer
and how to restate the question with the asker's details. Code makes the rest: every action is checked (known action,
a usable query, not a repeat; tool arguments through app/services/tools.py), the steps are limited, and the answer is
not written here: the pipeline answers the chosen question from the gathered evidence with the M3/M4 evidence step and
its code checks, unchanged. A bad choice costs a step, never an unchecked answer.

The agent starts from what the pipeline already found (rule facts, the first search), so a simple question is
answered after one decision. Traced per step (`agent_step`: number, action, valid, what was found); never the query or
the model's reasoning, which can echo the user's words.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import tools
from app.services.tracing import trace_step

logger = logging.getLogger(__name__)

TOOL_ACTIONS = ("rules", "knowledge_base_search", "profile", "processing_times_link")
MAX_INVALID_IN_A_ROW = 2
_SUMMARY_CHARS = 420


class AgentAction(BaseModel):
    thought: str = Field(default="", max_length=400)
    action: Literal["rules", "knowledge_base_search", "profile", "processing_times_link", "ask_user", "answer"]
    query: str = Field(default="", max_length=400)


class AgentState(TypedDict, total=False):
    question: str
    conversation: str
    rule_facts: List[str]       # distinct rule-fact blocks found
    chunks: List[Dict[str, Any]]
    profile: Optional[Dict[str, Any]]
    observations: List[str]     # what the model sees, one line per result
    tried: List[str]            # "action|query" already done
    steps: int
    invalid_in_row: int
    pending: Optional[Dict[str, str]]
    outcome: str                # answer | ask | limit | fallback
    answer_question: str
    ask: str
    trail: List[Dict[str, Any]]


@dataclass
class AgentResult:
    outcome: str                         # answer | ask | limit | fallback
    answer_question: str                 # the question the evidence step answers (restated by the agent)
    ask: str = ""                        # the clarifying question, when outcome == "ask"
    rule_facts: Optional[str] = None
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    trail: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        actions = [t["action"] for t in self.trail]
        return {"outcome": self.outcome, "steps": len(self.trail), "actions": actions,
                "invalid": sum(not t["valid"] for t in self.trail)}


# ---------------------------------------------------------------- what the model sees

def _facts_line(query: str, facts: Optional[str]) -> str:
    if not facts:
        return f"rules ({query}): nothing in the rules file for this."
    lines = [line.strip() for line in facts.splitlines() if line.strip() and not line.strip().startswith("- Source")]
    return f"rules ({query}): " + " | ".join(lines)[:_SUMMARY_CHARS]


def _search_line(query: str, chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return f"search ({query}): no passages found."
    parts = []
    for c in chunks[:4]:
        meta = c.get("metadata") or {}
        title = meta.get("title") or c.get("title") or "page"
        parts.append(f"{title}: {' '.join((c.get('text') or '').split())[:110]}")
    return f"search ({query}): {len(chunks)} passages: " + " || ".join(parts)


def _profile_line(profile: Dict[str, Any]) -> str:
    if not profile.get("found"):
        return "profile: no saved profile."
    shown = {k: v for k, v in profile.items() if k != "found" and v not in (None, "", {}, [])}
    return "profile: " + json.dumps(shown, ensure_ascii=False)[:_SUMMARY_CHARS]


def _key(action: str, query: str) -> str:
    return f"{action}|{' '.join(query.lower().split())}"


# ---------------------------------------------------------------- nodes

async def _decide(state: AgentState) -> AgentState:
    from app.core.exceptions import LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    steps = state.get("steps", 0)
    if steps >= settings.AGENT_MAX_STEPS:
        return {"outcome": "limit", "answer_question": state["question"], "pending": None}
    system, user = get_prompt("agent_decide").render(
        question=state["question"], conversation=state.get("conversation") or "(none)",
        known="\n".join(state.get("observations") or []) or "(nothing yet)",
        steps_left=settings.AGENT_MAX_STEPS - steps)
    trail = list(state.get("trail") or [])
    try:
        chosen = await llm_service.structured_call(AgentAction, system, user, role="agent", max_tokens=160)
        problem = _problem(chosen, state)
    except LLMStructuredOutputError:
        chosen, problem = None, "unreadable"
    if problem:
        invalid = state.get("invalid_in_row", 0) + 1
        trail.append({"n": steps + 1, "action": chosen.action if chosen else "unreadable", "valid": False,
                      "problem": problem})
        with trace_step("agent_step", **trail[-1]):
            pass
        observations = list(state.get("observations") or [])
        observations.append(f"(your last choice was not used: {problem})")
        return {"steps": steps + 1, "invalid_in_row": invalid, "trail": trail, "observations": observations,
                "pending": None, "outcome": "fallback" if invalid >= MAX_INVALID_IN_A_ROW else ""}
    update: AgentState = {"steps": steps + 1, "invalid_in_row": 0, "trail": trail,
                          "pending": {"action": chosen.action, "query": chosen.query.strip()}}
    if chosen.action == "answer":
        update.update(outcome="answer", answer_question=chosen.query.strip() or state["question"], pending=None)
        trail.append({"n": steps + 1, "action": "answer", "valid": True})
        with trace_step("agent_step", **trail[-1]):
            pass
    elif chosen.action == "ask_user":
        update.update(outcome="ask", ask=chosen.query.strip(), pending=None)
        trail.append({"n": steps + 1, "action": "ask_user", "valid": True})
        with trace_step("agent_step", **trail[-1]):
            pass
    return update


def _problem(chosen: AgentAction, state: AgentState) -> str:
    """Why code won't run the model's choice ('' if it will)."""
    query = chosen.query.strip()
    if chosen.action in ("rules", "knowledge_base_search") and len(query) < 3:
        return f"{chosen.action} needs a query"
    if chosen.action == "ask_user":
        if len(query) < 8:
            return "ask_user needs the question to ask"
        if state.get("conversation") and "assistant:" in state["conversation"].lower():
            return "the asker has already been asked once; answer with what is known"
    if chosen.action in TOOL_ACTIONS and _key(chosen.action, query) in (state.get("tried") or []):
        return (f"{chosen.action} was already done with this query and its result is above; if the answer depends on "
                "something the asker did not say, choose ask_user, otherwise choose answer")
    return ""


async def _act(state: AgentState) -> AgentState:
    pending = state["pending"]
    action, query = pending["action"], pending["query"]
    args = {"rules": {"question": query}, "knowledge_base_search": {"query": query}}.get(action, {})
    observations = list(state.get("observations") or [])
    rule_facts = list(state.get("rule_facts") or [])
    chunks = list(state.get("chunks") or [])
    profile = state.get("profile")
    found = 0
    try:
        result = await tools.call(action, args)
        valid = True
    except tools.ToolError as e:  # arguments refused or tool unavailable: the model sees why and chooses again
        result, valid = None, False
        observations.append(f"({action} could not run: {e})")
    if result is not None:
        if action == "rules":
            blocks = [b for b in (result.facts, result.guarantee_fact, result.closed_program_fact) if b]
            for block in blocks:
                if block not in rule_facts:
                    rule_facts.append(block)
            found = len(blocks)
            observations.append(_facts_line(query, "\n".join(blocks) or None))
        elif action == "knowledge_base_search":
            known = {(c.get("metadata") or {}).get("url", "") + (c.get("text") or "") for c in chunks}
            new = [{"text": c.text, "score": c.score, "authority_tier": c.authority_tier,
                    "metadata": {"url": c.url, "title": c.title}} for c in result.chunks]
            new = [c for c in new if c["metadata"]["url"] + c["text"] not in known]
            chunks += new
            found = len(new)
            observations.append(_search_line(query, new))
        elif action == "profile":
            profile = result.model_dump()
            found = int(bool(profile.get("found")))
            observations.append(_profile_line(profile))
        elif action == "processing_times_link":
            block = (f"OFFICIAL IRCC PROCESSING TIMES: Pendu stores no processing-time figures. {result.note} "
                     f"Check the current time with IRCC's tool: {result.url}")
            if block not in rule_facts:
                rule_facts.append(block)
            found = 1
            observations.append(f"processing times: check {result.url} (no figures are stored)")
    trail = list(state.get("trail") or [])
    trail.append({"n": state.get("steps", 0), "action": action, "valid": valid, "found": found})
    with trace_step("agent_step", **trail[-1]):
        pass
    return {"observations": observations, "rule_facts": rule_facts, "chunks": chunks, "profile": profile,
            "tried": list(state.get("tried") or []) + [_key(action, query)], "trail": trail, "pending": None}


async def _fallback(state: AgentState) -> AgentState:
    """Two unusable choices in a row: the M5.2 router's tools, then the original question."""
    from app.services.router import route

    plan = await route(state["question"])
    update: AgentState = {"outcome": "fallback", "answer_question": state["question"]}
    merged = dict(state)
    for action in plan.tools:
        if action == "rules" and state.get("rule_facts"):
            continue
        merged["pending"] = {"action": action, "query": state["question"]}
        merged.update(await _act(merged))
    for key in ("rule_facts", "chunks", "profile", "observations", "trail"):
        update[key] = merged.get(key)
    return update


def _after_decide(state: AgentState) -> str:
    if state.get("outcome") in ("answer", "ask", "limit"):
        return "end"
    if state.get("outcome") == "fallback":
        return "fallback"
    return "act" if state.get("pending") else "decide"


_graph = None


def graph():
    global _graph
    if _graph is None:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(AgentState)
        builder.add_node("decide", _decide)
        builder.add_node("act", _act)
        builder.add_node("fallback", _fallback)
        builder.add_edge(START, "decide")
        builder.add_conditional_edges("decide", _after_decide,
                                      {"act": "act", "decide": "decide", "fallback": "fallback", "end": END})
        builder.add_edge("act", "decide")
        builder.add_edge("fallback", END)
        _graph = builder.compile()
    return _graph


def _conversation(chat_history: Optional[List[Dict[str, Any]]]) -> str:
    """The last exchange, so a reply to the agent's own question is understood."""
    turns = [m for m in (chat_history or []) if m.get("role") in ("user", "assistant")][-4:]
    return "\n".join(f"{m['role']}: {' '.join((m.get('content') or '').split())[:300]}" for m in turns)


async def run(question: str, rule_facts: Optional[str], chunks: List[Dict[str, Any]],
              chat_history: Optional[List[Dict[str, Any]]] = None, seed: Tuple[str, ...] = ()) -> AgentResult:
    """
    Run the loop from what the pipeline already found. `seed`: tools code knows are needed (the M5.2 router's profile
    and processing_times_link), looked up before the first decision and shown as found: the model still decides
    whether to ask, search further, how to restate and when to answer. Model-unavailable errors propagate (M4.7).
    """
    observations = [_facts_line("the question", rule_facts), _search_line("the question", chunks)]
    state: AgentState = {
        "question": question, "conversation": _conversation(chat_history),
        "rule_facts": [rule_facts] if rule_facts else [], "chunks": list(chunks), "profile": None,
        "observations": observations, "tried": [_key("knowledge_base_search", question)], "steps": 0,
        "invalid_in_row": 0, "pending": None, "outcome": "", "trail": []}
    for action in seed:
        if action in ("profile", "processing_times_link"):
            state["pending"] = {"action": action, "query": ""}
            state.update(await _act(state))
            state["trail"][-1]["seeded"] = True
    final = await graph().ainvoke(state, config={"recursion_limit": 4 * settings.AGENT_MAX_STEPS + 10})
    facts = "\n\n".join(final.get("rule_facts") or []) or None
    return AgentResult(outcome=final.get("outcome") or "limit",
                       answer_question=final.get("answer_question") or question, ask=final.get("ask") or "",
                       rule_facts=facts, chunks=final.get("chunks") or [], trail=final.get("trail") or [])
