"""
M1.4 verified-path queue: per-user limits, place in line, own worker, and model-call priority so fast answers
never wait behind verified ones. Real Redis (test db 15); Celery is captured, the model is scripted.
"""

import asyncio
import time

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.services import answer_jobs as jobs
from app.services import llm as llm_module
from app.services import rag_pipeline as rp
from app.services import verified_queue as vq
from app.services.cache_service import intent_cache
from app.services.llm_slots import SLOTS_KEY, WAITING_KEY, global_slots

VERIFIED_QUESTION = "Can I still get a PGWP if I work off campus more than 24 hours per week?"
FAST_QUESTION = "How many hours can a study permit holder work off campus?"
ANSWER = "You can work up to 24 hours per week off campus [Source 1]."


@pytest_asyncio.fixture(autouse=True)
async def clean_redis():
    async def wipe():
        redis = jobs._redis()
        keys = [k async for k in redis.scan_iter("verified:*")] + [SLOTS_KEY, WAITING_KEY]
        await redis.delete(*keys)

    await wipe()
    yield
    await wipe()
    await global_slots.close()
    await jobs.close_redis()


@pytest.fixture
def agent_on(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MODE", "on")


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
    monkeypatch.setattr(answer_tasks, "run_verified_answer_job_task", Capture("verified"))
    return sent


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


async def login(client, email):
    r = await client.post("/api/v1/auth/signup", json={"email": email, "password": "testpass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()


async def queue_events(job_id):
    return [d for _, kind, d in await jobs.read_events(job_id) if kind == "queue"]


# ---------------------------------------------------------------- routing

@pytest.mark.asyncio
async def test_verified_questions_go_to_their_own_queue_and_fast_ones_do_not(client, agent_on, queued):
    headers, _ = await login(client, "route@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)
    assert r.status_code == 202 and r.json()["path"] == "verified"
    assert r.json()["queue"] == {"position": 1, "eta_s": round(settings.VERIFIED_JOB_ESTIMATE_SECONDS)}
    r = await client.post("/api/v1/chat/jobs", json={"query": FAST_QUESTION}, headers=headers)
    assert r.status_code == 202 and r.json()["path"] == "fast" and "queue" not in r.json()
    assert [(s["task"], s["queue"]) for s in queued] == [("verified", "verified"), ("answer", "answers")]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "shadow"])
async def test_without_agent_mode_on_everything_is_fast(client, queued, monkeypatch, mode):
    monkeypatch.setattr(settings, "AGENT_MODE", mode)
    headers, _ = await login(client, f"route-{mode}@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)
    assert r.json()["path"] == "fast" and queued[0]["queue"] == "answers"


@pytest.mark.asyncio
async def test_a_question_the_guardrail_refuses_is_not_queued_as_verified(client, agent_on, queued):
    headers, _ = await login(client, "route-refused@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": "¿Puedo obtener un PGWP si trabajo más de 24 horas?"},
                          headers=headers)
    assert r.json()["path"] == "fast"


# ---------------------------------------------------------------- limits

@pytest.mark.asyncio
async def test_a_burst_of_ten_from_one_user_is_limited_and_other_users_are_not(client, db_session, agent_on, queued):
    headers, _ = await login(client, "burst@example.com")
    responses = [await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)
                 for _ in range(10)]
    codes = [r.status_code for r in responses]
    assert codes == [202] * 3 + [429] * 7
    assert sorted(r.json()["queue"]["position"] for r in responses if r.status_code == 202) == [1, 2, 3]
    refusal = next(r for r in responses if r.status_code == 429).json()["detail"]
    assert "3 of those running or waiting" in refusal

    # Only admitted questions were stored or sent
    await db_session.commit()
    stored = (await db_session.execute(select(ChatMessage).where(ChatMessage.role == "user"))).scalars().all()
    assert len(stored) == 3 and len(queued) == 3

    # Another user is unaffected: a fast question goes straight to the answers queue, a verified one joins the line
    other, _ = await login(client, "other@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": FAST_QUESTION}, headers=other)
    assert r.status_code == 202 and r.json()["path"] == "fast" and queued[-1]["queue"] == "answers"
    r = await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=other)
    assert r.status_code == 202 and r.json()["queue"]["position"] == 4


@pytest.mark.asyncio
async def test_simultaneous_requests_cannot_slip_past_the_limit():
    """Checking and recording happen in one Redis script, so 10 at once still admits exactly 3."""
    ids = [await jobs.create_job(6, path="verified") for _ in range(10)]
    admissions = await asyncio.gather(*[vq.admit(6, i) for i in ids])
    assert sum(a.admitted for a in admissions) == 3
    assert sorted(a.position for a in admissions if a.admitted) == [1, 2, 3]


