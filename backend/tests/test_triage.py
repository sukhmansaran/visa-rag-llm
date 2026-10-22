"""M1.1 triage: agreement with the hand labels, each signal, and no slowdown on the fast path."""

import json
import time
from pathlib import Path

import pytest

from app.services.triage import FAST, VERIFIED, triage

DATA = Path(__file__).parent / "data"
CASES = {c["id"]: c for c in json.loads((DATA / "rag_eval_set.json").read_text(encoding="utf-8"))["cases"]}
LABELS = json.loads((DATA / "triage_labels.json").read_text(encoding="utf-8"))["labels"]


def test_labels_refer_to_eval_cases():
    assert set(LABELS) <= set(CASES)
    assert all(label["path"] in (FAST, VERIFIED) for label in LABELS.values())


def test_agrees_with_hand_labels():
    misses = [(cid, label["path"], triage(CASES[cid]["question"]).path)
              for cid, label in LABELS.items() if triage(CASES[cid]["question"]).path != label["path"]]
    agreement = 1 - len(misses) / len(LABELS)
    # Known honest miss: distractor_ielts_academic (a false premise with no cue word)
    assert agreement >= 0.95, f"agreement {agreement:.1%}, misses: {misses}"


@pytest.mark.parametrize("question,reason", [
    ("My study permit was refused, what can I do?", "legal_risk"),
    ("Can I fake a bank statement?", "legal_risk"),
    ("How do I work under the table without getting caught?", "legal_risk"),
    ("What are the funds needed, and how many hours can I work?", "several_topics"),
    ("Am I eligible for a PGWP?", "eligibility"),
    ("Can I still get a PGWP if I studied part-time?", "eligibility"),
    ("Will my study permit be approved?", "eligibility"),
    ("What is the current processing time?", "freshness"),
    ("Did the work hour limit change in 2025?", "freshness"),
    ("Is the Student Direct Stream still open?", "freshness"),
    ("How long does Canada student visa processing take?", "freshness"),
    ("What are the processing times for a visitor visa from India?", "freshness"),
    ("Students can work 40 hours, right?", "premise"),
    ("Since the funds are $10,000, how much do I need for two?", "premise"),
    ("How do I apply through the Student Direct Stream?", "premise"),
])
def test_signal(question, reason):
    decision = triage(question)
    assert decision.path == VERIFIED and reason in decision.reasons, decision


@pytest.mark.parametrize("question", [
    "How many hours can I work off campus during a regular term?",
    "Can I work more hours during scheduled breaks?",
    "How do I extend my current study permit?",
    "How much does biometrics cost for one person and for a family?",
    "What is a new program's PAL requirement?",
    "How long is a PGWP for a two-year program?",
])
def test_plain_questions_stay_fast(question):
    assert triage(question).path == FAST, triage(question)


def test_the_chat_pages_suggested_questions_are_plain_fast_questions():
    """Suggestions are what new users click first: none may be about a closed program or need verification
    (the page suggested "the SDS program", closed by IRCC, until the M1 review)."""
    import re

    page = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "app" / "chat" / "page.tsx").read_text(encoding="utf-8")
    suggestions = re.findall(r'handleQuickQuestion\("([^"]+)"\)', page)
    assert len(suggestions) >= 3
    for question in suggestions:
        assert triage(question).path == FAST, (question, triage(question))


def test_low_retrieval_confidence_sends_to_verified():
    question = "How many hours can I work off campus during a regular term?"
    assert triage(question, retrieval_level="HIGH").path == FAST
    for level in ("LOW", "INSUFFICIENT"):
        assert triage(question, retrieval_level=level).reasons == ("low_retrieval",)


def test_empty_question_is_fast():
    assert triage("").path == FAST and triage(None).path == FAST


def test_fast_enough_for_every_question():
    questions = [c["question"] for c in CASES.values()]
    triage(questions[0])  # warm the lazy imports
    start = time.perf_counter()
    for _ in range(20):
        for question in questions:
            triage(question)
    per_question = (time.perf_counter() - start) / (20 * len(questions))
    assert per_question < 0.005, f"{per_question * 1000:.2f} ms per question"
