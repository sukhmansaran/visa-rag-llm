"""
Evidence-grounded answers (M3): the verified path answers each part with a quote it can be checked against.

M3.1 Evidence step: for each part (sub-question, or the question itself), `structured_call` returns
     {answer, evidence_quote, source_number} or {not_covered: true}, from a context where the official rule facts are
     [Source 0] and each retrieved chunk is [Source N] as usual.
M3.2 Code check: after normalising whitespace, quotes, dashes and markdown, the quote must be in the cited source word for
     word (case aside), the source must exist, the quote must be a real sentence (not a few words), and every number
     in the answer must be in the quote (or the question). A real quote under the wrong source number is corrected.
A part that is not covered, fails the check, or whose output is unreadable says so plainly instead of guessing; the
answer is composed from the checked parts only. Claim-level checks and retries are M4.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

RULES_SOURCE = 0
MIN_QUOTE_WORDS = 4
NOT_COVERED_TEXT = "The official sources I have don't cover this: {part}"
UNVERIFIED_TEXT = "I couldn't check an answer to this against the official sources: {part}"

_SPACE = re.compile(r"\s+")
_MARKDOWN = re.compile(r"\*\*|__|`|(?<!\w)[*•](?!\w)")  # emphasis and bullet markers, not hyphens or words
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CITATION = re.compile(r"\s*\[(?:Source|Sources?)\s*[\d,\s]*\]", re.IGNORECASE)
_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


class EvidenceAnswer(BaseModel):
    not_covered: bool = False
    answer: str = Field(default="", max_length=800)
    evidence_quote: str = Field(default="", max_length=800)
    source_number: int = Field(default=-1, ge=-1, le=50)


@dataclass(frozen=True)
class PartResult:
    part: str
    status: str                     # verified | not_covered | unverified | invalid
    answer: str = ""
    quote: str = ""
    source_number: int = -1
    problems: Tuple[str, ...] = field(default_factory=tuple)
    partial: bool = False           # M4.2: the model check doubted a claim (shown as "partially verified")
    claims: int = 0                 # claims checked (M4.1/M4.2)

    def summary(self) -> Dict[str, Any]:
        """Trace fields: no user text."""
        return {"status": self.status, "source": self.source_number, "problems": list(self.problems),
                "partial": self.partial, "claims": self.claims}


def evidence_context(rule_facts: Optional[str], chunk_context: str) -> str:
    """The context the evidence step sees: rule facts as [Source 0], then the chunks ([Source 1..N])."""
    blocks = []
    if rule_facts:
        blocks.append(f"[Source {RULES_SOURCE}] (Official rules)\n{rule_facts}")
    if chunk_context:
        blocks.append(chunk_context)
    return "\n\n".join(blocks)


def _normal(text: str) -> str:
    """For comparing a quote with its source: same words, ignoring case, spacing, curly quotes, dashes and the page's
    markdown ('You **don’t** need a PAL' is quoted as 'You don't need a PAL')."""
    text = _MARKDOWN.sub(" ", (text or "").translate(_TRANSLATE))
    return _SPACE.sub(" ", text).strip().lower()


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text or "")}


def check(reply: EvidenceAnswer, sources: Dict[int, str], question: str, rule_facts: Optional[str]) -> List[str]:
    """M3.2: problems with an answered part; empty means its evidence holds."""
    problems = []
    if not reply.answer.strip():
        problems.append("answer: empty")
    if reply.source_number not in sources:
        return problems + [f"source: [Source {reply.source_number}] does not exist"]
    quote = _normal(reply.evidence_quote).strip(' ".')
    if len(quote.split()) < MIN_QUOTE_WORDS:
        problems.append("quote: too short to be evidence")
    elif quote not in _normal(sources[reply.source_number]):
        problems.append(f"quote: not found in [Source {reply.source_number}]")
    # The answer's numbers must come from its own quote (or the question): the roadmap also allowed "the rule facts",
    # which let answer "24" (hours in term) pass with a quote about unlimited hours in breaks. Rules quoted as
    # [Source 0] still count, as the quote then is the rule.
    unsupported = _numbers(reply.answer) - _numbers(reply.evidence_quote) - _numbers(question)
    if unsupported:
        problems.append(f"numbers: {', '.join(sorted(unsupported))} not in the quote")
    return problems


