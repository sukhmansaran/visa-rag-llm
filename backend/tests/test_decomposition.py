"""M2.2 decomposition: when to split, each validator, repair, fallback, and the model being unavailable.
The model is scripted (FakeLLM); the real-model evaluation is scripts/eval_decomposition.py."""

import json
from pathlib import Path

import pytest

from app.core.exceptions import AIServiceUnavailableError
from app.services import decomposition as dec
from app.services.prompt_registry import get_prompt, load_lock
from app.services.topics import TOPICS, detect_topics

DATA = Path(__file__).parent / "data"
FUNDS_AND_HOURS = ("As a single student, how much money do I need for living expenses, and how many hours can I "
                   "work off campus during classes?")
GOOD_SPLIT = {"sub_questions": ["As a single student, how much money do I need for living expenses?",
                                "As a single student, how many hours can I work off campus during classes?"]}


def problems_for(question, subs):
    return dec.validate(question, detect_topics(question), subs)


# ---------------------------------------------------------------- when to split

@pytest.mark.parametrize("question,split", [
    (FUNDS_AND_HOURS, True),
    ("How much does biometrics cost for one person and are children under 14 exempt?", True),  # 2 asks, 1 topic
    ("What are the funds and work hour rules for students?", True),                           # listed topics
    ("How many hours per week can I work off campus during my semester?", False),
    ("Do children under 14 need to give biometrics for a visitor visa?", False),  # one ask touching two topics
    ("Do I need a GIC for my study permit?", False),
])
def test_needs_split(question, split):
    assert dec.needs_split(question) is split


@pytest.mark.asyncio
async def test_a_single_question_makes_no_model_call(fake_llm):
    result = await dec.decompose("How many hours per week can I work off campus during my semester?")
    assert (result.method, result.sub_questions) == (dec.SINGLE, ("How many hours per week can I work off campus during my semester?",))
    assert fake_llm.calls == []


# ---------------------------------------------------------------- the model's split, accepted or not

@pytest.mark.asyncio
async def test_a_good_split_is_used(fake_llm):
    fake_llm.when(r"Question: As a single student", GOOD_SPLIT)
    result = await dec.decompose(FUNDS_AND_HOURS)
    assert result.method == dec.MODEL and result.sub_questions == tuple(GOOD_SPLIT["sub_questions"])
    assert result.topics == ("funds", "work") and not result.problems
    call = fake_llm.calls[0]
    assert call["kind"] == "structured" and call["role"] == "planner" and "at most 2 sub-questions" in call["system_prompt"]


@pytest.mark.parametrize("subs,problem", [
    (["How much money do I need as a single student?", "How many hours can I work off campus?",
      "Can I bring my family?"], "count:"),
    (["As a single student, how much money do I need for living expenses?"], "coverage: no sub-question about work"),
    (["As a single student, how much money do I need?", "As a single student, how much money do I need for it?"],
     "duplicates:"),
    (["As a single student, how much money do I need?", "As a single student, how long is a PGWP?"],
     "mapping: sub-question 2 adds pgwp"),
    (["How much money do I need for living expenses?", "How many hours can I work off campus during classes?"],
     "facts: single missing"),
])
def test_each_validator(subs, problem):
    problems = problems_for(FUNDS_AND_HOURS, subs)
    assert any(p.startswith(problem) for p in problems), problems


def test_facts_are_numbers_and_people_words():
    assert dec._facts("What IELTS score gives CLB 9, and do I need $22,895 for my wife and 2 children?") == [
        "wife", "children", "9", "$22,895", "2"]


def test_a_sub_question_about_nothing_in_the_question_is_refused():
    question = "My wife and son are coming with me. How much money do we need, and can my wife work while I study?"
    ok = problems_for(question, ["My wife and son are coming with me. How much money do we need?",
                                 "Can my wife work while I study?"])
    assert ok == []
    bad = problems_for(question, ["My wife and son are coming with me. How much money do we need?",
                                  "What is the best city to live in?"])
    assert any("is not about the question" in p for p in bad)


