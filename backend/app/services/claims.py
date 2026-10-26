"""
Claim checks (M4.1 + M4.2): after a part's evidence passes the code check (M3.2), each claim in its answer is checked
against the passage it cites, to catch claims that quote a real sentence but say something it doesn't.

M4.1 split_claims: the answer's sentences; a sentence with several number-bearing pieces ("$85 per person; families
     pay at most $170") is split at ';' and ', and' so each number is checked on its own. Deterministic.
M4.2 Two layers per claim, against the passage it cites (the chunk, or the rule facts for [Source 0]):
     code (blocks)   every number in the claim is in the passage, and "all / every / always / never / none /
                     everyone" only if the passage says it too; a claim failing this is not shown as verified
     model (advises) structured_call -> {supported: yes | partial | no}; anything but "yes" marks the part
                     "partially verified", never removes it.
     Why the model only advises (owner decision 2026-10-27, deviation from the roadmap's done-criterion): on
     tests/data/entailment_cases.json every local model rejected 21-25% of correct claims (target < 5%):
     llama3.2:3b 6/24, qwen3:4b 5/24, phi4-mini 6/24; qwen3 thinking mode took over 180 s per claim.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

YES, PARTIAL, NO, UNCHECKED = "yes", "partial", "no", "unchecked"
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(])")
_PIECE = re.compile(r";\s+|,\s+and\s+")
_NUMBER = re.compile(r"\d")
_MIN_CLAIM_WORDS = 3


class Entailment(BaseModel):
    supported: Literal["yes", "partial", "no"]
    reason: str = Field(default="", max_length=400)


@dataclass(frozen=True)
class ClaimVerdict:
    claim: str
    supported: str          # yes | partial | no | unchecked (the check itself failed)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.supported == YES


def split_claims(answer: str) -> List[str]:
    """Atomic claims of an answer: sentences, and number-bearing pieces of a sentence that has several."""
    claims: List[str] = []
    for sentence in _SENTENCE.split((answer or "").strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        pieces = [p.strip(" ,;") for p in _PIECE.split(sentence)]
        numbered = [p for p in pieces if _NUMBER.search(p)]
        if len(numbered) >= 2 and all(len(p.split()) >= _MIN_CLAIM_WORDS for p in pieces):
            claims.extend(pieces)
        elif len(sentence.split()) >= _MIN_CLAIM_WORDS:
            claims.append(sentence)
    return claims


_NUMBER_VALUE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ABSOLUTE = re.compile(r"\b(all|every|always|never|none|everyone|anyone|no one|any)\b", re.IGNORECASE)


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER_VALUE.findall(text or "")}


def code_check(claim: str, passage: str, question: str = "") -> List[str]:
    """The claim's hard checks: problems, or [] if it may be shown as verified. Numbers the user gave in the
    question ("after a 10-month diploma") may appear in the claim."""
    problems = []
    missing = _numbers(claim) - _numbers(passage) - _numbers(question)
    if missing:
        problems.append(f"numbers: {', '.join(sorted(missing))} not in the passage")
    lowered = (passage or "").lower()
    overreach = sorted({w.lower() for w in _ABSOLUTE.findall(claim)
                        if not re.search(rf"\b{re.escape(w.lower())}\b", lowered)})
    if overreach:
        problems.append(f"overreach: '{', '.join(overreach)}' not in the passage")
    return problems


async def check_claim(claim: str, passage: str) -> ClaimVerdict:
    """One claim against its passage. If the check can't run (unreadable output), the claim is 'unchecked'."""
    from app.core.exceptions import LLMStructuredOutputError
    from app.services.llm import llm_service
    from app.services.prompt_registry import get_prompt

    system, user = get_prompt("entailment").render(claim=claim)
    try:
        verdict = await llm_service.structured_call(Entailment, system, user, context=f"PASSAGE:\n{passage}",
                                                    role="verifier", max_tokens=120)
    except LLMStructuredOutputError as e:
        logger.warning(f"[CLAIMS] entailment output unreadable: {e}")
        return ClaimVerdict(claim, UNCHECKED, "unreadable")
    return ClaimVerdict(claim, verdict.supported, verdict.reason)
