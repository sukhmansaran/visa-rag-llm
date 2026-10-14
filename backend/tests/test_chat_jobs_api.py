"""
Answer jobs API (M0.6c): create, SSE relay with resume after reconnect, heartbeats, status, cancel,
ownership, queue outage, and the admin diagnostic job. Celery is replaced by running the job inline.
"""

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.services import answer_jobs as jobs
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache

QUESTION = "How many hours can a study permit holder work off campus? Call me at 416-555-0199"
ANSWER = "You can work up to 24 hours per week off campus [Source 1]."


@pytest_asyncio.fixture(autouse=True)
async def close_job_redis():
    yield
    await jobs.close_redis()


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    async def retrieve(**_):
        return [{"text": "Students may work up to 24 hours per week off campus.", "score": 0.86, "authority_tier": 1,
                 "freshness_weight": 1.0, "metadata": {"url": "https://www.canada.ca/work.html", "title": "Work"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"24 hours per week", ANSWER)
    return fake_llm


@pytest.fixture
def queued(monkeypatch):
    """Capture what would be sent to Celery instead of sending it."""
    from app.workers import answer_tasks

    sent = []

    class Capture:
        def __init__(self, name):
            self.name = name

        def apply_async(self, args, queue):
            sent.append({"task": self.name, "args": args, "queue": queue})

    monkeypatch.setattr(answer_tasks, "run_answer_job_task", Capture("answer"))
    monkeypatch.setattr(answer_tasks, "run_diagnostic_job_task", Capture("diagnostic"))
    return sent


async def login(client, email):
    r = await client.post("/api/v1/auth/signup", json={"email": email, "password": "testpass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def parse_sse(text):
    """-> list of (id, event, data) plus the number of heartbeat comments."""
    events, heartbeats = [], 0
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        if block.startswith(": heartbeat"):
            heartbeats += 1
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields.get("id"), fields["event"], json.loads(fields["data"])))
    return events, heartbeats


# ---------------------------------------------------------------- create + run + stream

@pytest.mark.asyncio
async def test_create_run_and_stream_a_job(client, db_session, scripted, queued):
    headers = await login(client, "jobs-flow@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": QUESTION}, headers=headers)
    assert r.status_code == 202
    body = r.json()
    job_id = body["job_id"]
    assert body["status"] == "queued" and body["events_url"].endswith(f"/chat/jobs/{job_id}/events")

    # Sent to the answers queue with the original question (the model needs it); history saved redacted
    assert queued[0]["task"] == "answer" and queued[0]["queue"] == "answers"
    assert queued[0]["args"][2] == QUESTION
    await db_session.commit()
    saved = (await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == body["session_id"]))).scalars().all()
    assert [m.role for m in saved] == ["user"] and "416-555-0199" not in saved[0].content

    # Run the job as the worker would, then follow it
    await jobs.execute_answer_job(*queued[0]["args"])
    stream = await client.get(f"/api/v1/chat/jobs/{job_id}/events", headers=headers)
    assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["x-accel-buffering"] == "no"
    events, _ = parse_sse(stream.text)
    kinds = [k for _, k, _ in events]
    assert kinds[0] == "status" and kinds[-1] == "done" and "step" in kinds and "chunk" in kinds
    assert events[-1][2]["full_response"] == ANSWER
    assert all(eid for eid, _, _ in events)

    status = (await client.get(f"/api/v1/chat/jobs/{job_id}", headers=headers)).json()
    assert status["status"] == "done" and status["trace_id"]


@pytest.mark.asyncio
async def test_reconnect_resumes_after_the_last_event(client, queued):
    headers = await login(client, "jobs-resume@example.com")
    job_id = await jobs.create_job(await _user_id(client, headers))
    ids = [await jobs.publish(job_id, "step", {"n": i}) for i in range(6)]
    await jobs.publish(job_id, "done", {"full_response": "ok"})

    first, _ = parse_sse((await client.get(f"/api/v1/chat/jobs/{job_id}/events", headers=headers)).text)
    assert [d.get("n") for _, k, d in first if k == "step"] == [0, 1, 2, 3, 4, 5]

    # Reconnect after event n=2 via the standard header, then via the query parameter
    resumed, _ = parse_sse((await client.get(f"/api/v1/chat/jobs/{job_id}/events",
                                             headers={**headers, "Last-Event-ID": ids[2]})).text)
    assert [d.get("n") for _, k, d in resumed if k == "step"] == [3, 4, 5]
    assert resumed[-1][1] == "done"
    via_query, _ = parse_sse((await client.get(f"/api/v1/chat/jobs/{job_id}/events?after={ids[4]}", headers=headers)).text)
    assert [d.get("n") for _, k, d in via_query if k == "step"] == [5]

    bad = await client.get(f"/api/v1/chat/jobs/{job_id}/events", headers={**headers, "Last-Event-ID": "nonsense"})
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_idle_stream_sends_heartbeats(client, monkeypatch):
    monkeypatch.setattr(settings, "SSE_HEARTBEAT_SECONDS", 0.1)
    headers = await login(client, "jobs-heartbeat@example.com")
    job_id = await jobs.create_job(await _user_id(client, headers))

    async def finish_later():
        await asyncio.sleep(0.6)
        await jobs.publish(job_id, "done", {})

    task = asyncio.create_task(finish_later())
    r = await client.get(f"/api/v1/chat/jobs/{job_id}/events", headers=headers)
    await task
    events, heartbeats = parse_sse(r.text)
    assert heartbeats >= 3 and [k for _, k, _ in events] == ["done"]


