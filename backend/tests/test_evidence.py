"""M3 evidence answers: the code check (synthetic detection set), source correction, composition, the pipeline."""

import pytest

from app.services import evidence as ev
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

RULES = ("- Allowed Working Hours: Eligible full-time students are permitted to work up to 24 hours per week "
         "off-campus during regular semesters.")
SOURCES = {
    0: RULES,
    1: "You **don’t** need a PAL or TAL when you apply for a study permit to attend one of these programs if "
       "you’re applying after January 1, 2026. You still need an LOA from the school.",
    2: "If you’re working during a break scheduled by your DLI, such as summer and winter holidays, or a reading "
       "week, you can work **unlimited** hours off campus.",
    3: "The minimum proof of funds for living expenses outside Quebec is CAD $23,448 per year for a single applicant.",
}
QUESTION = "How many hours can I work off campus?"


def reply(answer, quote, source):
    return ev.EvidenceAnswer(answer=answer, evidence_quote=quote, source_number=source)


# ---------------------------------------------------------------- M3.2: what the check must catch (100%)

FABRICATED = [
    # (answer, quote, source, the problem it must report)
    ("You can work 40 hours a week.", "Students can work up to 40 hours per week during classes.", 0, "quote: not found"),
    ("You need a PAL.", "Every master's student needs a PAL from their province.", 1, "quote: not found"),
    ("You can work 20 hours.", "Students may work up to 20 hours per week off campus.", 2, "quote: not found"),
    ("Funds are $10,000.", "The minimum proof of funds is CAD $10,000 per year.", 3, "quote: not found"),
    # a real sentence, slightly reworded
    ("No PAL needed.", "You do not need a PAL or TAL when you apply for a study permit to attend these programs.", 1,
     "quote: not found"),
    # a real sentence cut off and re-joined
    ("Unlimited in breaks.", "If you’re working during a break you can work unlimited hours off campus.", 2,
     "quote: not found"),
]
WRONG_SOURCE = [
    ("No PAL needed after 2026.", "You don’t need a PAL or TAL when you apply for a study permit to attend one of these "
     "programs if you’re applying after January 1, 2026.", 42, "source: [Source 42] does not exist"),
    ("No PAL needed.", "You don’t need a PAL or TAL when you apply for a study permit to attend one of these programs",
     -1, "source: [Source -1] does not exist"),
]
OTHER = [
    ("24 hours.", "you can work unlimited hours off campus", 2, "numbers: 24 not in the quote"),  # answer vs quote
    ("Unlimited.", "unlimited hours", 2, "quote: too short"),
    ("", "You still need an LOA from the school.", 1, "answer: empty"),
    ("You need $25,000.", "The minimum proof of funds for living expenses outside Quebec is CAD $23,448 per year for "
     "a single applicant.", 3, "numbers: 25000 not in the quote"),
]


@pytest.mark.parametrize("answer,quote,source,problem", FABRICATED + WRONG_SOURCE + OTHER)
def test_the_check_catches(answer, quote, source, problem):
    problems = ev.check(reply(answer, quote, source), SOURCES, QUESTION, RULES)
    assert any(p.startswith(problem) for p in problems), problems


def test_detection_rate_on_the_synthetic_set_is_100_percent():
    bad = FABRICATED + WRONG_SOURCE + OTHER
    caught = sum(bool(ev.check(reply(a, q, s), SOURCES, QUESTION, RULES)) for a, q, s, _ in bad)
    assert caught == len(bad) == 12


@pytest.mark.parametrize("answer,quote,source", [
    # the page has "**don’t**" and curly quotes; the model copies plain text
    ("You don't need a PAL after January 1, 2026.", "You don't need a PAL or TAL when you apply for a study permit to "
     "attend one of these programs if you're applying after January 1, 2026.", 1),
    ("Unlimited hours during scheduled breaks.", "you can work unlimited hours off campus", 2),
    ("Up to 24 hours per week.", "permitted to work up to 24 hours per week off-campus during regular semesters", 0),
    ("$23,448 a year for one person.", "  The minimum proof of funds for living expenses outside Quebec is CAD "
     "$23,448 per year   for a single applicant.  ", 3),
])
def test_genuine_quotes_pass(answer, quote, source):
    assert ev.check(reply(answer, quote, source), SOURCES, QUESTION, RULES) == []


# ---------------------------------------------------------------- the evidence step

@pytest.mark.asyncio
async def test_a_real_quote_under_the_wrong_number_is_corrected_and_recorded(fake_llm):
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    fake_llm.when(r"Question: Do I need a PAL", {
        "answer": "No PAL is needed after January 1, 2026.", "source_number": 2,
        "evidence_quote": "You don’t need a PAL or TAL when you apply for a study permit to attend one of these programs "
                          "if you’re applying after January 1, 2026."})
    result = await ev.answer_part("Do I need a PAL?", "ctx", SOURCES, RULES)
    assert (result.status, result.source_number) == ("verified", 1)
    assert "source: corrected to [Source 1]" in result.problems


@pytest.mark.asyncio
@pytest.mark.parametrize("model_reply,status", [
    ({"not_covered": True}, "not_covered"),
    ({"answer": "40 hours.", "evidence_quote": "You can work 40 hours during classes.", "source_number": 2}, "unverified"),
    ("this is not json", "invalid"),
])
async def test_part_outcomes(fake_llm, model_reply, status):
    fake_llm.when(r"Question: How many hours", model_reply)
    result = await ev.answer_part(QUESTION, "ctx", SOURCES, RULES)
    assert result.status == status
    assert "How many hours" not in str(result.summary())  # traces carry no user text


