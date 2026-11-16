"""A fast-path answer keeps no money amount its sources don't state (app/services/amount_guard.py)."""

import pytest

from app.core.config import settings
from app.services import amount_guard
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.step_labels import describe
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

# IRCC's fee table as retrieved: the Start-up Visa row came without its amount
FEE_TABLE = ("Business immigration. These fees apply to: Start-up visa. Fees | $CAN\n**Your application**\n"
             "This amount includes the processing fee and the right of permanent residence fee.")
VISITOR = "Visitor visa processing fee | Individual: $100. Biometrics fee | Individual: $85"


def test_stated_amounts_are_kept_as_they_are():
    answer = "- The visitor visa fee is $100.\n- Biometrics cost $85 per person."
    assert amount_guard.check(answer, VISITOR) == (answer, 0)


def test_an_amount_the_sources_dont_state_is_removed_and_the_answer_says_so():
    answer = ("- The government fee for the Start-up Visa program is $1,225.\n"
              "- This amount includes the processing fee and the right of permanent residence fee.")
    text, removed = amount_guard.check(answer, FEE_TABLE)
    assert removed == 1 and "1,225" not in text
    assert text.startswith("- This amount includes the processing fee")
    assert "I couldn't find that amount in the official sources" in text


def test_only_the_sentence_with_the_amount_goes():
    answer = "- You pay one fee. It is CAD 1325 per person. Pay it online."
    text, removed = amount_guard.check(answer, FEE_TABLE)
    assert removed == 1 and text.splitlines()[0] == "- You pay one fee. Pay it online."


def test_formats_are_compared_by_value():
    assert amount_guard.check("It costs $1225.00.", "Fee: $1,225")[1] == 0
    assert amount_guard.check("You need 23,448 dollars.", "CAD $23448 for one person")[1] == 0
    assert amount_guard.check("You need 25,000 Canadian dollars.", "CAD $23,448")[1] == 1


def test_an_amount_the_asker_gave_may_be_repeated():
    assert amount_guard.check("Yes, $10,000 is less than required.", "CAD $23,448",
                              question="Is $10,000 enough?")[1] == 0


def test_numbers_that_are_not_amounts_are_left_alone():
    answer = "Add your scores: 7 + 7 + 7 + 7 = 28 points. Wait 30 days."
    assert amount_guard.check(answer, "Speaking 7")[1] == 0


def test_an_answer_that_was_only_the_amount_becomes_the_note():
    text, removed = amount_guard.check("The fee is $1,225.", FEE_TABLE)
    assert removed == 1 and text == amount_guard.NOTE.format(what="that amount", it="it")


def test_label():
    assert describe({"name": "amount_guard", "removed": 2}) == "Left out 2 amounts the official sources don't state"
    assert describe({"name": "amount_guard", "removed": 0}) is None


# --- in the pipeline (fast path, both modes) ---

QUESTION = "What is the government fee for the Start-up Visa program?"
INVENTED = "- The government fee for the Start-up Visa program is $1,225.\n- It includes the right of PR fee."


@pytest.fixture
def fast(fake_llm, monkeypatch):
    async def retrieve(query, **_):
        return [{"text": FEE_TABLE, "score": 0.85, "authority_tier": 1, "freshness_weight": 1.0,
                 "metadata": {"url": "https://ircc.canada.ca/english/information/fees/fees.asp", "title": "Fee list"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(rp.rule_engine, "try_rule_answer", lambda *a, **k: None)
    fake_llm.when(r"User Question:", INVENTED)
    intent_cache.clear()
    yield fake_llm
    intent_cache.clear()


async def _ask(stream: bool):
    trace = TraceRecorder("test", query=QUESTION)
    with activate_trace(trace), routed_as("fast"):
        if not stream:
            return (await rp.rag_pipeline.process_query(QUESTION, db=object()))["answer"], trace
        done = {}
        async for event in rp.rag_pipeline.process_query_stream(QUESTION, db=object()):
            if event.get("type") == "done":
                done = event
        return done["full_response"], trace


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_the_fast_path_drops_an_invented_fee(fast, stream):
    answer, trace = await _ask(stream)
    assert "1,225" not in answer and "I couldn't find that amount" in answer
    assert next(s for s in trace.steps if s["name"] == "amount_guard")["removed"] == 1


@pytest.mark.asyncio
async def test_the_guard_can_be_switched_off(fast, monkeypatch):
    monkeypatch.setattr(settings, "AMOUNT_GUARD", False)
    answer, _ = await _ask(False)
    assert "$1,225" in answer