@pytest.mark.asyncio
async def test_a_failed_save_gives_the_place_back(client, agent_on, queued, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    headers, _ = await login(client, "save-fails@example.com")

    async def broken_commit(self):
        raise RuntimeError("database down")
    monkeypatch.setattr(AsyncSession, "commit", broken_commit)
    r = await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)
    assert r.status_code == 500
    assert await jobs._redis().zcard(vq.QUEUE_KEY) == 0 and queued == []
    in_flight = [k async for k in jobs._redis().scan_iter("verified:user:*:inflight")]
    assert [await jobs._redis().scard(k) for k in in_flight] in ([], [0])  # the user's place was given back


@pytest.mark.asyncio
async def test_a_finished_job_frees_the_users_place():
    ids = [await jobs.create_job(7, path="verified") for _ in range(4)]
    assert [(await vq.admit(7, i)).admitted for i in ids] == [True, True, True, False]
    await jobs.set_status(ids[0], "done")
    await vq.finished(ids[0], 7)
    assert (await vq.admit(7, ids[3])).admitted


@pytest.mark.asyncio
async def test_an_ended_or_expired_job_never_locks_the_user_out():
    """A crashed worker never calls finished(): the next check drops jobs that ended or expired."""
    ids = [await jobs.create_job(8, path="verified") for _ in range(3)]
    for i in ids:
        assert (await vq.admit(8, i)).admitted
    await jobs.set_status(ids[0], "error")
    await jobs.delete_job(ids[1])  # expired
    new = [await jobs.create_job(8, path="verified") for _ in range(2)]
    assert [(await vq.admit(8, i)).admitted for i in new] == [True, True]


@pytest.mark.asyncio
async def test_hourly_cap(monkeypatch):
    monkeypatch.setattr(settings, "VERIFIED_JOBS_PER_HOUR", 2)
    ids = [await jobs.create_job(9, path="verified") for _ in range(3)]
    for i in ids[:2]:
        assert (await vq.admit(9, i)).admitted
        await jobs.set_status(i, "done")
        await vq.finished(i, 9)
    refused = await vq.admit(9, ids[2])
    assert (refused.admitted, refused.reason) == (False, "hourly")
    assert 3590 <= refused.retry_after_s <= 3600


@pytest.mark.asyncio
async def test_hourly_refusal_says_when_to_retry(client, agent_on, queued, monkeypatch):
    monkeypatch.setattr(settings, "VERIFIED_JOBS_PER_HOUR", 1)
    headers, _ = await login(client, "hourly@example.com")
    assert (await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)).status_code == 202
    r = await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 3500
    assert "1 of those per hour" in r.json()["detail"] and "60 minutes" in r.json()["detail"]


# ---------------------------------------------------------------- place in line

@pytest.mark.asyncio
async def test_place_in_line_is_streamed_and_moves_up(client, agent_on, queued):
    users = [await login(client, f"line{n}@example.com") for n in range(3)]
    job_ids = []
    for headers, _ in users:
        r = await client.post("/api/v1/chat/jobs", json={"query": VERIFIED_QUESTION}, headers=headers)
        job_ids.append(r.json()["job_id"])
    estimate = settings.VERIFIED_JOB_ESTIMATE_SECONDS
    assert [await queue_events(j) for j in job_ids] == [
        [{"position": 1, "eta_s": round(estimate)}],
        [{"position": 2, "eta_s": round(2 * estimate)}],
        [{"position": 3, "eta_s": round(3 * estimate)}]]

    await vq.started(job_ids[0])  # the worker takes the first one
    assert (await queue_events(job_ids[1]))[-1]["position"] == 1
    assert (await queue_events(job_ids[2]))[-1]["position"] == 2

    # Stopping a waiting job ends it at once and moves the line up
    headers = users[1][0]
    r = await client.post(f"/api/v1/chat/jobs/{job_ids[1]}/cancel", headers=headers)
    assert r.json()["status"] == "cancelled"
    assert (await jobs.get_job(job_ids[1]))["status"] == "cancelled"
    assert (await queue_events(job_ids[2]))[-1]["position"] == 1


