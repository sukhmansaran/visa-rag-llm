"""
Follow-up questions (M2.4): rewrite a message that only makes sense after the previous one ("And if my spouse comes
with me?", "Do my children also need to give them?") into a question that stands on its own, before triage,
rules, retrieval and decomposition see it. Until now only the answer step saw the conversation: the rules engine
was asked "And if my spouse comes with me?" (no funds rule) and retrieval searched for "What if my program was only
10 months long?" (no PGWP pages).

  1. Standalone: no earlier question, or the message names its own topic and points back at nothing -> unchanged.
  2. Deterministic, on the previous user question (itself resolved, so three-turn conversations chain):
       - "What if / And if X?"       its condition is replaced by X, or added to with "too/also" ("our child
                                      comes too" keeps "my spouse comes"); family members added drop "single"
       - "What about during X?"      the previous question's phrase with the same preposition is replaced
       - "... them / it / they ..."  the pronoun becomes the previous question's topic ("biometrics", "PGWP")
  3. Model fallback (structured_call, prompt `follow_up`) when no rule applies.
  Checked: the rewrite keeps every number and person word of the message, is about a known topic, and adds no
  acronym nobody wrote. A rewrite that fails is not used (the message goes on unchanged, with the conversation).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.services.decomposition import _ACRONYM, _facts
from app.services.topics import detect_topics

logger = logging.getLogger(__name__)

STANDALONE, DETERMINISTIC, MODEL, UNRESOLVED = "standalone", "deterministic", "model", "unresolved"
MAX_QUESTION_CHARS = 300

_LEAD = re.compile(r"^\s*(?:and|but|also|so|ok(?:ay)?|then)\b[,\s]*", re.IGNORECASE)
_CONDITION = re.compile(r"^(?:what|how)\s+(?:if|about)\s+(.+?)\s*\??\s*$|^if\s+(.+?)\s*\??\s*$", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(it|them|they|those|these|that one)\b", re.IGNORECASE)
_ADDITIVE = re.compile(r"\b(too|also|as well)\b", re.IGNORECASE)
_FAMILY = re.compile(r"\b(spouse|wife|husband|partner|child|children|son|daughter|kids?|family|parents?)\b",
                     re.IGNORECASE)
_SINGLE = re.compile(r"\bsingle\s+", re.IGNORECASE)
_PREPOSITION = re.compile(r"^(during|in|for|with|at|on|after|before|from|by)\b", re.IGNORECASE)
_QUESTION_START = re.compile(r"^(how|what|which|when|where|why|who|is|are|do|does|can|could|will|would|should)\b",
                             re.IGNORECASE)
# Where a replaced phrase ends: the next phrase ("for a bachelor's degree | in Manitoba") or a comma
_NEXT_PHRASE = re.compile(r",|\s(?=(?:during|in|for|with|at|on|after|before|from|by|if|while|when)\b)", re.IGNORECASE)
_LOWERABLE = frozenset("during in for with at on after before from by our my your his her their a an the "
                        "how what which when where why who is are do does can could will would should".split())
_FRAGMENT_WORDS = 5  # "How many hours per week?": too short to stand alone after a question
_VERBISH = re.compile(r"\b(is|are|was|were|be|been|comes?|came|go|goes|have|has|had|do|does|did|can|will|would|"
                      r"want|get|got|study|studies|work|works|apply|applies|need|needs)\b", re.IGNORECASE)


class Rewrite(BaseModel):
    question: str = Field(min_length=3, max_length=MAX_QUESTION_CHARS)


@dataclass(frozen=True)
class Resolution:
    question: str                                            # what the rest of the pipeline should answer
    original: str
    method: str                                              # standalone | deterministic | model | unresolved
    problems: Tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> Dict:
        """Trace fields: no user text."""
        return {"method": self.method, "changed": self.question != self.original, "problems": list(self.problems)}


def _user_turns(history: Optional[List[Dict]]) -> List[str]:
    return [" ".join(str(t.get("content", "")).split()) for t in (history or []) if t.get("role") == "user"
            and str(t.get("content", "")).strip()]


def needs_resolution(message: str, previous: Optional[str]) -> bool:
    """A message that leans on the previous question: a 'what if / and ...' opener, 'too / also / instead', a
    pronoun with nothing of its own to refer to, a fragment of a few words, or no topic at all."""
    if not previous:
        return False
    text = message.strip()
    own_topics = detect_topics(text).topics
    if _CONDITION.match(_LEAD.sub("", text)) or _LEAD.match(text) or _ADDITIVE.search(text):
        return True
    if _PRONOUN.search(text) and not set(detect_topics(previous).topics) <= set(own_topics):
        return True
    return not own_topics or len(text.split()) <= _FRAGMENT_WORDS


def rewrite(message: str, previous: str) -> Optional[str]:
    """The deterministic rewrite against the (already resolved) previous question, or None if no rule applies."""
    led = bool(_LEAD.match(message))
    text = _LEAD.sub("", " ".join(message.split())).strip()
    text = text[:1].upper() + text[1:] if text else text
    base = previous.strip().rstrip("?").strip()

    condition = _CONDITION.match(text)
    new, is_if = None, False
    if condition:
        new = (condition.group(1) or condition.group(2)).strip().rstrip("?").strip()
        is_if = bool(re.match(r"(?:what|how)\s+if\b|if\b", text, re.IGNORECASE))  # "what if" keeps its "if"
    elif _PREPOSITION.match(text) or (led and not _VERBISH.search(text) and not _QUESTION_START.match(text)):
        new = text.rstrip("?").strip()  # "And after a 1-year diploma?", "And our two kids?"
    if new:
        return _with_condition(base, new, is_if)

    pronoun = _PRONOUN.search(text)
    previous_topics = detect_topics(previous)
    if pronoun and previous_topics.topics:
        mention = previous_topics.mentions[previous_topics.topics[0]]
        return _question(f"{text[:pronoun.start()]}{mention}{text[pronoun.end():]}")

    # Carry the previous question's topic over when the message lacks it ("How much is the fee for a family of
    # three?" after a biometrics question)
    missing = [t for t in previous_topics.topics if t not in detect_topics(text).topics]
    if missing:  # every missing topic, so a chain of follow-ups keeps them all ("IELTS", then "Express Entry")
        about = ", ".join(previous_topics.mentions[t] for t in missing)
        return _question(f"{text.rstrip('?')} (about {about})")
    if len(text.split()) <= _FRAGMENT_WORDS:  # "How many hours per week?" after "Can I work off campus ...?"
        return _question(f"{base}, {_lower_first(text)}")
    return None


def _with_condition(base: str, new: str, is_if: bool = False) -> str:
    """Put the message's new condition into the previous question."""
    new = _lower_first(new)
    family = bool(_FAMILY.search(new))
    if family:
        base = _SINGLE.sub("", base)
    at_if = re.search(r"\bif\b", base, re.IGNORECASE)
    earlier = base[at_if.end():] if at_if else base
    if (at_if or family) and (_ADDITIVE.search(new) or (family and _FAMILY.search(earlier))):
        return _question(f"{base} and {new}")  # "our child comes too" / "and our two kids": people add up

    preposition = _PREPOSITION.match(new)
    if preposition and not family and not is_if:
        swapped = _swap_modifier(base, new)  # "on campus" replaces "off campus"
        if swapped:
            return _question(swapped)
        # "for a master's" replaces "for a bachelor's degree" and keeps "in Manitoba" after it
        at = re.search(rf"\b{preposition.group(1)}\b", base, re.IGNORECASE)
        if at:
            after = _NEXT_PHRASE.search(base, at.end())
            rest = base[after.start():] if after else ""
            return _question(f"{base[:at.start()].rstrip()} {new} {rest}".strip())
        return _question(f"{base} {new}")
    if at_if:
        return _question(f"{base[:at_if.start()].rstrip(' ,')} if {new}")
    if is_if or _VERBISH.search(new):
        return _question(f"{base}, if {new}")
    return _question(f"{base}, {new}" if preposition else f"{base}, for {new}")


