"""
Topic detector (M2.1): which immigration topics a question asks about, by whole-word patterns, no model call.

Used by decomposition (M2.2): a split may have at most one sub-question per detected topic plus one, and every
sub-question must map to a detected topic or the original question. Also returns the glossary terms the question
uses (with their official expansions), so a split never expands an acronym differently from the glossary.

Topics (one name each, stable: traces and labels use them):
  funds             proof of funds, money, bank statements, GIC, living expenses
  work              working while studying: hours, on/off campus, SIN
  pal               provincial / territorial attestation letter
  biometrics        biometrics, fingerprints
  pgwp              post-graduation work permit
  extension         extending or restoring status
  visitor_visa      visitor visa, TRV, eTA, super visa
  express_entry     Express Entry, FSW/FST/CEC, CRS, ITA, ECA, TEER/NOC
  language_tests    IELTS, CELPIP, PTE, TEF/TCF, CLB/NCLC, language results
  processing_times  how long an application takes to process
  study_permit      the study permit application itself: approval, refusal, letter of acceptance, SDS
                    (not a passing mention such as "funds for a study permit")
Labels and the recall test: tests/data/topic_labels.json, tests/test_topics.py.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from app.services.glossary import Term, term_mentions

_I = re.IGNORECASE

# Acronyms are matched case-sensitively (as in the glossary): "pal" the word is not PAL
_PATTERNS: Dict[str, List[re.Pattern]] = {
    "funds": [
        re.compile(r"\b(proof of )?funds\b|\bmoney\b|\bcash\b|\bsavings\b|\bliving expenses\b|\bfinancial\b"
                   r"|\btuition\b", _I),
        re.compile(r"\b(in|into|on) (my|your|the|our) (bank |savings )?accounts?\b", _I),
        # not a bare "bank account": opening one ("get a bank account in Canada") is not proof of funds
        re.compile(r"\bbank (statements?|balance)\b|\b(minimum|account) balance\b|\bguaranteed investment certificates?\b", _I),
        re.compile(r"\bGICs?\b|\$\s?\d"),
    ],
    "work": [
        re.compile(r"\b(off|on)[- ]campus\b", _I),
        re.compile(r"\bhours?\b[^.?!]{0,40}\b(work|week)\b|\bwork(ing)?\b[^.?!]{0,40}\bhours?\b", _I),
        re.compile(r"\bwork(ing)? (while|during) (my |your )?(studies|studying|classes|semester|program)\b", _I),
        re.compile(r"\bwork(ing)? (full|part)[- ]time\b|\bwork(ing)?\b[^.?!]{0,30}\bbreaks?\b", _I),
        re.compile(r"\bsocial insurance number\b|\bpart-time jobs?\b", _I),
        re.compile(r"\bSIN\b"),
    ],
    "pal": [
        re.compile(r"\b(provincial|territorial) attestation( letters?)?\b|\battestation letters?\b", _I),
        re.compile(r"\b(PAL|TAL)s?\b"),
    ],
    "biometrics": [re.compile(r"\bbiometrics?\b|\bfingerprints?\b", _I)],
    "pgwp": [
        re.compile(r"\bpost[- ]graduation work permits?\b", _I),
        re.compile(r"\bPGWPs?\b"),
    ],
    "extension": [
        re.compile(r"\bextend(ing)?\b[^.?!]{0,30}\b(permit|stay|status|visa)\b|\bextensions?\b", _I),
        re.compile(r"\b(be|get|been|got) extended\b", _I),
        re.compile(r"\b(permit|visa|status)\b[^.?!]{0,15}\b(will |is going to )?expir(e|es|ing)\b", _I),
        re.compile(r"\brestor(e|ing|ation)\b[^.?!]{0,30}\bstatus\b|\bmaintained status\b", _I),
    ],
    "visitor_visa": [
        re.compile(r"\b(visitor|tourist|super) visas?\b|\belectronic travel authori[sz]ation\b", _I),
        re.compile(r"\btravell?ers? to canada\b|\bvisit(ing)? canada\b", _I),
        re.compile(r"\b(TRV|eTA)s?\b"),
    ],
    "express_entry": [
        re.compile(r"\bexpress entry\b|\bfederal skilled (worker|trades)\b|\bcanadian experience class\b", _I),
        re.compile(r"\bcomprehensive ranking\b|\binvitations? to apply\b|\bselection grid\b", _I),
        re.compile(r"\beducational credential assessment\b", _I),
        re.compile(r"\b(FSWP?|FST|CEC|CRS|ITA|ECA|TEER|NOC)s?\b"),
    ],
    "language_tests": [
        re.compile(r"\blanguage (tests?|levels?|results?|scores?|proficiency|requirements?)\b", _I),
        re.compile(r"\b(IELTS|CELPIP|PTE|TEF|TCF|CLB|NCLC)\b"),
    ],
    "processing_times": [
        re.compile(r"\bprocessing (times?|take|takes)\b|\bhow long\b[^.?!]{0,40}\bto (be )?process(ed)?\b", _I),
    ],
    "study_permit": [
        re.compile(r"\bstudy permit applications?\b|\bapply for a study permit\b", _I),
        re.compile(r"\bstudy permit\b[^.?!]{0,40}\b(approved|refused|rejected|approval|refusal)\b", _I),
        re.compile(r"\bletters? of acceptance\b|\bstatement of purpose\b|\bstudent direct stream\b", _I),
        re.compile(r"\b(LOA|SOP|SDS)s?\b"),
    ],
}

TOPICS: Tuple[str, ...] = tuple(_PATTERNS)

# Glossary terms that name a topic: any spelling the glossary knows (acronym, official expansion, alias such as
# "post-grad work permit") counts as a mention. Terms that are not a topic of their own (DLI, IRCC, LMIA) are absent.
TERM_TOPICS: Dict[str, str] = {
    "PAL": "pal", "TAL": "pal", "PGWP": "pgwp", "GIC": "funds", "eTA": "visitor_visa", "TRV": "visitor_visa",
    "CRS": "express_entry", "ITA": "express_entry", "FSW": "express_entry", "FST": "express_entry",
    "CEC": "express_entry", "ECA": "express_entry", "TEER": "express_entry", "NOC": "express_entry",
    "CLB": "language_tests", "SDS": "study_permit",
}


@dataclass(frozen=True)
class TopicResult:
    topics: Tuple[str, ...]                                   # in order of first mention
    mentions: Dict[str, str] = field(default_factory=dict)    # topic -> the words that matched first
    terms: Tuple[Term, ...] = field(default_factory=tuple)    # glossary terms used, with official expansions

    def expansions(self) -> Dict[str, str]:
        """Acronym -> official expansion, for every glossary term in the question."""
        return {term.acronym: term.expansion for term in self.terms}


def detect_topics(text: str) -> TopicResult:
    text = " ".join((text or "").split())
    first: Dict[str, Tuple[int, str]] = {}

    def note(topic: str, start: int, words: str) -> None:
        if topic not in first or start < first[topic][0]:
            first[topic] = (start, words)

    for topic, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                note(topic, match.start(), match.group(0))
    mentions = term_mentions(text)
    for term, start, words in mentions:
        if term.acronym in TERM_TOPICS:
            note(TERM_TOPICS[term.acronym], start, words)
    ordered = sorted(first.items(), key=lambda item: item[1][0])
    return TopicResult(topics=tuple(topic for topic, _ in ordered),
                       mentions={topic: words for topic, (_, words) in ordered},
                       terms=tuple(term for term, _, _ in mentions))
