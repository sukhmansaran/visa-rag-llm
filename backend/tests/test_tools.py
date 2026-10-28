"""M5.1 tool registry: each tool runs only with checked arguments, returns a checked result and writes nothing."""

import pytest
from dataclasses import replace
from sqlalchemy import func, select

from app.models.profile import Profile
from app.models.user import User
from app.services import tools
from app.services.rule_engine import get_rules_content_hash, rule_engine
from app.services.source_registry import load_registry
from app.services.tracing import TraceRecorder, activate_trace

REGISTRY_URL = load_registry().entries[0].url


def spy_on(monkeypatch, name):
    """Replace a tool's run with one that records its calls; returns the list of calls."""
    calls = []
    real = tools.TOOLS[name]

    async def run(args):
        calls.append(args)
        return await real.run(args)

    monkeypatch.setitem(tools.TOOLS, name, replace(real, run=run))
    return calls


# ---------------------------------------------------------------- the registry

def test_the_registry_has_the_five_read_only_tools():
    assert set(tools.TOOLS) == {"rules", "knowledge_base_search", "live_fetch", "profile", "processing_times_link"}


def test_specs_offer_only_available_tools_with_strict_schemas():
    specs = {s["name"]: s for s in tools.tool_specs()}
    assert "live_fetch" not in specs  # until M5.3
    assert set(specs) == {"rules", "knowledge_base_search", "profile", "processing_times_link"}
    for spec in specs.values():
        assert spec["description"] and spec["parameters"].get("additionalProperties") is False


@pytest.mark.asyncio
async def test_an_unknown_tool_is_refused():
    with pytest.raises(tools.UnknownToolError):
        await tools.call("delete_everything", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("rules", {}),                                                   # missing
    ("rules", {"question": "hi"}),                                   # too short
    ("rules", {"question": "x" * 1001}),                             # too long
    ("rules", {"question": "How much money do I need?", "sql": "DROP TABLE users"}),  # unknown field
    ("knowledge_base_search", {"query": "PGWP length", "top_k": 0}),
    ("knowledge_base_search", {"query": "PGWP length", "top_k": 9}),
    ("knowledge_base_search", {"query": "PGWP length", "top_k": "lots"}),
    ("profile", {"user_id": 2}),                                     # whose profile is never an argument
    ("processing_times_link", {"application_type": "study permit"}),
])
async def test_bad_arguments_are_refused_before_the_tool_runs(monkeypatch, name, args):
    calls = spy_on(monkeypatch, name)
    with pytest.raises(tools.ToolArgumentError):
        await tools.call(name, args)
    assert calls == []


@pytest.mark.asyncio
async def test_a_call_is_traced_by_tool_name_never_by_its_arguments(monkeypatch):
    trace = TraceRecorder("test", query="private words")
    with activate_trace(trace):
        await tools.call("rules", {"question": "How much money do I need for a study permit, says Priya?"})
    step = next(s for s in trace.steps if s["name"] == "tool")
    assert step["tool"] == "rules" and step["result_chars"] > 0
    assert "Priya" not in str(step)


# ---------------------------------------------------------------- rules

@pytest.mark.asyncio
async def test_rules_returns_the_rule_engine_facts():
    result = await tools.call("rules", {"question": "How much money do I need to show for a study permit?"})
    assert isinstance(result, tools.RulesResult)
    assert result.facts and "23,448" in result.facts
    assert result.rules_version == get_rules_content_hash() and result.guarantee_fact is None


@pytest.mark.asyncio
async def test_rules_includes_the_guarantee_and_closed_program_facts():
    guarantee = await tools.call("rules", {"question": "If I show enough money, will my visa definitely be approved?"})
    assert guarantee.guarantee_fact == rule_engine.approval_guarantee_fact(
        "If I show enough money, will my visa definitely be approved?")
    closed = await tools.call("rules", {"question": "Can I apply through the Student Direct Stream?"})
    assert closed.closed_program_fact


# ---------------------------------------------------------------- knowledge_base_search

