"""
Decomposition (M2.2): split a question that asks several things into self-contained sub-questions.

  1. Single: one topic and no second question ("..., and how ...") -> the question itself, no model call.
  2. Model: structured_call with the `decomposition` prompt, then validators:
       count      at most max(detected topics, questions the user asked) sub-questions (the roadmap said topics
                  + 1: that refused a 3-part question on one topic and let the model add a question nobody asked)
       coverage   every detected topic is in some sub-question
       duplicates no two sub-questions are near-duplicates
       mapping    every sub-question is about a detected topic or clearly part of the original question, and
                  brings in no topic the user did not ask about
       facts      every number and person / program word in the question (single, spouse, children, master's,
                  months...) is in some sub-question: an answer about funds without "single" is a wrong answer
       acronyms   no acronym expanded differently from the glossary, and none the user did not write
     If the only problems are invented expansions, they are removed ("Express Entry Confirmation (ECA)" -> "ECA")
     and the split is checked again (`repaired`).
  3. Fallback: any validator fails, or the model is unavailable or returns bad JSON -> a deterministic split of
     the user's own clauses by topic (or the question unsplit if that can't cover every topic).
The result records which path was taken and why, for traces and the evaluation (scripts/eval_decomposition.py).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from app.services.glossary import glossary
from app.services.topics import TopicResult, detect_topics

logger = logging.getLogger(__name__)

SINGLE, MODEL, FALLBACK = "single", "model", "fallback"
MAX_SUB_QUESTION_CHARS = 300
_DUPLICATE_JACCARD = 0.8
_MIN_OVERLAP = 0.5  # share of a topic-less sub-question's content words found in the original

_QUESTION_WORDS = r"how|what|which|when|where|why|who|are|is|do|does|can|could|will|would|should|am"
_SECOND_QUESTION = re.compile(rf"(,\s*|\s)and ({_QUESTION_WORDS})\b", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(rf"(?<=[?.!])\s+|;\s*|,?\s+and\s+(?=(?:{_QUESTION_WORDS})\b)|,\s+(?=(?:{_QUESTION_WORDS})\b)",
                           re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_STOP = frozenset("""a an the and or of to for in on at by with is are am be do does did can could will would should
