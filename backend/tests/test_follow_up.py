"""M2.4 follow-up questions: when to rewrite, the deterministic rules, the checks, the model fallback, the pipeline.
The model is scripted (FakeLLM); held-out conversations are checked against labels in follow_up_holdout.json."""

import json
from pathlib import Path

import pytest

from app.core.exceptions import AIServiceUnavailableError
from app.services import follow_up as fu
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.prompt_registry import get_prompt, load_lock
from app.services.topics import detect_topics
from app.services.tracing import TraceRecorder, activate_trace

DATA = Path(__file__).parent / "data"
EVAL = {c["id"]: c for c in json.loads((DATA / "rag_eval_set.json").read_text(encoding="utf-8"))["cases"]}
HOLDOUT = json.loads((DATA / "follow_up_holdout.json").read_text(encoding="utf-8"))


def user_turns(*texts):
    return [{"role": "user", "content": t} for t in texts]


# ---------------------------------------------------------------- deterministic rewrites

@pytest.mark.asyncio
@pytest.mark.parametrize("case_id,expected", [
    ("followup_pgwp_short", "How long is a PGWP if my program was only 10 months long?"),
    ("followup_funds_spouse", "How much money do I need as a student, if my spouse comes with me?"),
    ("followup_biometrics_kids", "Do my children also need to give biometrics?"),
    ("followup_funds_child_3turn",
     "How much money do I need as a student, if my spouse comes with me and our child comes too?"),
    ("followup_work_break", "How many hours can I work off campus during my summer break?"),
    ("followup_biometrics_validity_3turn", "How long are biometrics valid?"),
])
async def test_evaluation_follow_ups(case_id, expected, fake_llm):
    case = EVAL[case_id]
    result = await fu.resolve(case["question"], case["history"])
    assert (result.method, result.question) == (fu.DETERMINISTIC, expected)
    assert fake_llm.calls == []  # deterministic: no model call


@pytest.mark.asyncio
@pytest.mark.parametrize("round_name,minimum", [("round_1", 12), ("round_2", 10), ("round_3", 8)])
async def test_held_out_conversations(round_name, minimum):
    """Label checks only (topics + words). Reading round_3's rewrites found 1 of 8 muddled ('a diploma ..., for a
    PhD'): labels can't judge meaning, so these floors guard against regressions, not quality."""
    good = 0
    for case in HOLDOUT[round_name]:
        result = await fu.resolve(case["message"], user_turns(*case["turns"]), use_model=False)
        if case.get("standalone"):
            good += result.question == case["message"]
        else:
            good += (set(case["topics"]) <= set(detect_topics(result.question).topics)
                     and all(w in result.question.lower() for w in case["words"]))
    assert good >= minimum


@pytest.mark.parametrize("message,previous,expected", [
    ("What about on campus?", "Can I work off campus during my studies?", "Can I work on campus during my studies?"),
    ("What about for a master's?", "Do I need a PAL for a bachelor's degree in Manitoba?",
     "Do I need a PAL for a master's in Manitoba?"),
    ("And if I bring my husband?", "How much money do I need as a single student?",
     "How much money do I need as a student, if I bring my husband?"),
    ("And our two kids?", "How much money do I need as a student, if my wife comes?",
     "How much money do I need as a student, if my wife comes and our two kids?"),
    ("Is CELPIP accepted too?", "Which IELTS test do I need for Express Entry?",
     "Is CELPIP accepted too (about Express Entry)?"),
])
def test_rewrite_rules(message, previous, expected):
    assert fu.rewrite(message, previous) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("message,turns", [
    ("How much is the biometrics fee?", ["Do I need a PAL?"]),                     # its own topic
    ("Do I need a PAL for a master's in BC?", ["How much money do I need as a single student?"]),
    ("How many hours can I work off campus during classes?", []),                  # no conversation
])
async def test_standalone_messages_are_left_alone(message, turns, fake_llm):
    result = await fu.resolve(message, user_turns(*turns) if turns else [])
    assert (result.method, result.question) == (fu.STANDALONE, message) and fake_llm.calls == []


# ---------------------------------------------------------------- checks and the model fallback

def test_a_rewrite_must_keep_the_messages_facts_and_add_no_acronym():
    assert fu.check("What if my 2 kids come?", "How much money do I need?", "",
                    "How much money do I need for my family?") == ["facts: kids, 2 missing"]
    assert fu.check("And for a diploma?", "How long is a PGWP?", "How long is a PGWP?",
                    "How long is a PGWP for a diploma at a DLI?") == ["acronyms: DLI added"]


@pytest.mark.asyncio
async def test_the_model_rewrites_when_no_rule_applies(fake_llm):
    fake_llm.when(r"Latest message: Does the province matter", {"question": "Does the province matter for a PAL?"})
    result = await fu.resolve("Does the province matter", user_turns("Do I need a PAL as a master's student?"))
    # the carried topic rule applies first ("(about PAL)") so the model is not needed here
    assert result.method == fu.DETERMINISTIC and "PAL" in result.question