@pytest.mark.parametrize("sub,ok", [
    ("Do I need a Guaranteed Investment Certificate (GIC) for my study permit?", True),
    ("Do I need a GIC (guaranteed investment certificate) for my study permit?", True),
    ("Do I need a PAL (Permanent Resident Card) for my study permit?", False),
    ("Do I need an Express Entry Confirmation of Completeness (ECA)?", False),
    ("Do I need a Social Insurance Number (SINX)?", False),   # an acronym the glossary doesn't know, and not asked
])
def test_acronym_expansions_must_match_the_glossary(sub, ok):
    question = "Do I need a GIC, a PAL or an ECA for my study permit?"
    expansion_problems = [p for p in dec.acronym_problems(question, [sub]) if "expands" in p or "adds" in p]
    assert (expansion_problems == []) is ok, expansion_problems


def test_an_acronym_the_user_did_not_write_is_refused():
    assert dec.acronym_problems("How many hours can I work in winter break?",
                                ["How many hours can I work on a PGWP?"]) == [
        "acronyms: sub-question 1 adds PGWP, which the user did not write"]


@pytest.mark.asyncio
async def test_invented_expansions_are_removed_and_the_split_rechecked(fake_llm):
    question = "For the Federal Skilled Worker Program, how many points do I need, and do I need an ECA?"
    fake_llm.when(r"Question: For the Federal", {"sub_questions": [
        "For the Federal Skilled Worker Program, how many points do I need?",
        "Do I need an Express Entry Confirmation of Completeness (ECA) for the Federal Skilled Worker Program?"]})
    result = await dec.decompose(question)
    assert result.method == dec.MODEL and result.repaired
    assert result.sub_questions[1] == "Do I need an ECA for the Federal Skilled Worker Program?"
    assert any("expands ECA" in p for p in result.problems)  # recorded, though repaired


@pytest.mark.asyncio
async def test_a_failing_split_falls_back_to_the_users_own_clauses(fake_llm):
    fake_llm.when(r"Question: As a single student", {"sub_questions": [
        "How much money do I need for living expenses?", "How many hours can I work off campus during classes?"]})
    result = await dec.decompose(FUNDS_AND_HOURS)
    assert result.method == dec.FALLBACK and any(p.startswith("facts:") for p in result.problems)
    assert result.sub_questions == tuple(GOOD_SPLIT["sub_questions"])
    assert result.proposed[0] == "How much money do I need for living expenses?"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [AIServiceUnavailableError(message="busy"), "not json at all"])
async def test_the_model_unavailable_or_unreadable_falls_back(fake_llm, failure):
    fake_llm.when(r"Question: As a single student", failure)
    result = await dec.decompose(FUNDS_AND_HOURS)
    assert result.method == dec.FALLBACK and result.problems[0].startswith("model:")
    assert len(result.sub_questions) == 2


# ---------------------------------------------------------------- deterministic split

@pytest.mark.parametrize("question,parts", [
    ("How much money do I need, do I need a PAL, and do I need biometrics?",
     ["How much money do I need?", "Do I need a PAL?", "Do I need biometrics?"]),
    ("My study permit was refused last month. Can I apply again, and do I need to give biometrics again?",
     ["My study permit was refused last month. Can I apply again?",
      "My study permit was refused last month. Do I need to give biometrics again?"]),
    ("Tell me about PAL and PGWP", ["Tell me about PAL and PGWP"]),  # no question clauses: unsplit
])
def test_fallback_split(question, parts):
    assert dec.fallback_split(question) == parts


def test_trace_summary_has_no_user_text():
    result = dec.Decomposition("secret question", ("secret a?", "secret b?"), dec.MODEL, ("funds",), ("x",))
    assert "secret" not in json.dumps(result.summary())


# ---------------------------------------------------------------- data and prompt

def test_the_prompt_is_registered_and_locked():
    prompt = get_prompt("decomposition")
    assert load_lock()["decomposition"][str(prompt.version)] == prompt.fingerprint
    assert "Never write what an acronym stands for" in prompt.system


@pytest.mark.parametrize("name", ["decomposition_cases", "decomposition_holdout"])
def test_evaluation_data_is_well_formed(name):
    cases = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))["cases"]
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["parts"]
        for part in case["parts"]:
            assert set(part["topics"]) <= set(TOPICS)
            assert all(fact == fact.lower() and fact in case["question"].lower() for fact in part["facts"])
        assert dec.max_parts(case["question"], detect_topics(case["question"])) == len(case["parts"])
