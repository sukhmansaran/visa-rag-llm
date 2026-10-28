"""
Tool router (M5.2): which tools a question needs beyond the knowledge-base search every question gets.
Deterministic (principle 3):

  rules                  the rule engine has a fact for the question (the same code that supplies the facts decides,
                         so routing and answering can't disagree), or the question is personal (below)
  profile                the answer depends on the asker's own saved details ("am I eligible", "based on my
                         background", "with my test scores"); always with rules, which hold the criteria
  processing_times_link  the question asks how long IRCC takes (Pendu stores no processing-time figures)

Measured on tests/data/tool_choice_labels.json (labels written before this module; three held-out sets, each
measured once before being used): 100/114 (88%) exact-set, below the 95% target; the held-out sets alone scored
21/24, 27/30 and 24/30 when first measured. Nearly every miss is the rule engine's keyword matching: it fires on a
topic word whose facts don't answer the question (11 of 14), or misses a rewording (2). Matching rule sections by meaning is the fix, and it changes answers too, so it is its own step.
A model check of rule relevance (prompt rule_relevance, qwen3:4b) was tried and removed: it vetoed correct rule
matches (missing owner-reviewed facts costs more than an extra fact block).

Traced only (step `route`); answers don't use it yet.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

ROUTABLE = ("rules", "profile", "processing_times_link")  # knowledge_base_search always runs; live_fetch: M5.3

_PROCESSING_TIME = re.compile(
    r"\bprocessing\s+times?\b"
    r"|\bhow\s+long\s+(?:does|do|will|would)\s+(?:it|ircc|they|(?:the|my|an?)\s+\w+(?:\s+\w+)?)\s+(?:usually\s+)?take\b"
    r"|\bhow\s+long\s+(?:is|are)\s+(?:ircc|it|they|the\s+\w+)\s+(?:currently\s+)?taking\b"
    r"|\bhow\s+(?:many|much)\s+(?:weeks|months|days|time)\s+(?:does|do|will|would)\b.*\btake\b"
    r"|\bwait(?:ing)?\s+times?\b", re.IGNORECASE)

# The asker's own details decide the answer
_PERSONAL = re.compile(
    r"\b(?:am\s+i|are\s+we)\s+(?:eligible|qualified)\b"
    r"|\bdo\s+i\s+(?:qualify|meet|have\s+enough)\b"
    r"|\b(?:with|based\s+on|given|considering|looking\s+at|according\s+to)\s+my\s+"
    r"(?:profile|background|education|degree|work\s+experience|experience|test\s+scores?|scores?|ielts|celpip|"
    r"field\s+of\s+study|savings|qualifications?|situation|details|results)\b"
    r"|\bmy\s+profile\b", re.IGNORECASE)


def asks_processing_time(question: str) -> bool:
    return bool(_PROCESSING_TIME.search(question))


@dataclass(frozen=True)
class RoutePlan:
    tools: Tuple[str, ...]
    reasons: Tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> dict:
        return {"tools": list(self.tools), "reasons": list(self.reasons)}


async def has_rule_facts(question: str, country: str = "Canada") -> bool:
    """Whether the rule engine has facts for the question (the processing-times notice is the link tool's job)."""
    from app.services.intent_parser import intent_parser
    from app.services.rule_engine import rule_engine

    if rule_engine.approval_guarantee_fact(question) or rule_engine.discontinued_program_fact(question):
        return True
    parsed = await intent_parser.parse_intent(question)
    facts = rule_engine.try_rule_answer(parsed.get("intent", "general"), country,
                                        parsed.get("visa_type", "Student"), query=question)
    return bool(facts) and "PROCESSING TIMES" not in facts


async def route(question: str, country: str = "Canada") -> RoutePlan:
    tools: List[str] = []
    reasons: List[str] = []
    processing = bool(_PROCESSING_TIME.search(question))
    if processing:
        tools.append("processing_times_link")
        reasons.append("processing_time")
    if _PERSONAL.search(question):
        tools += ["profile", "rules"]
        reasons.append("personal")
    # the rules hold no processing times (by design), so a processing-time question gets the link, not the visa or
    # permit facts its topic word matched. Limit: "how much money, and how long does it take?" loses the rules here
    elif not processing and await has_rule_facts(question, country):
        tools.append("rules")
        reasons.append("rule_fact")
    return RoutePlan(tuple(sorted(tools)), tuple(reasons))
