"""M4.6: a verified answer is cached by the question as answered and every version it depends on; personal answers
stay with their user; Redis being down or the monitor not having run means no cache, never a wrong one."""

import json
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.exceptions import AIServiceUnavailableError
from app.services import rag_pipeline as rp
from app.services import verified_cache
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as
from app.services.vector_store import vector_store

EVAL = {c["id"]: c for c in json.loads((Path(__file__).parent / "data" / "rag_eval_set.json")
                                       .read_text(encoding="utf-8"))["cases"]}
PLAIN = "How many hours can I work off campus during my winter break?"
PERSONAL = "My email is priya.k@example.com. How many hours can I work off campus during my winter break?"
PAGE = {"text": "You can work unlimited hours off campus during scheduled breaks. With your spouse you need "
                "29,192 CAD.",
        "score": 0.86, "authority_tier": 1, "freshness_weight": 1.0,
        "metadata": {"url": "https://www.canada.ca/work.html", "title": "Work"}}
GOOD = {"answer": "You can work unlimited hours off campus during scheduled breaks.", "source_number": 1,
        "evidence_quote": "You can work unlimited hours off campus during scheduled breaks."}


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value


class DownRedis:
    async def get(self, key):
        raise ConnectionError("down")

    async def set(self, key, value, ex=None):
        raise ConnectionError("down")


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(verified_cache, "_redis", lambda: fake)
    monkeypatch.setattr(settings, "VERIFIED_CACHE_ENABLED", True)

    async def kb():
        return "chroma-667"

    monkeypatch.setattr(vector_store, "content_version", kb)
    return fake


@pytest.fixture
def scripted(fake_llm, redis, monkeypatch):
    asked = []

    async def retrieve(query, **_):
        asked.append(query)
        return [PAGE]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(settings, "VERIFIED_MAX_ROUNDS", 1)
    fake_llm.when(r"User Question:", "A free-written answer.")
    fake_llm.when(r"Question: (My email is \S+ )?How many hours", GOOD)
    fake_llm.when(r"Question: How much money", {**GOOD, "answer": "With your spouse you need 29,192 CAD.",
                                                "evidence_quote": "With your spouse you need 29,192 CAD"})
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    fake_llm.asked = asked
    return fake_llm


async def run(question, user_id=None, chat_history=None, path="verified"):
    intent_cache.clear()
    trace = TraceRecorder("test", user_id=user_id, query=question)
    with activate_trace(trace), routed_as(path):
        result = await rp.rag_pipeline.process_query(question, chat_history=chat_history, db=object())
    return result, trace


def first(fake, pattern, response):
    """Script a reply that wins over the fixture's rules (FakeLLM uses the first matching rule)."""
    fake.when(pattern, response)
    fake._rules.insert(0, fake._rules.pop())


def steps(trace):
    return [s["name"] for s in trace.steps]


# ---------------------------------------------------------------- hits

@pytest.mark.asyncio
async def test_a_repeated_verified_question_comes_from_the_cache_in_under_a_second(scripted):
    first, _ = await run(PLAIN)
    calls = len(scripted.calls)
    started = time.perf_counter()
    second, trace = await run(PLAIN)
    assert time.perf_counter() - started < 1.0
    assert second["answer"] == first["answer"] and second["sources"] == first["sources"]
    assert second["metrics"]["source"] == "verified_cache" and len(scripted.calls) == calls  # no model call
    assert "retrieval" not in steps(trace) and len(scripted.asked) == 1


@pytest.mark.asyncio
async def test_spacing_and_case_do_not_change_the_key(scripted):
    await run(PLAIN)
    result, _ = await run("  how many HOURS can i work off campus   during my winter break? ")
    assert result["metrics"]["source"] == "verified_cache"


@pytest.mark.asyncio
async def test_a_follow_up_is_looked_up_as_the_question_it_resolves_to(scripted):
    case = EVAL["followup_funds_spouse"]
    await run("How much money do I need as a student, if my spouse comes with me?")
    result, _ = await run(case["question"], chat_history=case["history"])
    assert result["metrics"]["source"] == "verified_cache" and "29,192" in result["answer"]


# ---------------------------------------------------------------- what is never cached or served

@pytest.mark.asyncio
async def test_the_fast_path_does_not_use_the_verified_cache(scripted, redis):
    await run(PLAIN, path="fast")
    assert redis.data == {}