@pytest.mark.asyncio
async def test_search_passes_checked_arguments_and_returns_typed_chunks(monkeypatch):
    from app.services.retrieval import retrieval_service

    seen = {}

    async def retrieve(**kwargs):
        seen.update(kwargs)
        return [{"text": "You can work 24 hours a week.", "score": 0.81, "authority_tier": 1,
                 "metadata": {"url": "https://www.canada.ca/work.html", "title": "Work"}}]

    monkeypatch.setattr(retrieval_service, "retrieve", retrieve)
    result = await tools.call("knowledge_base_search", {"query": "  off-campus work hours  ", "top_k": 3})
    assert seen == {"query": "off-campus work hours", "top_k": 3, "country": None}
    assert result.chunks[0].url == "https://www.canada.ca/work.html" and result.chunks[0].score == 0.81


# ---------------------------------------------------------------- live_fetch

def test_live_fetch_accepts_exactly_a_registry_page():
    assert tools.validate_args("live_fetch", {"url": REGISTRY_URL}).url == REGISTRY_URL


@pytest.mark.parametrize("url", [
    "https://www.example.com/study.html",                      # not in the registry
    REGISTRY_URL + "?q=my+name+is+priya",                      # nothing from the user may ride along
    REGISTRY_URL + "#funds",
    "file:///etc/passwd",
])
def test_live_fetch_refuses_anything_but_a_registry_page(url):
    with pytest.raises(tools.ToolArgumentError):
        tools.validate_args("live_fetch", {"url": url})


@pytest.mark.asyncio
async def test_live_fetch_is_unavailable_until_m53():
    with pytest.raises(tools.ToolUnavailableError):
        await tools.call("live_fetch", {"url": REGISTRY_URL})


# ---------------------------------------------------------------- profile

async def _user_with_profile(db_session, email, **fields):
    user = User(email=email, full_name="Priya Kaur", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    db_session.add(Profile(user_id=user.id, first_name="Priya", last_name="Kaur", **fields))
    await db_session.commit()
    return user.id


@pytest.mark.asyncio
async def test_profile_is_the_requesting_users_and_holds_no_names(db_session):
    await _user_with_profile(db_session, "tools-other@example.com", education_level="phd")  # created first
    mine = await _user_with_profile(db_session, "tools-me@example.com", education_level="master",
                                    work_experience=3, test_scores={"ielts": 7.5})
    with activate_trace(TraceRecorder("test", user_id=mine)):
        result = await tools.call("profile")
    assert result.found and result.education_level == "master" and result.work_experience_years == 3
    assert result.test_scores == {"ielts": 7.5}
    assert "Priya" not in result.model_dump_json() and "Kaur" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_profile_without_a_user_or_a_profile_is_not_found(db_session):
    assert (await tools.call("profile")).found is False  # no request, no user
    with activate_trace(TraceRecorder("test", user_id=999999)):
        assert (await tools.call("profile")).found is False


@pytest.mark.asyncio
async def test_tools_write_nothing(db_session, monkeypatch):
    from app.services.retrieval import retrieval_service

    async def retrieve(**_):
        return []

    monkeypatch.setattr(retrieval_service, "retrieve", retrieve)
    user_id = await _user_with_profile(db_session, "tools-readonly@example.com", education_level="bachelor")

    async def counts():
        return [(await db_session.execute(select(func.count()).select_from(m))).scalar_one() for m in (User, Profile)]

    before = await counts()
    with activate_trace(TraceRecorder("test", user_id=user_id)):
        for name, args in [("rules", {"question": "How much money do I need?"}),
                           ("knowledge_base_search", {"query": "PGWP length"}),
                           ("profile", {}), ("processing_times_link", {})]:
            await tools.call(name, args)
    assert await counts() == before
    profile = (await db_session.execute(select(Profile).where(Profile.user_id == user_id))).scalars().one()
    await db_session.refresh(profile)
    assert profile.education_level == "bachelor"


# ---------------------------------------------------------------- processing_times_link

@pytest.mark.asyncio
async def test_processing_times_link_points_to_irccs_live_tool_and_has_no_figures():
    result = await tools.call("processing_times_link")
    assert result.url == rule_engine.rules_data["processing_times"]["source_url"]
    assert result.url.startswith("https://www.canada.ca/") and not any(ch.isdigit() for ch in result.note)