def _swap_modifier(base: str, new: str) -> Optional[str]:
    """'<prep> X' where the previous question has '<other word> X' ('on campus' vs 'off campus'): swap them."""
    words = new.split()
    if len(words) != 2:
        return None
    match = re.search(rf"\b(\w+)\s+{re.escape(words[1])}\b", base, re.IGNORECASE)
    if match and match.group(1).lower() != words[0].lower():
        return f"{base[:match.start()]}{new}{base[match.end():]}"
    return None


def _lower_first(text: str) -> str:
    """'After a 1-year diploma' -> 'after a ...' inside a sentence; acronyms and names keep their capitals."""
    first = text.split(" ", 1)[0] if text else ""
    if first.lower() in _LOWERABLE:
        return first.lower() + text[len(first):]
    return text


def check(message: str, previous: str, history_text: str, candidate: str) -> List[str]:
    """Problems with a rewrite: lost facts, no topic, too long, an acronym nobody wrote."""
    problems = []
    if not candidate or len(candidate) > MAX_QUESTION_CHARS:
        return ["length: empty or too long"]
    lowered = candidate.lower()
    lost = [f for f in _facts(message) if f not in lowered]
    if lost:
        problems.append(f"facts: {', '.join(lost)} missing")
    if not detect_topics(candidate).topics and not detect_topics(previous).topics:
        problems.append("topic: the rewrite is about no known topic")
    written = set(_ACRONYM.findall(f"{message} {history_text}"))
    added = {a for a in _ACRONYM.findall(candidate) if a not in written and a.rstrip("s") not in written}
    if added:
        problems.append(f"acronyms: {', '.join(sorted(added))} added")
    return problems


