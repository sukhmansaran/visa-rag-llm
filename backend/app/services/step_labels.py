"""
Plain-language lines for the chat's "how this answer was made" list (M6.1).

Each finished pipeline step (a request-trace step: name + fields, never user text) becomes one short sentence in the
past tense, or None when the step is internal and not worth a line. The wording lives here, next to the pipeline and
under test, so the browser only renders it. `STEP_NAMES` lists every step the answer pipeline emits: a test fails if a
new step is added without deciding its line here.
"""

from typing import Any, Dict, Optional
from urllib.parse import urlparse

# step name -> True if it can produce a line, False if it is internal (no line, by decision)
STEP_NAMES = {
    "agent_resume": True, "input_guardrail": True, "follow_up": True, "verified_cache": True, "monitor": True,
    "triage": True, "intent": False, "decomposition": True, "rules": True, "route": False, "cache": True,
    "tourist_db": False, "retrieval": True, "evidence_gate": True, "agent": True, "agent_step": True, "tool": False,
    "evidence": True, "reflect": True, "retry": True, "generation": True, "output_guardrail": True,
    "disclaimer": True, "verified_cache_store": False, "degraded": True, "diagnostic": True,
}

_TRIAGE_REASONS = {"multi_part": "it has several parts", "legal_risk": "it touches a legal risk",
                   "premise": "it assumes something that needs checking", "personal": "it depends on your details",
                   "low_confidence": "the first search was weak"}
_AGENT_TOOLS = {"rules": "Looked up the official rules", "knowledge_base_search": "Searched the official pages again",
                "profile": "Checked your saved profile", "processing_times_link": "Found IRCC's processing-times tool",
                "live_fetch": "Fetched the current version of an official page"}
_AGENT_FAILED = {"rules": "Couldn't look up the official rules", "knowledge_base_search": "Couldn't search the official pages",
                 "profile": "Couldn't read your saved profile", "processing_times_link": "Couldn't find IRCC's processing-times tool",
                 "live_fetch": "Couldn't fetch the official page, so it went on with what it had"}
_REFLECT = {"knowledge_base_search": "search with different words", "rules": "look it up in the official rules",
            "live_fetch": "fetch the current page", "restate": "ask it more clearly",
            "finish": "stop: the official sources don't cover it"}
_EVIDENCE = {"verified": "Checked a part against its source: the quote matches",
             "not_covered": "Checked a part: the sources found don't cover it",
             "unverified": "Checked a part: its evidence didn't hold, so it isn't shown as verified",
             "invalid": "Couldn't read the answer step's output for a part",
             "not_reached": "Ran out of time before checking a part"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _sites(chunks) -> str:
    hosts = list(dict.fromkeys(urlparse(c.get("url") or "").netloc.removeprefix("www.") for c in chunks or []))
    hosts = [h for h in hosts if h]
    return f" from {', '.join(hosts[:2])}" if hosts else ""


def describe(step: Dict[str, Any]) -> Optional[str]:
    """One sentence for a finished step, or None (internal step, or nothing happened worth saying)."""
    name = step.get("name")
    if name == "agent_resume":
        return "Picked up where it stopped, with your reply" if step.get("found") else None
    if name == "input_guardrail":
        return "Checked the question is one it can help with" if step.get("allowed") else "Declined the request"
    if name == "follow_up":
        return "Read it as a follow-up to your earlier question" if step.get("changed") else None
    if name == "verified_cache":
        return "Found a checked answer to this question from earlier" if step.get("hit") else None
    if name == "monitor":
        if step.get("available") is False:
            return "The second safety check was unavailable; checked by code rules only"
        return "A second safety check passed" if not step.get("denied") else "A second safety check declined it"
    if name == "triage":
        if step.get("routed") != "verified":
            return None
        reasons = [_TRIAGE_REASONS[r] for r in step.get("reasons") or [] if r in _TRIAGE_REASONS]
        return "Chose the careful, step-by-step check" + (f" because {reasons[0]}" if reasons else "")
    if name == "decomposition":
        parts = step.get("parts") or 1
        return f"Split the question into {parts} parts" if isinstance(parts, int) and parts > 1 else None
    if name == "rules":
        return "Found official figures for this in the rules" if step.get("rule_facts") else None
    if name == "cache":
        return "Used an earlier answer to the same question" if step.get("used") else None
    if name == "retrieval":
        chunks = step.get("chunks") or []
        if step.get("retrieval_error"):
            return "Couldn't search the official pages"
        return f"Found {_plural(len(chunks), 'passage')}{_sites(chunks)}" if chunks else "Found no matching passages"
    if name == "evidence_gate":
        return None if step.get("has_evidence") else "Not enough official evidence to answer"
    if name == "agent_step":
        return _agent_step(step)
    if name == "agent":
        if step.get("outcome") == "fallback":
            return "The agent's choices weren't usable, so the standard plan took over"
        if step.get("outcome") == "limit":
            return "Reached the step limit and answered with what it had"
        return None
    if name == "evidence":
        line = _EVIDENCE.get(step.get("status"))
        return line + " (partially verified)" if line and step.get("partial") else line
    if name == "reflect":
        if not step.get("valid"):
            return "Couldn't choose a next attempt, so the standard retry was used"
        return f"A part didn't check out; decided to {_REFLECT.get(step.get('action'), 'try again')}"
    if name == "retry":
        if step.get("skipped"):
            return "No time left for another attempt"
        if step.get("tool_error"):
            return "The extra attempt couldn't run"
        if "retry" not in step:
            return "The extra attempt found nothing new"
        return ("The second attempt checked out and replaced the first" if step.get("kept") == "retry"
                else "The second attempt was no better, so the first result stands")
    if name == "generation":
        return "Wrote the answer from the sources"
    if name == "output_guardrail":
        return "Checked the answer before showing it" if step.get("valid", True) else "Corrected the answer before showing it"
    if name == "disclaimer":
        return "Added a legal notice for this topic" if step.get("high_risk") else None
    if name == "degraded":
        return "The model was unavailable, so it answered without it"
    if name == "diagnostic":
        return f"Diagnostic step {step.get('n')}" + (f" of {step['of']}" if step.get("of") else "")
    return None


def _agent_step(step: Dict[str, Any]) -> Optional[str]:
    action = step.get("action")
    if not step.get("valid"):
        if action in _AGENT_FAILED and "problem" not in step:
            return _AGENT_FAILED[action]
        return "The agent made a choice that couldn't be used and chose again"
    if action in _AGENT_TOOLS:
        line = _AGENT_TOOLS[action]
        if step.get("before_ask"):
            line += " before asking you anything"
        elif step.get("before_answer"):
            line += ", because the question asks what is current"
        found = step.get("found")
        if action == "knowledge_base_search" and isinstance(found, int):
            line += f" ({_plural(found, 'new passage')})"
        elif action == "profile" and not found:
            line += " (nothing saved)"
        elif action == "rules" and not found:
            line += " (nothing for this)"
        return line
    return {"ask_user": "Decided it needs one detail from you", "user_reply": "Read your reply",
            "answer": "Decided it has what it needs to answer"}.get(action)
