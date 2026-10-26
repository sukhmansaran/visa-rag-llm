"""
Iteration policy (M4.3): a verified-path part that came back unverified, not covered or unreadable gets one more round.

  1. Refine the query and re-retrieve: the part with its acronyms spelled out (glossary expansions) and plain words
     for its topics, retrieving past the chunks already shown so the retry sees different evidence. The evidence
     step runs again on rule facts + the new chunks; the retry also gives the model another try, which counters
     the run-to-run instability found in the M4.2 evaluation (a part verified in one session, not covered in the next).
  2. Live fetch: M5 (not built yet).
  3. Still failing: the part says so ("couldn't check" / "not covered"), as composed by evidence.compose.
At most VERIFIED_MAX_ROUNDS rounds, and no retry once VERIFIED_RETRY_BEFORE_SECONDS of the request have passed.
"""

from typing import Dict, List

from app.services.topics import detect_topics

# Plain words that IRCC pages use for each topic, added to a retry's search
TOPIC_WORDS: Dict[str, str] = {
    "funds": "proof of financial support living expenses",
    "work": "work off campus hours international students",
    "pal": "provincial attestation letter",
    "biometrics": "biometrics fingerprints photo",
    "pgwp": "post-graduation work permit eligibility length",
    "extension": "extend study permit maintained status",
    "visitor_visa": "visitor visa electronic travel authorization",
    "express_entry": "Express Entry eligibility",
    "language_tests": "language test results",
    "processing_times": "processing times",
    "study_permit": "study permit application",
}

_RANK = {"verified": 3, "not_covered": 1, "unverified": 1, "invalid": 0}


def refine_query(part: str) -> str:
    """The part, its acronyms spelled out and its topics' plain words: a different search than the first round."""
    detected = detect_topics(part)
    extra: List[str] = []
    lowered = part.lower()
    for term in detected.terms:
        if term.expansion.lower() not in lowered:
            extra.append(term.expansion)
    for topic in detected.topics:
        words = TOPIC_WORDS.get(topic)
        if words and words.lower() not in lowered:
            extra.append(words)
    return " ".join([part, *dict.fromkeys(extra)])


def better(first, retry):
    """Keep the retry only if it is better: verified beats everything; otherwise the first round stands."""
    return retry if _RANK.get(retry.status, 0) > _RANK.get(first.status, 0) else first
