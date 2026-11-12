"""M6.1 step lines: every pipeline step has a decided line (or a decision to stay silent), the lines say what happened
in plain words, and they carry nothing but the step's own safe fields."""

import re
from pathlib import Path

import pytest

from app.services import answer_jobs
from app.services.step_labels import STEP_NAMES, describe

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_step_the_code_emits_has_a_decision():
    emitted = set()
    for path in APP.rglob("*.py"):
        emitted |= set(re.findall(r'trace_step\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert emitted, "no trace steps found: the scan is broken"
    assert emitted <= set(STEP_NAMES), f"steps without a line decision in step_labels.py: {sorted(emitted - set(STEP_NAMES))}"


def test_silent_steps_stay_silent_and_unknown_steps_too():
    for name, speaks in STEP_NAMES.items():
        if not speaks:
            assert describe({"name": name, "found": True, "hit": True, "valid": True}) is None
    assert describe({"name": "something_new"}) is None


@pytest.mark.parametrize("step,line", [
    ({"name": "triage", "routed": "verified", "reasons": ["multi_part"]},
     "Chose the careful, step-by-step check because it has several parts"),
    ({"name": "triage", "routed": "fast", "reasons": []}, None),
    ({"name": "decomposition", "parts": 3}, "Split the question into 3 parts"),
    ({"name": "decomposition", "parts": 1}, None),
    ({"name": "retrieval", "chunks": [{"url": "https://www.canada.ca/a.html"}, {"url": "https://www.canada.ca/b.html"}]},
     "Found 2 passages from canada.ca"),
    ({"name": "retrieval", "chunks": []}, "Found no matching passages"),
    ({"name": "agent_step", "action": "rules", "valid": True, "found": 1}, "Looked up the official rules"),
    ({"name": "agent_step", "action": "knowledge_base_search", "valid": True, "found": 1},
     "Searched the official pages again (1 new passage)"),
    ({"name": "agent_step", "action": "profile", "valid": True, "found": 0, "before_ask": True},
     "Checked your saved profile before asking you anything (nothing saved)"),
    ({"name": "agent_step", "action": "live_fetch", "valid": True, "found": 3, "before_answer": True},
     "Fetched the current version of an official page, because the question asks what is current"),
    ({"name": "agent_step", "action": "live_fetch", "valid": False, "found": 0},
     "Couldn't fetch the official page, so it went on with what it had"),
    ({"name": "agent_step", "action": "rules", "valid": False, "problem": "rules was already done with this query"},
     "The agent made a choice that couldn't be used and chose again"),
    ({"name": "agent_step", "action": "ask_user", "valid": True}, "Decided it needs one detail from you"),
    ({"name": "agent_step", "action": "user_reply", "valid": True}, "Read your reply"),
    ({"name": "agent_step", "action": "answer", "valid": True}, "Decided it has what it needs to answer"),
    ({"name": "agent", "outcome": "fallback"}, "The agent's choices weren't usable, so the standard plan took over"),
    ({"name": "agent", "outcome": "answer"}, None),
    ({"name": "evidence", "status": "verified", "partial": True},
     "Checked a part against its source: the quote matches (partially verified)"),
    ({"name": "evidence", "status": "not_covered"}, "Checked a part: the sources found don't cover it"),
    ({"name": "reflect", "action": "live_fetch", "valid": True}, "A part didn't check out; decided to fetch the current page"),
    ({"name": "reflect", "action": "unreadable", "valid": False},
     "Couldn't choose a next attempt, so the standard retry was used"),
    ({"name": "retry", "first": "not_covered", "retry": "verified", "kept": "retry"},
     "The second attempt checked out and replaced the first"),
    ({"name": "retry", "first": "not_covered", "retry": "unverified", "kept": "first"},
     "The second attempt was no better, so the first result stands"),
    ({"name": "retry", "first": "not_covered", "new_chunks": 0}, "The extra attempt found nothing new"),
    ({"name": "monitor", "denied": False, "available": False},
     "The second safety check was unavailable; checked by code rules only"),
    ({"name": "disclaimer", "high_risk": True}, "Added a legal notice for this topic"),
    ({"name": "agent_resume", "found": True}, "Picked up where it stopped, with your reply"),
])
def test_lines(step, line):
    assert describe(step) == line


def test_a_line_never_repeats_free_text_from_the_step():
    """Step fields are safe by design, but a line still only uses counts, statuses and site names."""
    step = {"name": "agent_step", "action": "rules", "valid": False, "problem": "Priya asked about her husband"}
    assert "Priya" not in describe(step)
    assert "secret" not in describe({"name": "retrieval", "chunks": [{"url": "https://www.canada.ca/x.html?secret=1"}]})


@pytest.mark.asyncio
async def test_job_step_events_carry_the_line(monkeypatch):
    from app.services import rag_pipeline as rp
    from app.services.tracing import trace_step

    emitted = []

    async def stream(**_):
        with trace_step("decomposition") as step:
            step["parts"] = 2
        with trace_step("intent"):
            pass
        yield {"type": "done", "full_response": "ok", "sources": [], "metrics": {}}

    async def nothing(*_, **__):
        return None

    async def queued(*_):
        return {"status": "queued"}

    async def no(*_):
        return False

    async def publish(job_id, kind, data=None):
        emitted.append((kind, data))

    monkeypatch.setattr(rp.rag_pipeline, "process_query_stream", stream)
    for name, fn in (("get_job", queued), ("is_cancel_requested", no), ("set_status", nothing), ("publish", publish),
                     ("_save_assistant_message", nothing)):
        monkeypatch.setattr(answer_jobs, name, fn)
    import app.services.tracing as tracing
    monkeypatch.setattr(tracing, "save_trace", nothing)
    assert await answer_jobs._execute_answer_job("j1", 1, "q", None, None, "s1") == "done"
    labels = {d["name"]: d["label"] for kind, d in emitted if kind == "step"}
    assert labels == {"decomposition": "Split the question into 2 parts", "intent": None}
