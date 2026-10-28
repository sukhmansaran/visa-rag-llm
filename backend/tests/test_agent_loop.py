"""M5.3 agent loop: the model chooses actions, code checks and runs them; the answer still goes through the evidence
step and its checks. The model is scripted (FakeLLM)."""

import pytest

from app.agent import loop
from app.core.config import settings
from app.core.exceptions import AIServiceUnavailableError
from app.services import rag_pipeline as rp
from app.services import tools
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

DECIDE = r"planner of a Canadian immigration assistant"
FUNDS = "How much money do I need to show if my family is coming with me?"
PAGE = {"text": "Your spouse or common-law partner may be eligible for an open work permit.", "score": 0.8,
        "authority_tier": 1, "metadata": {"url": "https://www.canada.ca/spouse.html", "title": "Spouse"}}
FACTS = "OFFICIAL IRCC REGULATORY FACTS — FUNDS:\n- A single applicant needs CAD $23,448."


def act(action, query="", thought=""):
    return {"thought": thought, "action": action, "query": query}


@pytest.fixture
def searches(monkeypatch):
    seen = []

    async def retrieve(**kwargs):
        seen.append(kwargs["query"])
        return [dict(PAGE)]

    from app.services.retrieval import retrieval_service
    monkeypatch.setattr(retrieval_service, "retrieve", retrieve)
    return seen


async def run(question=FUNDS, history=None):
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace):
        result = await loop.run(question, FACTS, [], history)
    return result, [s for s in trace.steps if s["name"] == "agent_step"]


# ---------------------------------------------------------------- choices

@pytest.mark.asyncio
async def test_answering_at_once_restates_the_question(fake_llm):
    fake_llm.when(DECIDE, act("answer", "How much money does a single student need outside Quebec?"))
    result, steps = await run()
    assert result.outcome == "answer" and result.answer_question.startswith("How much money does a single student")
    assert result.rule_facts == FACTS and [s["action"] for s in steps] == ["answer"]


@pytest.mark.asyncio
async def test_a_tool_runs_with_checked_arguments_and_its_result_is_seen(fake_llm, searches):
    fake_llm.when(DECIDE, [act("knowledge_base_search", "spouse open work permit"), act("answer", FUNDS)])
    result, steps = await run()
    assert searches == ["spouse open work permit"]
    assert result.chunks and result.chunks[0]["metadata"]["url"] == "https://www.canada.ca/spouse.html"
    second_decision = [c for c in fake_llm.calls if "planner" in c["system_prompt"]][1]
    assert "spouse open work permit" in second_decision["user_prompt"] and "Spouse" in second_decision["user_prompt"]
    assert [(s["action"], s["valid"], s.get("found")) for s in steps] == [
        ("knowledge_base_search", True, 1), ("answer", True, None)]


@pytest.mark.asyncio
async def test_the_profile_is_looked_up_when_chosen(fake_llm, monkeypatch):
    async def profile(_args):
        return tools.ProfileResult(found=True, education_level="master")

    monkeypatch.setitem(tools.TOOLS, "profile", tools.Tool("profile", "", tools.ProfileArgs, tools.ProfileResult, profile))
    fake_llm.when(DECIDE, [act("profile"), act("answer", "PGWP length after a master's")])
    _, _ = await run()
    second = [c for c in fake_llm.calls if "planner" in c["system_prompt"]][1]
    assert '"education_level": "master"' in second["user_prompt"]


@pytest.mark.asyncio
async def test_asking_the_user_ends_the_turn_with_the_question(fake_llm):
    fake_llm.when(DECIDE, act("ask_user", "How many family members are coming with you?"))
    result, steps = await run()
    assert result.outcome == "ask" and result.ask == "How many family members are coming with you?"


@pytest.mark.asyncio
async def test_the_agent_never_asks_twice(fake_llm):
    history = [{"role": "user", "content": FUNDS}, {"role": "assistant", "content": "How many are coming?"}]
    fake_llm.when(DECIDE, [act("ask_user", "And their ages?"), act("answer", "Funds for 4 people")])
    result, steps = await run("Four of us", history)
    assert result.outcome == "answer" and [s["valid"] for s in steps] == [False, True]


