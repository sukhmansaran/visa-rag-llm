"""
Triage (M1.1): does a question go down the fast path (today's pipeline) or the verified path?

Deterministic, no model call, microseconds: it runs on every question and must not slow the fast path.
A question is VERIFIED when any of these hold (each adds a reason):
  - legal_risk      refusal, misrepresentation, inadmissibility, enforcement, appeal (legal_disclaimer's detector)
                    plus faking documents and working illegally;
  - several_topics  a second question, introduced by "and <question word>", about a different topic;
  - eligibility     the asker's own eligibility or outcome: "can I get / apply as", "still get", "will I be banned",
                    "will my permit be approved";
  - freshness       "now", "current", "latest", "last year", "changed", a year, "still open";
  - premise         a claim to confirm ("…, right?", "…, correct?", "Since …") or a program IRCC has closed;
  - low_retrieval   retrieval confidence LOW or INSUFFICIENT (known only after retrieval; pass it in).
Otherwise FAST. Labels and the agreement test: tests/data/triage_labels.json, tests/test_triage.py.
"""

import contextvars
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional, Tuple

FAST, VERIFIED = "fast", "verified"

# The path this request actually runs on, set by whoever routed it (the verified answer job, M1.4); traces
# report it as `routed`. Anything not routed (direct chat endpoints, fast jobs) runs on the fast path.
_routed: contextvars.ContextVar[str] = contextvars.ContextVar("routed_path", default=FAST)


@contextmanager
def routed_as(path: str) -> Iterator[None]:
    if path not in (FAST, VERIFIED):
        raise ValueError(f"unknown path: {path}")
    token = _routed.set(path)
    try:
        yield
    finally:
        _routed.reset(token)


def routed_path() -> str:
    return _routed.get()

# Beyond legal_disclaimer's patterns: faking documents (any wording) and unauthorised work
_EXTRA_LEGAL = re.compile(
    r"\b(fake|forge|falsif\w*|doctor(ed)?|lie (to|on|about)|lying (to|on|about))\b"
    r"|\bwithout getting caught\b|\bwork(ing)? (illegally|under the table|off the books|without a permit)\b"
    r"|\bmore than (my|the) allowed hours\b",
    re.IGNORECASE)

# The asker's own eligibility or outcome
_ELIGIBILITY = re.compile(
    r"\b(am i|are we|is my \w+) (eligible|allowed|qualified)\b"
    r"|\b(do|would|will|could) (i|we) qualify\b"
    r"|\bcan (i|we) (still )?(get|apply|qualify|be eligible)\b"
    r"|\bstill (get|qualify|be eligible)\b"
    r"|\bwill (i|we) be (banned|eligible|approved|refused|accepted|deported)\b"
    r"|\bwill my [\w' -]{0,40}\b(be|get) (\w+ )?(approved|accepted|refused|rejected)\b",
    re.IGNORECASE)

_FRESHNESS = re.compile(
    r"\b(now|nowadays|currently|latest|recent|recently|today|this year|last year|so far this year)\b"
    r"|(?<!\bmy )(?<!\bour )\bcurrent\b"  # "the current processing time", not "my current permit"
    r"|\b(changed|changes to|has changed|new (rule|rules|policy|policies|law|laws|limit|cap|requirement|requirements))\b"
    r"|\bstill (open|available|valid|accepting|running|exists?)\b"
    r"|\bprocessing (times?|take|takes)\b"  # processing times are live data: they change every week
    r"|\b20(2[4-9]|3\d)\b",
    re.IGNORECASE)

# A claim the asker wants confirmed (a false premise is a classic way to mislead a small model)
_PREMISE = re.compile(
    r",?\s*\b(right|correct|true|is that (right|correct|true)|isn'?t (it|that) (right|true)?)\s*\?\s*$"
    r"|^\s*since\b",
    re.IGNORECASE)

# Topics, for "several topics": a second question only counts if it is about something else
_TOPICS = {
    "funds": r"\b(money|funds?|bank|gic|living expenses|financial)\b",
    "work": r"\b(work|working|job|jobs|hours)\b",
    "pal": r"\b(pal|tal|attestation letter)\b",
    "pgwp": r"\b(pgwp|post-graduation work permit|post graduation work permit)\b",
    "biometrics": r"\b(biometrics?|fingerprints?)\b",
    "language_test": r"\b(ielts|celpip|pte|tef|tcf|clb|nclc|language (test|level|results?))\b",
    "express_entry": r"\b(express entry|federal skilled|fsw|crs|canadian experience class)\b",
    "visitor": r"\b(visitor visa|eta|trv|super visa)\b",
    "exemption": r"\b(exempt|exemption)\b",
    "length": r"\bhow long\b|\bvalid(ity)?\b",
}
_TOPIC_RES = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _TOPICS.items()}
_SECOND_QUESTION = re.compile(
    r"(,\s*|\s)and (how|what|which|when|where|why|who|are|is|do|does|can|could|will|would|should)\b(.*)$",
    re.IGNORECASE)


@dataclass(frozen=True)
class TriageDecision:
    path: str
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def verified(self) -> bool:
        return self.path == VERIFIED


def _topics(text: str) -> set:
    return {name for name, pattern in _TOPIC_RES.items() if pattern.search(text)}


def _several_topics(query: str) -> bool:
    match = _SECOND_QUESTION.search(query)
    if not match:
        return False
    first, second = query[:match.start()], match.group(3)
    return bool(_topics(second) - _topics(first)) and bool(_topics(first))


def triage(query: str, retrieval_level: Optional[str] = None) -> TriageDecision:
    """Decide the path for one question. `retrieval_level`: HIGH | MEDIUM | LOW | INSUFFICIENT, if known."""
    from app.services.guardrails.legal_disclaimer import legal_disclaimer_engine
    from app.services.rule_engine import rule_engine

    text = " ".join((query or "").split())
    reasons = []
    categories, _ = legal_disclaimer_engine.detect_risk(text)
    if categories or _EXTRA_LEGAL.search(text):
        reasons.append("legal_risk")
    if _several_topics(text):
        reasons.append("several_topics")
    if _ELIGIBILITY.search(text):
        reasons.append("eligibility")
    if _FRESHNESS.search(text):
        reasons.append("freshness")
    if _PREMISE.search(text) or rule_engine.discontinued_program_fact(text):
        reasons.append("premise")
    if retrieval_level in ("LOW", "INSUFFICIENT"):
        reasons.append("low_retrieval")
    return TriageDecision(VERIFIED if reasons else FAST, tuple(reasons))