async def resolve(message: str, history: Optional[List[Dict]], use_model: bool = True) -> Resolution:
    message = " ".join((message or "").split())
    users = _user_turns(history)
    if not users:
        return Resolution(message, message, STANDALONE)
    previous = _resolved_previous(users)
    if not needs_resolution(message, previous):
        return Resolution(message, message, STANDALONE)

    history_text = " ".join(str(t.get("content", "")) for t in history or [])
    candidate = rewrite(message, previous)
    if candidate:
        problems = check(message, previous, history_text, candidate)
        if not problems:
            return Resolution(candidate, message, DETERMINISTIC)
    else:
        problems = ["deterministic: no rule applies"]

    if use_model:
        modelled, model_problems = await _model_rewrite(message, previous, history, history_text)
        if modelled:
            return Resolution(modelled, message, MODEL, tuple(problems))
        problems += model_problems
    return Resolution(message, message, UNRESOLVED, tuple(problems))


def _resolved_previous(users: List[str]) -> str:
    """The last user question with earlier follow-ups resolved in order (deterministic only)."""
    resolved = users[0]
    for n, turn in enumerate(users[1:], 1):
        if needs_resolution(turn, resolved):
            candidate = rewrite(turn, resolved)
            earlier = " ".join(users[:n])  # carried-over acronyms (IELTS) were written in earlier turns
            resolved = candidate if candidate and not check(turn, resolved, earlier, candidate) else turn
        else:
            resolved = turn
    return resolved


async def _model_rewrite(message, previous, history, history_text) -> Tuple[Optional[str], List[str]]:
    from app.core.exceptions import AIServiceUnavailableError, LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    last_answer = next((str(t.get("content", "")) for t in reversed(history or []) if t.get("role") == "assistant"), "")
    system, user = get_prompt("follow_up").render(previous=previous, answer=last_answer[:600], message=message)
    try:
        reply = await llm_service.structured_call(Rewrite, system, user, role="planner", max_tokens=120)
    except (AIServiceUnavailableError, LLMStructuredOutputError) as e:
        logger.warning(f"[FOLLOW_UP] model rewrite unavailable ({type(e).__name__})")
        return None, [f"model: {type(e).__name__}"]
    candidate = " ".join(reply.question.split())
    problems = check(message, previous, history_text, candidate)
    return (None, [f"model {p}" for p in problems]) if problems else (candidate, [])


def _question(text: str) -> str:
    text = " ".join(text.split()).strip(" ,")
    text = text[:1].upper() + text[1:]
    return text if text.endswith("?") else f"{text}?"