@pytest.mark.asyncio
async def test_a_model_rewrite_that_drops_facts_is_not_used(fake_llm, monkeypatch):
    monkeypatch.setattr(fu, "rewrite", lambda message, previous: None)  # force the model path
    fake_llm.when(r"Latest message:", {"question": "How much money do I need?"})
    result = await fu.resolve("What if my 3 children come?", user_turns("How much money do I need?"))
    assert result.method == fu.UNRESOLVED and result.question == "What if my 3 children come?"
    assert any("facts" in p for p in result.problems)


@pytest.mark.asyncio
async def test_a_good_model_rewrite_is_used(fake_llm, monkeypatch):
    monkeypatch.setattr(fu, "rewrite", lambda message, previous: None)
    fake_llm.when(r"Latest message:", {"question": "How much money do I need if my 3 children come?"})
    result = await fu.resolve("What if my 3 children come?", user_turns("How much money do I need?"))
    assert (result.method, result.question) == (fu.MODEL, "How much money do I need if my 3 children come?")


@pytest.mark.asyncio
async def test_the_model_being_down_leaves_the_message_unchanged(fake_llm, monkeypatch):
    monkeypatch.setattr(fu, "rewrite", lambda message, previous: None)
    fake_llm.when(r"Latest message:", AIServiceUnavailableError(message="busy"))
    result = await fu.resolve("What if my 3 children come?", user_turns("How much money do I need?"))
    assert result.method == fu.UNRESOLVED and result.question == "What if my 3 children come?"


def test_trace_summary_has_no_user_text():
    result = fu.Resolution("secret rewritten?", "secret?", fu.DETERMINISTIC)
    assert "secret" not in json.dumps(result.summary()) and result.summary()["changed"] is True


def test_the_prompt_is_registered_and_locked():
    prompt = get_prompt("follow_up")
    assert load_lock()["follow_up"][str(prompt.version)] == prompt.fingerprint


# ---------------------------------------------------------------- in the pipeline

@pytest.mark.asyncio
async def test_the_pipeline_answers_the_standalone_question(fake_llm, monkeypatch):
    asked = []

    async def retrieve(query, **_):
        asked.append(query)
        return [{"text": "Proof of funds for living expenses.", "score": 0.85, "authority_tier": 1,
                 "freshness_weight": 1.0, "metadata": {"url": "https://www.canada.ca/funds.html", "title": "Funds"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"User Question:", "With your spouse you need 29,192 CAD [Source 1].")
    case = EVAL["followup_funds_spouse"]
    trace = TraceRecorder("test", query=case["question"])
    with activate_trace(trace):
        await rp.rag_pipeline.process_query(case["question"], chat_history=case["history"], db=object())

    step = next(s for s in trace.steps if s["name"] == "follow_up")
    assert (step["method"], step["changed"]) == ("deterministic", True)
    assert asked == ["How much money do I need as a student, if my spouse comes with me?"]
    answer_call = next(c for c in fake_llm.calls if c["kind"] != "structured")
    assert "29,192" in answer_call["context"]  # the funds rule for 2 people, which the bare message never reached
    assert "if my spouse comes with me" in answer_call["user_prompt"]


@pytest.mark.asyncio
async def test_no_conversation_no_follow_up_step(fake_llm, monkeypatch):
    async def retrieve(query, **_):
        return []

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    fake_llm.when(r"User Question:", "Up to 24 hours per week [Source 1].")
    intent_cache.clear()
    trace = TraceRecorder("test", query="x")
    with activate_trace(trace):
        await rp.rag_pipeline.process_query("How many hours can I work off campus?", db=object())
    assert "follow_up" not in [s["name"] for s in trace.steps]


# ---------------------------------------------------------------- the input guardrail lets follow-ups through

@pytest.mark.parametrize("case_id", [c for c in EVAL if c.startswith("followup")])
def test_the_guardrail_lets_every_evaluation_follow_up_through(case_id):
    """'What if my program was only 10 months long?' was refused as off-topic before the resolver could run."""
    from app.services.guardrails.input_guardrail import input_guardrail

    case = EVAL[case_id]
    assert input_guardrail.evaluate(case["question"], chat_history=case["history"]).allowed


@pytest.mark.parametrize("message", ["What if I want to bake a cake?", "And what about the weather in Paris?"])
def test_an_unrelated_message_is_still_refused_without_an_immigration_conversation(message):
    from app.services.guardrails.input_guardrail import input_guardrail

    assert not input_guardrail.evaluate(message, chat_history=user_turns("What is your favourite movie?")).allowed
    assert not input_guardrail.evaluate(message).allowed