# ---------------------------------------------------------------- what code refuses

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [act("rules", ""), act("knowledge_base_search", "x"), act("ask_user", "?")])
async def test_unusable_choices_are_refused_and_two_in_a_row_hand_over_to_the_router(fake_llm, searches, bad):
    fake_llm.when(DECIDE, [bad, bad])
    result, steps = await run()
    assert result.outcome == "fallback" and [s["valid"] for s in steps][:2] == [False, False]
    assert result.answer_question == FUNDS  # the original question, not anything the model wrote


@pytest.mark.asyncio
async def test_a_repeated_action_is_refused(fake_llm, searches):
    fake_llm.when(DECIDE, [act("knowledge_base_search", "spouse work"), act("knowledge_base_search", "Spouse  work"),
                           act("answer", FUNDS)])
    result, steps = await run()
    assert searches == ["spouse work"] and [s["valid"] for s in steps] == [True, False, True]


@pytest.mark.asyncio
async def test_the_first_search_counts_as_done(fake_llm, searches):
    fake_llm.when(DECIDE, [act("knowledge_base_search", FUNDS), act("answer", FUNDS)])
    _, steps = await run()
    assert searches == [] and steps[0]["valid"] is False


@pytest.mark.asyncio
async def test_unreadable_output_counts_as_an_unusable_choice(fake_llm):
    fake_llm.when(DECIDE, ["not json"] * 4)  # structured_call retries once per decision
    result, _ = await run()
    assert result.outcome == "fallback"


@pytest.mark.asyncio
async def test_the_step_limit_ends_the_loop(fake_llm, searches, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MAX_STEPS", 2)
    fake_llm.when(DECIDE, [act("knowledge_base_search", "one"), act("knowledge_base_search", "two")])
    result, steps = await run()
    assert result.outcome == "limit" and result.answer_question == FUNDS and len(steps) == 2


@pytest.mark.asyncio
async def test_steps_are_traced_without_the_query_or_reasoning(fake_llm, searches):
    fake_llm.when(DECIDE, [act("knowledge_base_search", "Priya's spouse", "Priya asked about her husband"),
                           act("answer", FUNDS)])
    _, steps = await run()
    assert "Priya" not in str(steps)


@pytest.mark.asyncio
async def test_the_model_being_down_propagates_for_graceful_degradation(fake_llm):
    fake_llm.when(DECIDE, AIServiceUnavailableError("down"))
    with pytest.raises(AIServiceUnavailableError):
        await run()


# ---------------------------------------------------------------- in the pipeline

@pytest.fixture
def pipeline(fake_llm, monkeypatch):
    async def retrieve(*_, **__):
        return [dict(PAGE)]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(settings, "AGENT_LOOP", True)
    monkeypatch.setattr(settings, "VERIFIED_MAX_ROUNDS", 1)
    intent_cache.clear()
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    fake_llm.when(r"User Question:", "unused")
    return fake_llm


async def verified(question):
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(question, db=object())
    return result, trace


@pytest.mark.asyncio
async def test_the_evidence_step_answers_the_agents_restated_question(pipeline):
    pipeline.when(DECIDE, act("answer", "Can a spouse of an international student get an open work permit?"))
    pipeline.when(r"Question: Can a spouse of an international student", {
        "answer": "Your spouse may be eligible for an open work permit.", "source_number": 1,
        "evidence_quote": "Your spouse or common-law partner may be eligible for an open work permit."})
    result, trace = await verified("Can my husband work here while I study?")
    assert "open work permit" in result["answer"] and result["metrics"]["agent"]["outcome"] == "answer"
    assert result["metrics"]["evidence"]["verified"] == 1


@pytest.mark.asyncio
async def test_a_clarifying_question_is_sent_as_the_reply(pipeline):
    pipeline.when(DECIDE, act("ask_user", "How many family members are coming with you?"))
    result, _ = await verified(FUNDS)
    assert result["answer"] == "How many family members are coming with you?"
    assert result["metrics"]["source"] == "agent_ask" and result["sources"] == []


@pytest.mark.asyncio
async def test_with_the_loop_off_nothing_changes(pipeline, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_LOOP", False)
    pipeline.when(r"Question: How much money", {"not_covered": True})
    result, trace = await verified(FUNDS)
    assert "agent" not in [s["name"] for s in trace.steps] and "agent" not in result["metrics"]
    assert not [c for c in pipeline.calls if "planner of a Canadian" in c["system_prompt"]]