@pytest.mark.asyncio
async def test_waiting_behind_others_is_not_mistaken_for_a_missing_worker(monkeypatch):
    from app.api.v1.chat_jobs import _check_unstarted

    monkeypatch.setattr(settings, "JOB_QUEUED_GIVE_UP_SECONDS", 1)
    front, behind = await jobs.create_job(10, path="verified"), await jobs.create_job(11, path="verified")
    await vq.admit(10, front)
    await vq.admit(11, behind)
    await vq.publish_positions()
    await jobs._redis().hset(jobs._job_key(front), "front_at", str(time.time() - 5))  # at the front for 5 s

    await _check_unstarted(behind, await jobs.get_job(behind))
    assert (await jobs.get_job(behind))["status"] == "queued"
    await _check_unstarted(front, await jobs.get_job(front))
    assert (await jobs.get_job(front))["status"] == "error"  # no worker took it: told, and the line moves up
    assert (await queue_events(behind))[-1]["position"] == 1


# ---------------------------------------------------------------- running a verified job

@pytest.mark.asyncio
async def test_a_verified_job_runs_with_low_model_priority_and_frees_its_place(client, db_session, scripted, monkeypatch):
    seen = []
    real_stream = llm_module.llm_service.generate_answer_stream

    async def stream(**kwargs):
        seen.append(llm_module._priority.get())
        async for token in real_stream(**kwargs):
            yield token
    monkeypatch.setattr(llm_module.llm_service, "generate_answer_stream", stream)

    _, account = await login(client, "priority@example.com")
    user_id = (await db_session.execute(select(User.id).where(User.email == "priority@example.com"))).scalar_one()
    job_id = await jobs.create_job(user_id, path="verified")
    await vq.admit(user_id, job_id)
    assert await jobs.execute_answer_job(job_id, user_id, FAST_QUESTION, None, None, None, path="verified") == "done"
    assert seen == ["low"]
    assert not await jobs._redis().sismember(vq._inflight_key(user_id), job_id)
    assert await jobs._redis().zscore(vq.QUEUE_KEY, job_id) is None
    assert float(await jobs._redis().get(vq.AVG_KEY)) < settings.VERIFIED_JOB_ESTIMATE_SECONDS  # learned

    # A fast job keeps normal priority
    seen.clear()
    intent_cache.clear()  # or the fast job replays the cached answer without a model call
    fast_id = await jobs.create_job(user_id)
    await jobs.execute_answer_job(fast_id, user_id, FAST_QUESTION)
    assert seen == ["normal"]


@pytest.mark.asyncio
async def test_a_verified_job_stopped_while_waiting_is_skipped_by_the_worker(scripted):
    job_id = await jobs.create_job(13, path="verified")
    await vq.admit(13, job_id)
    await jobs.set_status(job_id, "cancelled")
    assert await jobs.execute_answer_job(job_id, 13, FAST_QUESTION, path="verified") == "cancelled"
    assert scripted.calls == []
    assert not await jobs._redis().exists(vq.AVG_KEY)  # a skipped job teaches the estimate nothing


# ---------------------------------------------------------------- model-call priority

@pytest.mark.asyncio
async def test_a_waiting_fast_call_goes_before_a_waiting_verified_call():
    assert await global_slots.acquire("running", 1, 5)

    order = []

    async def take(token, priority):
        await global_slots.acquire(token, 1, 10, priority=priority)
        order.append(token)

    verified = asyncio.create_task(take("verified", "low"))
    await asyncio.sleep(0.3)  # the verified call started waiting first
    fast = asyncio.create_task(take("fast", "normal"))
    await asyncio.sleep(0.3)
    await global_slots.release("running")
    await asyncio.wait_for(fast, 5)
    assert order == ["fast"] and not verified.done()
    await global_slots.release("fast")
    await asyncio.wait_for(verified, 5)
    assert order == ["fast", "verified"]
    await global_slots.release("verified")


@pytest.mark.asyncio
async def test_a_verified_call_takes_a_free_slot_when_nobody_fast_is_waiting():
    assert await global_slots.acquire("v", 1, 1, priority="low")
    await global_slots.release("v")


@pytest.mark.asyncio
async def test_a_fast_caller_that_gives_up_stops_holding_back_verified_calls():
    assert await global_slots.acquire("running", 1, 5)
    with pytest.raises(asyncio.TimeoutError):
        await global_slots.acquire("impatient", 1, 0.5)
    assert await jobs._redis().zcard(WAITING_KEY) == 0
    await global_slots.release("running")
    assert await global_slots.acquire("v", 1, 1, priority="low")
    await global_slots.release("v")


def test_unknown_priority_is_rejected():
    with pytest.raises(ValueError):
        with llm_module.llm_priority("urgent"):
            pass