def test_compose_states_what_was_checked_and_what_was_not():
    results = [
        ev.PartResult("How many hours in term?", "verified", "Up to 24 hours a week [Source 4].",
                      "work up to 24 hours per week off-campus during regular semesters", 0),
        ev.PartResult("In breaks?", "verified", "Unlimited.", "you can work **unlimited** hours off campus", 2),
        ev.PartResult("What is the processing time?", "not_covered"),
        ev.PartResult("Can I work 40 hours?", "unverified"),
    ]
    text = ev.compose(results)
    assert '- Up to 24 hours a week.\n> "work up to 24 hours' in text      # rules: no [Source 0]; model's own tag dropped
    assert "Unlimited. [Source 2]" in text
    assert "don't cover this: What is the processing time?" in text
    assert "couldn't check an answer to this against the official sources: Can I work 40 hours?" in text


# ---------------------------------------------------------------- in the pipeline

@pytest.fixture
def scripted(fake_llm, monkeypatch):
    async def retrieve(query, **_):
        return [{"text": SOURCES[2], "score": 0.86, "authority_tier": 1, "freshness_weight": 1.0,
                 "metadata": {"url": "https://www.canada.ca/work.html", "title": "Work"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"User Question:", "You can work unlimited hours in breaks [Source 1].")
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})  # M4.2 claim check
    return fake_llm


async def run(question, path):
    intent_cache.clear()
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace), routed_as(path):
        result = await rp.rag_pipeline.process_query(question, db=object())
    return result, trace


@pytest.mark.asyncio
async def test_the_verified_path_answers_from_checked_evidence(scripted):
    scripted.when(r"Question: How many hours can I work during my winter break", {
        "answer": "You can work unlimited hours during scheduled breaks.", "source_number": 1,
        "evidence_quote": "you can work unlimited hours off campus"})
    result, trace = await run("How many hours can I work during my winter break?", "verified")
    assert "unlimited hours during scheduled breaks. [Source 1]" in result["answer"]
    assert '> "you can work unlimited hours off campus"' in result["answer"]
    assert [s["status"] for s in trace.steps if s["name"] == "evidence"] == ["verified"]
    assert "generation" not in [s["name"] for s in trace.steps]
    assert result["metrics"]["evidence"] == {"verified": 1, "not_covered": 0, "unverified": 0, "invalid": 0, "partial": 0,
                                         "improved_by_retry": 0}


@pytest.mark.asyncio
async def test_the_fast_path_still_writes_the_answer(scripted):
    result, trace = await run("How many hours can I work during my winter break?", "fast")
    assert "evidence" not in [s["name"] for s in trace.steps] and "generation" in [s["name"] for s in trace.steps]
    assert "evidence" not in result["metrics"]


@pytest.mark.asyncio
async def test_unreadable_evidence_falls_back_to_writing_the_answer(scripted):
    scripted.when(r"Question: How many hours can I work during my winter break", "not json")
    result, trace = await run("How many hours can I work during my winter break?", "verified")
    assert "generation" in [s["name"] for s in trace.steps]
    assert result["answer"].startswith("You can work unlimited hours in breaks")


@pytest.mark.asyncio
async def test_the_streaming_verified_path_sends_the_checked_answer(scripted):
    scripted.when(r"Question: How many hours can I work during my winter break", {"not_covered": True})
    intent_cache.clear()
    trace = TraceRecorder("test", query="x")
    with activate_trace(trace), routed_as("verified"):
        events = [e async for e in rp.rag_pipeline.process_query_stream(
            "How many hours can I work during my winter break?", db=object())]
    assert events[-1]["type"] == "done"
    assert events[-1]["full_response"].startswith("The official sources I have don't cover this")


@pytest.mark.asyncio
async def test_a_premise_question_with_nothing_verified_is_answered_as_before(scripted):
    """'The funds are $10,000, right?' got 'not covered' (no source states the false claim); that is not trusted."""
    question = "Students can work 40 hours a week during breaks, right?"
    scripted.when(r"Question: Students can work 40 hours", {"not_covered": True})
    result, trace = await run(question, "verified")
    assert next(s for s in trace.steps if s["name"] == "triage")["reasons"] == ["premise"]
    assert "generation" in [s["name"] for s in trace.steps]
    assert result["answer"].startswith("You can work unlimited hours in breaks")
    assert result["metrics"]["evidence"]["premise_fallback"] is True


@pytest.mark.asyncio
async def test_a_question_without_a_premise_keeps_its_not_covered_answer(scripted):
    scripted.when(r"Question: Can I volunteer", {"not_covered": True})
    result, _ = await run("Can I volunteer at a charity while on a study permit?", "verified")
    assert result["answer"].startswith("The official sources I have don't cover this")


@pytest.mark.asyncio
async def test_a_processing_time_question_is_answered_by_code_with_irccs_tool(scripted):
    """Pendu stores no processing times (by design): the evidence step could only call it uncheckable (M5.3)."""
    scripted.when(r"Question: What is the processing time", {"not_covered": True})
    result, _ = await run("What is the processing time for a study permit from India?", "verified")
    assert result["answer"].startswith("The official sources I have don't cover current processing times")
    assert "check-processing-times.html" in result["answer"] and '> ""' not in result["answer"]