@pytest.mark.asyncio
async def test_a_free_written_answer_is_not_stored(scripted, redis):
    first(scripted, r"Question: How many hours", "not json")  # no evidence answer: refused or written freely
    await run(PLAIN)
    assert redis.data == {}


@pytest.mark.asyncio
async def test_an_answer_the_monitor_could_not_check_is_not_stored(scripted, redis, monkeypatch):
    monkeypatch.setattr(settings, "MONITOR_ENABLED", True)
    first(scripted, r"Message: How many hours", AIServiceUnavailableError(message="busy"))
    result, _ = await run(PLAIN)
    assert result["metrics"]["monitor"]["available"] is False and redis.data == {}


@pytest.mark.asyncio
async def test_an_answer_the_monitor_checked_is_stored(scripted, redis, monkeypatch):
    monkeypatch.setattr(settings, "MONITOR_ENABLED", True)
    first(scripted, r"Message: How many hours", {"category": "immigration", "confidence": 0.95})
    await run(PLAIN)
    assert len(redis.data) == 1


@pytest.mark.asyncio
async def test_a_personal_question_is_only_served_to_the_same_user(scripted):
    await run(PERSONAL, user_id=1)
    same, _ = await run(PERSONAL, user_id=1)
    other, _ = await run(PERSONAL, user_id=2)
    assert same["metrics"]["source"] == "verified_cache"
    assert other["metrics"]["source"] != "verified_cache"


@pytest.mark.asyncio
async def test_a_personal_question_with_no_user_is_not_cached(redis):
    assert verified_cache.is_personal(PERSONAL) and not verified_cache.is_personal(PLAIN)
    assert await verified_cache.key_for(PERSONAL, None, None) is None
    assert await verified_cache.key_for(PLAIN, None, None) is not None


@pytest.mark.asyncio
async def test_redis_down_answers_as_usual(scripted, monkeypatch):
    monkeypatch.setattr(verified_cache, "_redis", lambda: DownRedis())
    result, trace = await run(PLAIN)
    assert "unlimited hours" in result["answer"] and result["metrics"]["source"] != "verified_cache"
    assert next(s for s in trace.steps if s["name"] == "verified_cache_store")["stored"] is False


@pytest.mark.asyncio
async def test_the_cache_can_be_switched_off(scripted, redis, monkeypatch):
    monkeypatch.setattr(settings, "VERIFIED_CACHE_ENABLED", False)
    await run(PLAIN)
    _, trace = await run(PLAIN)
    assert redis.data == {} and "verified_cache" not in steps(trace)


# ---------------------------------------------------------------- invalidation: every version is in the key

@pytest.mark.asyncio
async def test_the_key_depends_on_the_profile(redis):
    a = await verified_cache.key_for(PLAIN, {"country": "India"}, None)
    b = await verified_cache.key_for(PLAIN, {"country": "Nigeria"}, None)
    assert a != b


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rules", "kb", "prompt", "pins", "settings"])
async def test_a_changed_version_changes_the_key(redis, monkeypatch, tmp_path, change):
    from app.services import model_pins, prompt_registry, rule_engine

    before = await verified_cache.key_for(PLAIN, None, None)
    if change == "rules":
        monkeypatch.setattr(rule_engine, "get_rules_content_hash", lambda: "changed-rules")
    elif change == "kb":
        async def kb():
            return "chroma-668"
        monkeypatch.setattr(vector_store, "content_version", kb)
    elif change == "prompt":
        prompts = dict(prompt_registry.all_prompts())
        name = next(iter(prompts))

        class Bumped:
            tag = prompts[name].tag + "-bumped"
        monkeypatch.setattr(prompt_registry, "all_prompts", lambda: {**prompts, name: Bumped()})
    elif change == "pins":
        pins = tmp_path / "model_pins.yaml"
        original = model_pins.PINS_PATH.read_bytes() if model_pins.PINS_PATH.exists() else b""
        pins.write_bytes(original + b"\n# rebuilt\n")
        monkeypatch.setattr(model_pins, "PINS_PATH", pins)
    else:
        monkeypatch.setattr(settings, "RAG_TOP_K", settings.RAG_TOP_K + 1)
    assert await verified_cache.key_for(PLAIN, None, None) != before


@pytest.mark.asyncio
async def test_an_unknown_knowledge_base_is_not_cached(redis, monkeypatch):
    async def broken():
        raise RuntimeError("chroma down")
    monkeypatch.setattr(vector_store, "content_version", broken)
    assert await verified_cache.key_for(PLAIN, None, None) is None
