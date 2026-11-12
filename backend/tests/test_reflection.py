"""M5.6 reflection: for a part that failed the evidence checks, the agent chooses the next attempt (search again, rules,
live fetch, restate, finish); code runs it through the same checks and keeps it only if it is better; an unusable
choice leaves code's own retry. The model is scripted (FakeLLM)."""

import pytest

from app.agent import reflect
from app.core.config import settings
from app.services import live_fetch, tools
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.source_registry import load_registry
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

DECIDE = r"planner of a Canadian immigration assistant"
REFLECT = r"reviewer of a Canadian immigration assistant"
QUESTION = "Can I get a 3-year PGWP if my master's program was only 1 year long?"
EVIDENCE = r"^(?!.*reviewer of a Canadian).*Question: Can I get a 3-year PGWP"  # not the reflection prompt
REGISTRY_URL = next(iter(load_registry().by_url()))
FIRST_PAGE = {"text": "The length of your PGWP depends on the length of your study program.", "score": 0.8,
              "authority_tier": 1, "freshness_weight": 1.0,
              "metadata": {"url": REGISTRY_URL, "title": "About the PGWP"}}
RETRY_TEXT = ("Master's degree graduates can get a 3-year PGWP if the master's program was at least 8 months long, even "
              "if it was shorter than 2 years.")
RETRY_PAGE = {"text": RETRY_TEXT, "score": 0.78, "authority_tier": 1, "freshness_weight": 1.0,
              "metadata": {"url": "https://www.canada.ca/pgwp-length.html", "title": "Length"}}
GOOD = {"answer": "Yes, a master's program of at least 8 months can lead to a 3-year PGWP.", "source_number": 2,
        "evidence_quote": RETRY_TEXT}
FROM_FIRST = {"answer": "It depends on the length of your study program.", "source_number": 1,
              "evidence_quote": "The length of your PGWP depends on the length of your study program."}
NOT_COVERED = {"not_covered": True}


def choice(action, query=""):
    return {"thought": "", "action": action, "query": query}


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    searches = []

    async def retrieve(query, top_k=4, **_):
        searches.append(query)
        return [dict(FIRST_PAGE)] if len(searches) == 1 else [dict(FIRST_PAGE), dict(RETRY_PAGE)]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(rp.rule_engine, "try_rule_answer", lambda *a, **k: None)
    monkeypatch.setattr(settings, "AGENT_LOOP", True)
    monkeypatch.setattr(settings, "VERIFIED_MAX_ROUNDS", 2)
    intent_cache.clear()
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    fake_llm.when(r"User Question:", "unused")
    fake_llm.when(DECIDE, {"thought": "", "action": "answer", "query": QUESTION})
    fake_llm.searches = searches
    return fake_llm


async def run():
    intent_cache.clear()
    trace = TraceRecorder("test", query=QUESTION)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(QUESTION, db=object())
    return result, trace


def steps(trace, name):
    return [s for s in trace.steps if s["name"] == name]


# ---------------------------------------------------------------- the agent's choice is run and checked

@pytest.mark.asyncio
async def test_the_agents_search_is_run_and_a_verified_retry_is_kept(scripted):
    scripted.when(EVIDENCE, [NOT_COVERED, GOOD])
    scripted.when(REFLECT, choice("knowledge_base_search", "master's degree PGWP length 8 months"))
    result, trace = await run()
    assert scripted.searches[-1] == "master's degree PGWP length 8 months"  # the model's words, not code's refinement
    assert steps(trace, "reflect") == [{**steps(trace, "reflect")[0], "action": "knowledge_base_search", "valid": True}]
    retry = steps(trace, "retry")[0]
    assert (retry["chosen"], retry["first"], retry["retry"], retry["kept"]) == (
        "knowledge_base_search", "not_covered", "verified", "retry")
    assert "8 months" in result["answer"] and "[Source 2]" in result["answer"]
    assert result["metrics"]["agent"]["reflect"] == ["knowledge_base_search"]
    seen = next(c for c in scripted.calls if "reviewer" in c["system_prompt"])["user_prompt"]
    assert "don't cover this" in seen and f"<{REGISTRY_URL}>" in seen


@pytest.mark.asyncio
async def test_finish_stops_without_another_attempt(scripted):
    scripted.when(EVIDENCE, NOT_COVERED)
    scripted.when(REFLECT, choice("finish"))
    result, trace = await run()
    assert not steps(trace, "retry") and len(scripted.searches) == 1
    assert result["answer"].startswith("The official sources I have don't cover this")
    assert result["metrics"]["agent"]["reflect"] == ["finish"]


@pytest.mark.asyncio
async def test_a_restated_question_is_answered_from_the_passages_already_shown(scripted):
    scripted.when(EVIDENCE, NOT_COVERED)
    scripted.when(r"Question: What decides how long a PGWP is", FROM_FIRST)
    scripted.when(REFLECT, choice("restate", "What decides how long a PGWP is for a one-year master's program?"))
    result, trace = await run()
    assert steps(trace, "retry")[0]["kept"] == "retry" and len(scripted.searches) == 1
    assert "depends on the length of your study program" in result["answer"] and "[Source 1]" in result["answer"]


