"""
Agent loop (M5.3), a LangGraph graph on the verified path (behind AGENT_LOOP):

    decide --(tool)--> act --> decide ... --(answer | limit)--> end
       |--(ask_user)--> ask: pauses (M5.4); the asker's reply resumes it here --> decide
       \\--(two invalid actions in a row)--> fallback (the M5.2 router's plan) --> end

The model makes the recoverable decisions: which action next, what to look up, whether to ask the user, when to answer
and how to restate the question with the asker's details. Code makes the rest: every action is checked (known action,
a usable query, not a repeat; tool arguments through app/services/tools.py), the steps are limited, and the answer is
not written here: the pipeline answers the chosen question from the gathered evidence with the M3/M4 evidence step and
its code checks, unchanged. A bad choice costs a step, never an unchecked answer.

The agent starts from what the pipeline already found (rule facts, the first search), so a simple question is
answered after one decision.

Clarifying questions (M5.4): `ask` pauses the graph with LangGraph's interrupt; the run is saved in the checkpoint
database (app/agent/checkpoints.py) and the job ends with the question. The reply is a new job: `resume` loads the
checkpoint, gives the reply to the model as an observation, and the loop goes on from the same point. Code allows one
question per answer, looks up the asker's saved profile before any question is asked, and refuses a question about a
detail the profile already holds. Without the checkpoint database the question ends the run (M5.3 behaviour).

Traced per step (`agent_step`: number, action, valid, what was found); never the query or
the model's reasoning, which can echo the user's words.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import tools
from app.services.tracing import trace_step

logger = logging.getLogger(__name__)

TOOL_ACTIONS = ("rules", "knowledge_base_search", "profile", "processing_times_link", "live_fetch")
MAX_INVALID_IN_A_ROW = 2
_SUMMARY_CHARS = 420


class AgentAction(BaseModel):
    thought: str = Field(default="", max_length=400)
    action: Literal["rules", "knowledge_base_search", "profile", "processing_times_link", "live_fetch", "ask_user",
                    "answer"]
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
    asked: bool                 # one question per answer (M5.4)
    can_pause: bool             # a checkpointer is attached: ask pauses instead of ending the run
    trail: List[Dict[str, Any]]


@dataclass
class AgentResult:
    outcome: str                         # answer | ask | limit | fallback
    answer_question: str                 # the question the evidence step answers (restated by the agent)
    ask: str = ""                        # the clarifying question, when outcome == "ask"
    rule_facts: Optional[str] = None
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    trail: List[Dict[str, Any]] = field(default_factory=list)
    thread_id: str = ""                  # set when the run paused at its question (M5.4) and can be resumed
    question: str = ""                   # the question the run started from (a resume gets it from the checkpoint)

    def summary(self) -> Dict[str, Any]:
        actions = [t["action"] for t in self.trail]
        return {"outcome": self.outcome, "steps": len(self.trail), "actions": actions,
                "invalid": sum(not t["valid"] for t in self.trail), "paused": bool(self.thread_id)}


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
        url = meta.get("url") or ""
        parts.append(f"{title} <{url}>: {' '.join((c.get('text') or '').split())[:110]}")
    return f"search ({query}): {len(chunks)} passages: " + " || ".join(parts)


def _profile_line(profile: Dict[str, Any]) -> str:
    if not profile.get("found"):
        return "profile: no saved profile."
    shown = {k: v for k, v in profile.items() if k != "found" and v not in (None, "", {}, [])}
    return "profile: " + json.dumps(shown, ensure_ascii=False)[:_SUMMARY_CHARS]


# What a clarifying question asks about -> the profile field that already answers it
_PROFILE_FIELDS = {
    "education_level": re.compile(r"\b(?:degree|diploma|education|level of stud|bachelor|master|phd|doctora|"
                                  r"undergrad|graduate program|college or university)", re.IGNORECASE),
    "field_of_study": re.compile(r"\b(?:field of study|what (?:do|will|are) you stud|program of study|major)\b",
                                 re.IGNORECASE),
    "work_experience_years": re.compile(r"\b(?:work experience|years of experience|how long have you worked)",
                                        re.IGNORECASE),
    "test_scores": re.compile(r"\b(?:ielts|celpip|pte|tef|tcf|test scores?|language (?:test|scores?|results?)|clb)",
                              re.IGNORECASE),
}


def _held_by_profile(ask: str, profile: Optional[Dict[str, Any]]) -> List[str]:
    """Profile fields the clarifying question asks about that the saved profile already holds."""
    if not profile or not profile.get("found"):
        return []
    return [name for name, pattern in _PROFILE_FIELDS.items()
            if profile.get(name) not in (None, "", {}, []) and pattern.search(ask)]


# The question asks what is current: the stored copy of a page may be behind
_CURRENT = re.compile(
    r"\b(?:latest|right now|as of (?:today|now)|recent(?:ly)? (?:changes?|updates?)|new (?:rules?|changes?|requirements?)"
    r"|still (?:valid|the case|true|appl(?:y|ies))|(?:has|have) (?:it|this|that|the \w+) changed"
    r"|current (?:rules?|requirements?|amounts?|fees?|figures?|polic(?:y|ies)))\b", re.IGNORECASE)


def _page_to_check(state: "AgentState") -> str:
    """The official page to fetch before answering a question about what is current: the first found passage's
    registry page, if no page was fetched yet ('' otherwise)."""
    if not (settings.LIVE_FETCH_ENABLED and _CURRENT.search(state.get("question") or "")):
        return ""
    if any(t.startswith("live_fetch|") for t in state.get("tried") or []):
        return ""
    from app.services.source_registry import load_registry

    registry = load_registry().by_url()
    for chunk in state.get("chunks") or []:
        url = (chunk.get("metadata") or {}).get("url") or ""
        if url in registry:
            return url
    return ""


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
        page = _page_to_check(state)
        if page:
            # Code backstop (M5.5a): the question asks what is current and the agent didn't fetch; fetch the top
            # official page once, then let it decide again with the current text in view. Costs no step.
            update.update(pending={"action": "live_fetch", "query": page, "before_answer": "1"}, steps=steps)
            return update
        update.update(outcome="answer", answer_question=chosen.query.strip() or state["question"], pending=None)
        trail.append({"n": steps + 1, "action": "answer", "valid": True})
        with trace_step("agent_step", **trail[-1]):
            pass
    elif chosen.action == "ask_user":
        if state.get("profile") is None and _key("profile", "") not in (state.get("tried") or []):
            # Never ask for what the profile holds (M5.4): look it up first, then let the model choose again with
            # it in view. Not the model's mistake, so it isn't an invalid choice, and it costs no step.
            update.update(pending={"action": "profile", "query": "", "before_ask": "1"}, steps=steps)
            return update
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
        if state.get("asked") or (not state.get("can_pause") and state.get("conversation")
                                  and "assistant:" in state["conversation"].lower()):
            return "the asker has already been asked once; answer with what is known"
        held = _held_by_profile(query, state.get("profile"))
        if held:
            return (f"the asker's saved profile already has {', '.join(held)} (see 'profile' above); use it and "
                    "don't ask for it")
    if chosen.action == "live_fetch" and not query.startswith("https://"):
        return "live_fetch needs the exact URL of an official page shown above"
    if chosen.action in TOOL_ACTIONS and _key(chosen.action, query) in (state.get("tried") or []):
        return (f"{chosen.action} was already done with this query and its result is above; if the answer depends on "
                "something the asker did not say, choose ask_user, otherwise choose answer")
    return ""


async def _act(state: AgentState) -> AgentState:
    pending = state["pending"]
    action, query = pending["action"], pending["query"]
    args = {"rules": {"question": query}, "knowledge_base_search": {"query": query},
            "live_fetch": {"url": query}}.get(action, {})
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
            line = _profile_line(profile)
            if pending.get("before_ask"):
                line = ("(before asking, code looked up the asker's saved profile; ask only for what it doesn't "
                        "hold) " + line)
            observations.append(line)
        elif action == "live_fetch":
            from app.services import live_fetch
            from app.services.source_registry import load_registry

            page = live_fetch.FetchedPage(url=result.url, final_url=result.url, title=result.title, text=result.text,
                                          fetched_at=result.fetched_at, tier=load_registry().by_url()[result.url].tier)
            picked = await live_fetch.passages(page, state["question"])
            chunks += picked["chunks"]
            found = len(picked["chunks"])
            line = _search_line(f"fetched now: {result.url}", picked["chunks"]).replace("search (", "live fetch (", 1)
            if picked["dropped"]:
                line += f" ({picked['dropped']} passages that read like instructions were left out)"
            if pending.get("before_answer"):
                line = "(the question asks what is current, so code fetched the official page first) " + line
            observations.append(line)
        elif action == "processing_times_link":
            block = (f"OFFICIAL IRCC PROCESSING TIMES: Pendu stores no processing-time figures. {result.note} "
                     f"Check the current time with IRCC's tool: {result.url}")
            if block not in rule_facts:
                rule_facts.append(block)
            found = 1
            observations.append(f"processing times: check {result.url} (no figures are stored)")
    trail = list(state.get("trail") or [])
    trail.append({"n": state.get("steps", 0), "action": action, "valid": valid, "found": found})
    if pending.get("before_ask"):
        trail[-1]["before_ask"] = True
    if pending.get("before_answer"):
        trail[-1]["before_answer"] = True
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


async def _ask(state: AgentState) -> AgentState:
    """Pause for the asker's reply (M5.4). LangGraph saves the run and stops here; on resume this node runs again
    and `interrupt` returns the reply, so nothing with side effects comes before it."""
    from langgraph.types import interrupt

    reply = " ".join(str(interrupt({"question": state["ask"]}) or "").split())[:600]
    trail = list(state.get("trail") or [])
    trail.append({"n": state.get("steps", 0), "action": "user_reply", "valid": bool(reply)})
    with trace_step("agent_step", **trail[-1]):
        pass
    observations = list(state.get("observations") or [])
    observations.append(f'you asked the asker "{state["ask"]}"; they replied: "{reply or "(nothing)"}". '
                        "Use their reply; you can't ask again.")
    conversation = "\n".join(filter(None, [state.get("conversation"), f"assistant: {state['ask']}", f"user: {reply}"]))
    return {"observations": observations, "conversation": conversation, "asked": True, "outcome": "",
            "trail": trail}


def _after_decide(state: AgentState) -> str:
    if state.get("outcome") == "ask" and state.get("can_pause") and not state.get("asked"):
        return "ask"
    if state.get("outcome") in ("answer", "ask", "limit"):
        return "end"
    if state.get("outcome") == "fallback":
        return "fallback"
    return "act" if state.get("pending") else "decide"


_builder = None


def graph(checkpointer=None):
    """The compiled graph; with a checkpointer (M5.4) its runs can pause at `ask` and be resumed."""
    global _builder
    if _builder is None:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(AgentState)
        builder.add_node("decide", _decide)
        builder.add_node("act", _act)
        builder.add_node("ask", _ask)
        builder.add_node("fallback", _fallback)
        builder.add_edge(START, "decide")
        builder.add_conditional_edges("decide", _after_decide, {"act": "act", "decide": "decide", "ask": "ask",
                                                                "fallback": "fallback", "end": END})
        builder.add_edge("act", "decide")
        builder.add_edge("ask", "decide")
        builder.add_edge("fallback", END)
        _builder = builder
    return _builder.compile(checkpointer=checkpointer)


def _conversation(chat_history: Optional[List[Dict[str, Any]]]) -> str:
    """The last exchange, so a reply to the agent's own question is understood."""
    turns = [m for m in (chat_history or []) if m.get("role") in ("user", "assistant")][-4:]
    return "\n".join(f"{m['role']}: {' '.join((m.get('content') or '').split())[:300]}" for m in turns)