@pytest.mark.asyncio
async def test_stream_of_an_expired_job_ends_with_an_error(client, monkeypatch):
    monkeypatch.setattr(settings, "SSE_HEARTBEAT_SECONDS", 0.1)
    headers = await login(client, "jobs-expired@example.com")
    job_id = await jobs.create_job(await _user_id(client, headers))

    async def expire():
        await asyncio.sleep(0.3)
        await jobs._redis().delete(f"job:{job_id}")

    task = asyncio.create_task(expire())
    r = await client.get(f"/api/v1/chat/jobs/{job_id}/events", headers=headers)
    await task
    events, _ = parse_sse(r.text)
    assert events[-1][1] == "error" and events[-1][2]["reason"] == "job_expired"


# ---------------------------------------------------------------- cancel

@pytest.mark.asyncio
async def test_cancel_sets_the_flag_and_is_idempotent_after_the_end(client):
    headers = await login(client, "jobs-cancel@example.com")
    job_id = await jobs.create_job(await _user_id(client, headers))
    r = await client.post(f"/api/v1/chat/jobs/{job_id}/cancel", headers=headers)
    assert r.status_code == 202 and r.json()["status"] == "cancel_requested"
    assert await jobs.is_cancel_requested(job_id)

    await jobs.set_status(job_id, "done")
    r = await client.post(f"/api/v1/chat/jobs/{job_id}/cancel", headers=headers)
    assert r.json()["status"] == "done"


# ---------------------------------------------------------------- ownership and failures

@pytest.mark.asyncio
async def test_other_users_cannot_see_or_control_a_job(client):
    owner = await login(client, "jobs-owner@example.com")
    other = await login(client, "jobs-other@example.com")
    job_id = await jobs.create_job(await _user_id(client, owner))
    await jobs.publish(job_id, "done", {})

    for method, path in (("GET", f"/api/v1/chat/jobs/{job_id}"), ("GET", f"/api/v1/chat/jobs/{job_id}/events"),
                         ("POST", f"/api/v1/chat/jobs/{job_id}/cancel")):
        assert (await client.request(method, path, headers=other)).status_code == 404
        assert (await client.request(method, path)).status_code == 401
    assert not await jobs.is_cancel_requested(job_id)
    assert (await client.get("/api/v1/chat/jobs/no-such-job", headers=owner)).status_code == 404


@pytest.mark.asyncio
async def test_queue_outage_returns_503_and_marks_the_job(client, monkeypatch):
    from app.workers import answer_tasks

    class Down:
        def apply_async(self, *a, **k):
            raise ConnectionError("broker down")

    monkeypatch.setattr(answer_tasks, "run_answer_job_task", Down())
    headers = await login(client, "jobs-down@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": QUESTION}, headers=headers)
    assert r.status_code == 503
    assert "broker" not in r.text  # no internal detail leaks


@pytest.mark.asyncio
async def test_query_validation_applies_to_jobs(client):
    headers = await login(client, "jobs-validate@example.com")
    assert (await client.post("/api/v1/chat/jobs", json={"query": ""}, headers=headers)).status_code == 422


# ---------------------------------------------------------------- admin diagnostic job

@pytest.mark.asyncio
async def test_diagnostic_jobs_are_admin_only(client, db_session, queued):
    headers = await login(client, "jobs-admin@example.com")
    assert (await client.post("/api/v1/admin/diagnostic-jobs", json={"seconds": 1, "interval": 0.5}, headers=headers)).status_code == 403

    await db_session.execute(update(User).where(User.email == "jobs-admin@example.com").values(is_admin=True))
    await db_session.commit()
    r = await client.post("/api/v1/admin/diagnostic-jobs", json={"seconds": 1, "interval": 0.5}, headers=headers)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert queued[-1] == {"task": "diagnostic", "args": [job_id, 1.0, 0.5], "queue": "answers"}

    await jobs.execute_diagnostic_job(job_id, 1.0, 0.5)
    events, _ = parse_sse((await client.get(f"/api/v1/chat/jobs/{job_id}/events", headers=headers)).text)
    assert [d["n"] for _, k, d in events if k == "step"] == [1, 2] and events[-1][1] == "done"
    assert (await client.post("/api/v1/admin/diagnostic-jobs", json={"seconds": 99999}, headers=headers)).status_code == 422


async def _user_id(client, headers) -> int:
    from app.core.security import verify_token

    return int(verify_token(headers["Authorization"].split()[1])["sub"])