async def answer_part(part: str, context: str, sources: Dict[int, str], rule_facts: Optional[str]) -> PartResult:
    """One part through the evidence step and the check. Model unavailable errors propagate (the endpoint maps them)."""
    from app.core.exceptions import LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    system, user = get_prompt("evidence_answer").render(question=part)
    try:
        reply = await llm_service.structured_call(EvidenceAnswer, system, user, context=context, role="answer",
                                                  max_tokens=350)
    except LLMStructuredOutputError as e:
        logger.warning(f"[EVIDENCE] unreadable output after retries: {e}")
        return PartResult(part, "invalid", problems=("schema: unreadable after retries",))
    if reply.not_covered:
        return PartResult(part, "not_covered")
    problems = check(reply, sources, part, rule_facts)
    answer = _CITATION.sub("", reply.answer).strip()
    if problems:
        corrected = _correct_source(reply, sources, part, rule_facts, problems)
        if corrected is not None:  # a real quote cited under the wrong number: keep it, under the right number
            result = PartResult(part, "verified", answer, reply.evidence_quote.strip(), corrected,
                                tuple(problems) + (f"source: corrected to [Source {corrected}]",))
            return await _check_claims(result, sources)
        return PartResult(part, "unverified", answer, reply.evidence_quote.strip(), reply.source_number, tuple(problems))
    return await _check_claims(PartResult(part, "verified", answer, reply.evidence_quote.strip(), reply.source_number),
                               sources)


async def _check_claims(result: PartResult, sources: Dict[int, str]) -> PartResult:
    """M4.1/M4.2 on a part whose evidence passed: each claim's code check against the cited passage blocks; the
    model check (VERIFY_CLAIMS_WITH_MODEL) only marks the part partially verified."""
    from dataclasses import replace

    from app.core.config import settings
    from app.services.claims import check_claim, code_check, split_claims

    passage = sources.get(result.source_number, "")
    claims = split_claims(result.answer) or [result.answer]
    blocked = [f"claim: {p}" for claim in claims for p in code_check(claim, passage, result.part)]
    if blocked:
        return replace(result, status="unverified", problems=result.problems + tuple(blocked), claims=len(claims))
    doubted = False
    if settings.VERIFY_CLAIMS_WITH_MODEL:
        for claim in claims:
            if not (await check_claim(claim, passage)).ok:
                doubted = True
                break  # one doubt is enough to label the part; saves the remaining calls
    return replace(result, partial=doubted, claims=len(claims))


def _correct_source(reply: EvidenceAnswer, sources: Dict[int, str], part: str, rule_facts: Optional[str],
                    problems: List[str]) -> Optional[int]:
    """The one other source that has the quote word for word, if the wrong number was the only problem."""
    if problems != [f"quote: not found in [Source {reply.source_number}]"]:
        return None
    quote = _normal(reply.evidence_quote).strip(' ".')
    holders = [n for n, text in sources.items() if n != reply.source_number and quote in _normal(text)]
    if len(holders) != 1:
        return None
    if check(reply.model_copy(update={"source_number": holders[0]}), sources, part, rule_facts):
        return None
    return holders[0]


def source_texts(rule_facts: Optional[str], chunks: List[Dict[str, Any]]) -> Dict[int, str]:
    """[Source N] -> its text: rule facts as 0, each chunk in the context by its number."""
    texts = {RULES_SOURCE: rule_facts} if rule_facts else {}
    for chunk in chunks:
        if chunk.get("_included_in_context") and chunk.get("_source_number"):
            texts[chunk["_source_number"]] = chunk.get("text", "")
    return texts


def compose(results: List[PartResult]) -> str:
    """The answer from checked parts only: each verified part with its citation and its quote; the others say so."""
    lines = []
    for result in results:
        if result.status == "verified":
            cite = "" if result.source_number == RULES_SOURCE else f" [Source {result.source_number}]"
            quote = result.quote.strip(' "')
            answer = _CITATION.sub("", result.answer).strip()  # only the checked citation is shown
            label = " (partially verified)" if result.partial else ""
            text = f'{answer}{cite}{label}\n> "{quote}"'
        elif result.status == "not_covered":
            text = NOT_COVERED_TEXT.format(part=result.part)
        else:
            text = UNVERIFIED_TEXT.format(part=result.part)
        lines.append(f"- {text}" if len(results) > 1 else text)
    return "\n\n".join(lines)
