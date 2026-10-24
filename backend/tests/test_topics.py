"""M2.1 topic detector: recall on the labelled evaluation questions, held-out questions, traps, glossary terms."""

import json
import time
from pathlib import Path

import pytest

from app.services.glossary import glossary
from app.services.topics import TERM_TOPICS, TOPICS, detect_topics

DATA = Path(__file__).parent / "data"
CASES = {c["id"]: c for c in json.loads((DATA / "rag_eval_set.json").read_text(encoding="utf-8"))["cases"]}
LABELS = json.loads((DATA / "topic_labels.json").read_text(encoding="utf-8"))["labels"]
HOLDOUT = json.loads((DATA / "topic_holdout.json").read_text(encoding="utf-8"))


def score(labelled):
    """(recall, precision, misses) over {question: [topics]}."""
    tp = fn = fp = 0
    misses = []
    for question, want in labelled.items():
        got, want = set(detect_topics(question).topics), set(want)
        tp, fn, fp = tp + len(got & want), fn + len(want - got), fp + len(got - want)
        if got != want:
            misses.append((question, sorted(want - got), sorted(got - want)))
    return tp / max(1, tp + fn), tp / max(1, tp + fp), misses


def test_labels_use_known_topics_and_cases():
    assert set(LABELS) <= set(CASES)
    for labelled in (LABELS, *[HOLDOUT[r] for r in ("round_1", "round_2", "round_3")]):
        assert all(set(topics) <= set(TOPICS) for topics in labelled.values())


def test_every_topic_is_labelled_somewhere():
    used = {t for topics in LABELS.values() for t in topics}
    assert used == set(TOPICS)


def test_multi_part_cases_have_every_topic_found():
    """The roadmap's done-criterion: >= 95% topic recall on the multi-part evaluation cases."""
    multi = {CASES[cid]["question"]: topics for cid, topics in LABELS.items() if CASES[cid]["type"] == "multi_part"}
    recall, _, misses = score(multi)
    assert recall >= 0.95, misses


def test_evaluation_questions():
    recall, precision, misses = score({CASES[cid]["question"]: topics for cid, topics in LABELS.items()})
    assert recall >= 0.95 and precision >= 0.95, misses


@pytest.mark.parametrize("round_name,min_recall", [("round_1", 0.95), ("round_2", 0.9), ("round_3", 0.85)])
def test_held_out_questions(round_name, min_recall):
    """round_3 was never used to change a pattern (90.5% recall when written): its floor catches regressions while
    the honest misses (implied meanings: 'drive for Uber while studying') are left to M2.2's model decomposition."""
    recall, precision, misses = score(HOLDOUT[round_name])
    assert recall >= min_recall and precision >= 0.95, misses


@pytest.mark.parametrize("question", [
    "Does a job offer give me extra points under the Federal Skilled Worker Program?",  # not working while studying
    "How much is the application fee for a study permit?",                              # a fee is not proof of funds
    "How do I get a bank account in Canada as a student?",                              # opening an account
    "How much money do I need to show for a Canadian study permit?",                    # a passing "study permit"
    "Can my pal come with me to Canada?",                                               # the word, not the acronym
])
def test_traps(question):
    topics = set(detect_topics(question).topics)
    assert "work" not in topics and "study_permit" not in topics and "pal" not in topics
    if "money" not in question:
        assert "funds" not in topics


def test_topics_are_in_order_of_mention_with_the_words_that_matched():
    result = detect_topics("Do I need biometrics, and how much money do I need for a PAL?")
    assert result.topics == ("biometrics", "funds", "pal")
    assert result.mentions == {"biometrics": "biometrics", "funds": "money", "pal": "PAL"}


def test_glossary_spellings_count_and_expansions_come_from_the_glossary():
    result = detect_topics("How long is a post-grad work permit after a 2-year program, and is a GIC required?")
    assert result.topics == ("pgwp", "funds")
    assert result.expansions() == {"PGWP": glossary()["PGWP"].expansion, "GIC": glossary()["GIC"].expansion}


def test_term_topics_name_real_glossary_terms_and_topics():
    assert set(TERM_TOPICS) <= set(glossary())
    assert set(TERM_TOPICS.values()) <= set(TOPICS)


def test_empty_and_unrelated_input():
    assert detect_topics("").topics == () and detect_topics(None).topics == ()
    assert detect_topics("Can I bring my dog to Canada?").topics == ()


def test_fast_enough_for_every_question():
    questions = [c["question"] for c in CASES.values()]
    detect_topics(questions[0])
    start = time.perf_counter()
    for _ in range(10):
        for question in questions:
            detect_topics(question)
    assert (time.perf_counter() - start) / (10 * len(questions)) < 0.005