i my me we our you your it its this that what which how when where who why if as from about there their they""".split())
# "PAL (Provincial ...)" and "Provincial ... (PAL)"
_ACRONYM_FORM = r"(?:[A-Z]{2,6}|e[A-Z]{2,5})s?"
_EXPANDED_AFTER = re.compile(rf"\b({_ACRONYM_FORM})\s*\(([^()]{{3,80}})\)")  # "PAL (provincial ...)"
_IN_BRACKETS = re.compile(rf"\(({_ACRONYM_FORM})\)")                     # "... letter (PAL)"
_ACRONYM = re.compile(r"\b(?:[A-Z]{2,6}s?|e[A-Z]{2,5})\b")


class SubQuestions(BaseModel):
    sub_questions: List[str] = Field(min_length=1, max_length=8)


@dataclass(frozen=True)
class Decomposition:
    question: str
    sub_questions: Tuple[str, ...]
    method: str                                             # single | model | fallback
    topics: Tuple[str, ...] = field(default_factory=tuple)  # detected in the original question
    problems: Tuple[str, ...] = field(default_factory=tuple)  # why the model's split was not used
    proposed: Tuple[str, ...] = field(default_factory=tuple)  # the model's split as returned (kept for evaluation)
    repaired: bool = False                                  # invented acronym expansions were removed

    def summary(self) -> dict:
        """Trace fields: no user text, only the shape of the split."""
        return {"method": self.method, "parts": len(self.sub_questions), "topics": list(self.topics),
                "problems": list(self.problems), "repaired": self.repaired}


def _asks(question: str) -> int:
    """How many questions the user asked: question clauses (see fallback_split for the clause rules)."""
    return sum(_is_question(c.strip(" ,")) for c in _CLAUSE_SPLIT.split(question or "") if c and c.strip(" ,"))


def _listed_topics(question: str, detected: TopicResult) -> bool:
    """Two topics joined as a list ("the funds and work hour rules"), not one topic qualifying another
    ("biometrics for a visitor visa")."""
    mentions = [detected.mentions[t] for t in detected.topics]
    lowered = question.lower()
    for first, second in zip(mentions, mentions[1:]):
        start, end = lowered.find(first.lower()), lowered.find(second.lower())
        if 0 <= start < end and re.search(r"\band\b|,", lowered[start + len(first):end]):
            return True
    return False


def max_parts(question: str, detected: TopicResult) -> int:
    """One sub-question per question asked; per topic only when the topics are listed side by side."""
    topics = len(detected.topics) if _listed_topics(question, detected) else 1
    return max(_asks(question), topics, 1)


def needs_split(question: str, topics: Optional[TopicResult] = None) -> bool:
    """Several questions asked, or several topics listed. One question touching two topics ("Do children need
    biometrics for a visitor visa?") is not split: the model then adds questions nobody asked."""
    topics = topics or detect_topics(question)
    return _asks(question) >= 2 or (len(topics.topics) >= 2 and _listed_topics(question, topics))


async def decompose(question: str) -> Decomposition:
    question = " ".join((question or "").split())
    detected = detect_topics(question)
    if not needs_split(question, detected):
        return Decomposition(question, (question,), SINGLE, detected.topics)

    from app.core.exceptions import AIServiceUnavailableError, LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    system, user = get_prompt("decomposition").render(
        question=question, topics=", ".join(detected.topics) or "none", max_parts=str(max_parts(question, detected)))
    try:
        reply = await llm_service.structured_call(SubQuestions, system, user, role="planner", max_tokens=300)
        subs = [" ".join(s.split()) for s in reply.sub_questions if s and s.strip()]
        problems = validate(question, detected, subs)
    except (AIServiceUnavailableError, LLMStructuredOutputError) as e:
        logger.warning(f"[DECOMPOSE] model unavailable or invalid output ({type(e).__name__}); deterministic split")
        subs, problems = [], [f"model: {type(e).__name__}"]

    if not problems:
        return Decomposition(question, tuple(subs), MODEL, detected.topics, proposed=tuple(subs))
    if all(p.startswith("acronyms:") and " expands " in p for p in problems):
        repaired = [strip_expansions(s) for s in subs]
        if not validate(question, detected, repaired):
            return Decomposition(question, tuple(repaired), MODEL, detected.topics, tuple(problems),
                                 proposed=tuple(subs), repaired=True)
    return Decomposition(question, tuple(fallback_split(question, detected)), FALLBACK, detected.topics,
                         tuple(problems), proposed=tuple(subs))


# ---------------------------------------------------------------- validators

def validate(question: str, detected: TopicResult, subs: List[str]) -> List[str]:
    """Problems with a proposed split; empty means it is usable."""
    problems: List[str] = []
    if not subs:
        return ["count: no sub-questions"]
    limit = max_parts(question, detected)
    if len(subs) > limit:
        problems.append(f"count: {len(subs)} sub-questions, at most {limit} (topics or questions asked)")
    if any(len(s) > MAX_SUB_QUESTION_CHARS for s in subs):
        problems.append("count: a sub-question is too long")

    sub_topics = [set(detect_topics(s).topics) for s in subs]
    missing = [t for t in detected.topics if not any(t in topics for topics in sub_topics)]
    if missing:
        problems.append(f"coverage: no sub-question about {', '.join(missing)}")

    words = [_content_words(s) for s in subs]
    for i in range(len(subs)):
        for j in range(i + 1, len(subs)):
            if _jaccard(words[i], words[j]) >= _DUPLICATE_JACCARD:
                problems.append(f"duplicates: sub-questions {i + 1} and {j + 1}")

    original_words = _content_words(question)
    for n, (sub, topics) in enumerate(zip(subs, sub_topics), 1):
        extra = topics - set(detected.topics)
        if extra:
            problems.append(f"mapping: sub-question {n} adds {', '.join(sorted(extra))}")
        elif not topics and _overlap(words[n - 1], original_words) < _MIN_OVERLAP:
            problems.append(f"mapping: sub-question {n} is not about the question")

    joined = " ".join(subs).lower()
    lost = [fact for fact in _facts(question) if fact not in joined]
    if lost:
        problems.append(f"facts: {', '.join(lost)} missing from every sub-question")

    problems.extend(acronym_problems(question, subs))
    return problems


# Facts an answer depends on: who is applying, family, level and length of study, plus every number
_FACT_WORDS = re.compile(
    r"\b(single|alone|spouse|wife|husband|partner|common-law|child|children|son|daughter|kids?|family|parents?|"
    r"mother|father|brother|sister|master's|masters|bachelor's|bachelors|phd|doctoral|diploma|certificate|"
    r"college|university|secondary|high school|months?|years?|weeks?|part-time|full-time|online)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\$?\d+(?:,\d{3})*(?:\.\d+)?")  # "$22,895", "9" (not "9," before a comma)


def _facts(question: str) -> List[str]:
    found = [m.group(0).lower() for m in _FACT_WORDS.finditer(question)] + _NUMBER.findall(question)
    return list(dict.fromkeys(found))


_INVENTED_BEFORE = re.compile(rf"(?:\b(?:[A-Z][\w'-]*|of|and|for|the|to)\s+)*?\b[A-Z][\w'-]*\s*\(({_ACRONYM_FORM})\)")
_INVENTED_AFTER = re.compile(rf"\b({_ACRONYM_FORM})\s*\([^()]{{3,80}}\)")


def strip_expansions(sub: str) -> str:
    """'an Express Entry Confirmation of Completeness (ECA)' -> 'an ECA'; 'PAL (Permanent ...)' -> 'PAL'."""
    sub = _INVENTED_AFTER.sub(lambda m: m.group(1), sub)
    return " ".join(_INVENTED_BEFORE.sub(lambda m: m.group(1), sub).split())


def acronym_problems(question: str, subs: List[str]) -> List[str]:
    """Acronyms expanded unlike the glossary, or acronyms the user did not write."""
    problems = []
    asked = set(_ACRONYM.findall(question))
    for n, sub in enumerate(subs, 1):
        for acronym, text in _EXPANDED_AFTER.findall(sub):        # "PAL (Permanent Resident Card)"
            problem = _expansion_problem(acronym, _normal(text), exact=True)
            if problem:
                problems.append(f"acronyms: sub-question {n} {problem}")
        for match in _IN_BRACKETS.finditer(sub):                 # "Express Entry Confirmation ... (ECA)"
            problem = _expansion_problem(match.group(1), _normal(sub[:match.start()]), exact=False)
            if problem:
                problems.append(f"acronyms: sub-question {n} {problem}")
        for acronym in set(_ACRONYM.findall(sub)) - asked:
            if acronym.rstrip("s") not in asked:
                problems.append(f"acronyms: sub-question {n} adds {acronym}, which the user did not write")
    return problems


def _normal(text: str) -> str:
    return " ".join(re.sub(r"[-‐–]", " ", text.lower()).split())


def _expansion_problem(acronym: str, text: str, exact: bool) -> Optional[str]:
    """None if `text` is the glossary's expansion (or an alias) of `acronym`: equal to it (exact) or ending with it
    (the words just before "(ACR)"). Otherwise what is wrong, as a short phrase."""
    term = glossary().get(acronym) or glossary().get(acronym.rstrip("s"))
    if term is None:
        return f"expands {acronym}, which is not in the glossary"
    known = [_normal(p) for p in (term.expansion, *term.aliases) if not p.isupper()]
    if any(text == k if exact else (text == k or text.endswith(" " + k)) for k in known):
        return None
    shown = text if exact else " ".join(text.split()[-6:])
    return f"expands {acronym} as '{shown}', not '{term.expansion}'"


# ---------------------------------------------------------------- deterministic split

def fallback_split(question: str, detected: Optional[TopicResult] = None) -> List[str]:
    """
    The user's own clauses, split at sentence ends, ';' and ', (and) <question word>': each question clause becomes
    a sub-question; a statement ("My wife is coming with me.", "As a single student") is context, repeated in every
    question after it, so each part stands alone. If the questions don't cover every detected topic, the question is returned unsplit.
    """
    detected = detected or detect_topics(question)
    clauses = [c.strip(" ,") for c in _CLAUSE_SPLIT.split(question) if c and c.strip(" ,")]
    parts: List[str] = []
    context = ""
    for clause in clauses:
        if not _is_question(clause):
            context = f"{context} {clause}".strip()
            continue
        parts.append(_as_question(_join(context, clause) if context else clause))  # context stays for later parts
    covered = {t for p in parts for t in detect_topics(p).topics}
    if len(parts) < 2 or not set(detected.topics) <= covered:
        return [question]
    return parts


def _join(context: str, clause: str) -> str:
    """'As a single student' + 'how much ...' -> 'As a single student, how much ...'; sentences keep their stop."""
    if context.endswith((".", "?", "!")):
        return f"{context} {clause[:1].upper()}{clause[1:]}"
    return f"{context}, {clause}"


def _is_question(clause: str) -> bool:
    return clause.endswith("?") or bool(re.match(rf"({_QUESTION_WORDS})\b", clause, re.IGNORECASE))


def _as_question(text: str) -> str:
    text = text.strip().rstrip(".,;")
    text = text[:1].upper() + text[1:]
    return text if text.endswith("?") else f"{text}?"


def _content_words(text: str) -> set:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _overlap(part: set, whole: set) -> float:
    return len(part & whole) / len(part) if part else 0.0