def _config(thread_id: str) -> Dict[str, Any]:
    return {"recursion_limit": 4 * settings.AGENT_MAX_STEPS + 10, "configurable": {"thread_id": thread_id}}


def _result(final: Dict[str, Any], question: str, thread_id: str = "") -> AgentResult:
    paused = bool(final.get("__interrupt__"))
    facts = "\n\n".join(final.get("rule_facts") or []) or None
    return AgentResult(outcome="ask" if paused else (final.get("outcome") or "limit"),
                       answer_question=final.get("answer_question") or question, ask=final.get("ask") or "",
                       rule_facts=facts, chunks=final.get("chunks") or [], trail=final.get("trail") or [],
                       thread_id=thread_id if paused else "", question=final.get("question") or question)


async def run(question: str, rule_facts: Optional[str], chunks: List[Dict[str, Any]],
              chat_history: Optional[List[Dict[str, Any]]] = None, seed: Tuple[str, ...] = (),
              thread_id: str = "") -> AgentResult:
    """
    Run the loop from what the pipeline already found. `seed`: tools code knows are needed (the M5.2 router's profile
    and processing_times_link), looked up before the first decision and shown as found: the model still decides
    whether to ask, search further, how to restate and when to answer. Model-unavailable errors propagate (M4.7).
    `thread_id` (M5.4): checkpoint the run under this id so its question can pause it; the result's thread_id is set
    only if it paused. A run that finishes leaves no checkpoint.
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
    if not thread_id:
        return _result(await graph().ainvoke(state, config=_config("unsaved")), question)

    from app.agent import checkpoints

    async with checkpoints.saver() as saver:
        state["can_pause"] = saver is not None
        final = await graph(saver).ainvoke(state, config=_config(thread_id))
        result = _result(final, question, thread_id if saver is not None else "")
        if saver is not None and not result.thread_id:
            await saver.adelete_thread(thread_id)  # finished without pausing: nothing to keep
    return result


async def paused_question(thread_id: str) -> Optional[Dict[str, str]]:
    """{question, ask} of a run paused at its question, or None (finished, deleted, expired or unreachable)."""
    from app.agent import checkpoints

    async with checkpoints.saver() as saver:
        if saver is None:
            return None
        snapshot = await graph(saver).aget_state(_config(thread_id))
    if "ask" not in (snapshot.next or ()):
        return None
    return {"question": snapshot.values.get("question", ""), "ask": snapshot.values.get("ask", "")}


async def resume(thread_id: str, reply: str) -> Optional[AgentResult]:
    """Continue a run paused at its question with the asker's reply (M5.4); None if no run is paused under this id
    (finished, deleted, expired, or the checkpoint database unreachable). The checkpoint is deleted once the run is
    over: one question per answer, so it can't pause again."""
    from langgraph.types import Command

    from app.agent import checkpoints

    async with checkpoints.saver() as saver:
        if saver is None:
            return None
        app = graph(saver)
        snapshot = await app.aget_state(_config(thread_id))
        if "ask" not in (snapshot.next or ()):
            return None
        question = snapshot.values.get("question", "")
        try:
            final = await app.ainvoke(Command(resume=reply), config=_config(thread_id))
        finally:
            await saver.adelete_thread(thread_id)
    return _result(final, question)