@pytest.mark.asyncio
async def test_rules_chosen_on_reflection_become_source_zero(scripted, monkeypatch):
    facts = "OFFICIAL IRCC REGULATORY FACTS — PGWP:\n- Master's programs of at least 8 months: a PGWP of up to 3 years."

    async def rules(args):
        return tools.RulesResult(intent="pgwp", visa_type="Student", facts=facts, rules_version="test")

    monkeypatch.setitem(tools.TOOLS, "rules", tools.Tool("rules", "", tools.RulesArgs, tools.RulesResult, rules))
    scripted.when(EVIDENCE, [NOT_COVERED, {
        "answer": "Yes: a master's program of at least 8 months can lead to a PGWP of up to 3 years.",
        "source_number": 0, "evidence_quote": "Master's programs of at least 8 months: a PGWP of up to 3 years."}])
    scripted.when(REFLECT, choice("rules", "PGWP length for a 1-year master's"))
    result, trace = await run()
    assert steps(trace, "retry")[0]["kept"] == "retry" and "up to 3 years" in result["answer"]


@pytest.mark.asyncio
async def test_a_live_fetch_chosen_on_reflection_supplies_the_passage(scripted, monkeypatch):
    async def fetch(url, client=None):
        return live_fetch.FetchedPage(url=url, final_url=url, title="About the PGWP", text=RETRY_TEXT,
                                      fetched_at="2026-11-12T10:00:00", tier=1)

    async def embed(texts):
        return [[1.0, 0.0]] * len(texts)

    monkeypatch.setattr(live_fetch, "fetch", fetch)
    monkeypatch.setattr("app.services.embeddings.embed_texts_batch", embed)
    scripted.when(EVIDENCE, [NOT_COVERED, GOOD])
    scripted.when(REFLECT, choice("live_fetch", REGISTRY_URL))
    result, trace = await run()
    retry = steps(trace, "retry")[0]
    assert (retry["chosen"], retry["new_chunks"], retry["kept"]) == ("live_fetch", 1, "retry")
    assert "8 months" in result["answer"] and len(scripted.searches) == 1


# ---------------------------------------------------------------- code stays the judge

@pytest.mark.asyncio
async def test_an_attempt_that_is_not_better_is_not_kept(scripted):
    bad = {"answer": "Yes, always 5 years.", "source_number": 2, "evidence_quote": "Graduates always get 5 years."}
    scripted.when(EVIDENCE, [NOT_COVERED, bad])
    scripted.when(REFLECT, choice("knowledge_base_search", "PGWP length master's"))
    result, trace = await run()
    assert steps(trace, "retry")[0]["kept"] == "first" and "5 years" not in result["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("unusable", [choice("knowledge_base_search", ""), choice("live_fetch", "https://evil.example.com/"),
                                      choice("restate", QUESTION), "not json"])
async def test_an_unusable_choice_leaves_codes_own_retry(scripted, unusable):
    scripted.when(EVIDENCE, [NOT_COVERED, GOOD])
    scripted.when(REFLECT, unusable)
    result, trace = await run()
    assert steps(trace, "reflect")[0]["valid"] is False
    assert steps(trace, "retry")[0]["chosen"] == "code" and "Post-graduation work permit" in scripted.searches[-1]
    assert "8 months" in result["answer"] and result["metrics"]["agent"]["reflect"] == ["code_retry"]


@pytest.mark.asyncio
async def test_a_tool_that_fails_on_reflection_keeps_the_first_answer(scripted, monkeypatch):
    async def down(url, client=None):
        raise live_fetch.LiveFetchError("ConnectError")

    monkeypatch.setattr(live_fetch, "fetch", down)
    scripted.when(EVIDENCE, NOT_COVERED)
    scripted.when(REFLECT, choice("live_fetch", REGISTRY_URL))
    result, trace = await run()
    assert steps(trace, "retry")[0]["tool_error"] == "ToolUnavailableError"
    assert result["answer"].startswith("The official sources I have don't cover this")


@pytest.mark.asyncio
async def test_with_no_reflection_steps_code_retries_as_before(scripted, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_REFLECT_STEPS", 0)
    scripted.when(EVIDENCE, [NOT_COVERED, GOOD])
    result, trace = await run()
    assert not steps(trace, "reflect") and steps(trace, "retry")[0]["chosen"] == "code"
    assert "reflect" not in result["metrics"]["agent"]


@pytest.mark.asyncio
async def test_a_verified_answer_is_not_reflected_on(scripted):
    scripted.when(EVIDENCE, FROM_FIRST)
    _, trace = await run()
    assert not steps(trace, "reflect") and not steps(trace, "retry")


# ---------------------------------------------------------------- the choice itself

def test_choices_code_refuses():
    pages = [("About", REGISTRY_URL)]
    ok = reflect.ReflectAction(action="live_fetch", query=REGISTRY_URL)
    assert reflect._problem(ok, QUESTION, pages, []) == ""
    assert "already tried" in reflect._problem(ok, QUESTION, pages, [reflect.key("live_fetch", REGISTRY_URL)])
    assert "needs a query" in reflect._problem(reflect.ReflectAction(action="rules", query=" "), QUESTION, pages, [])
    assert reflect._problem(reflect.ReflectAction(action="finish"), QUESTION, pages, ["finish|"]) == ""
    assert reflect.pages_seen([FIRST_PAGE, FIRST_PAGE, RETRY_PAGE]) == [
        ("About the PGWP", REGISTRY_URL), ("Length", "https://www.canada.ca/pgwp-length.html")]


@pytest.mark.asyncio
async def test_the_trace_holds_no_query_or_reasoning(scripted):
    scripted.when(EVIDENCE, [NOT_COVERED, GOOD])
    scripted.when(REFLECT, {"thought": "Priya asked about her master's", "action": "knowledge_base_search",
                            "query": "Priya master's PGWP"})
    _, trace = await run()
    assert "Priya" not in str(steps(trace, "reflect") + steps(trace, "retry"))
