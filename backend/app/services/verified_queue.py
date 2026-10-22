"""
Verified-path queue and per-user limits (M1.4).

Verified answers (AGENT_MODE=on) run on their own Celery queue and worker, so fast-path answers never wait behind
them, and their model calls give way to waiting fast-path calls (llm_slots priority). They share one CPU, so they
wait in line; every waiting job is told its place: event "queue" {"position", "eta_s"} ("You're #2 in line").

Limits per user, checked and recorded in one Redis script so two simultaneous requests can't both slip through:
  - VERIFIED_JOBS_IN_FLIGHT_PER_USER (3 = 1 running + 2 waiting), refused with reason "in_flight";
  - VERIFIED_JOBS_PER_HOUR, refused with reason "hourly" and the seconds until a slot frees up.
Refused requests don't count. A job leaves the user's in-flight set when it ends; members whose job has ended or
expired are also dropped at the next check, so a crashed worker can't lock a user out.

Redis keys:
  verified:queue                 zset  waiting job ids, scored by arrival number (strict FIFO)
  verified:seq                   counter  arrival numbers (a timestamp can tie, and ties sort by job id)
  verified:user:{id}:inflight    set   the user's queued or running verified jobs
  verified:user:{id}:hour        zset  the user's admitted jobs in the last hour, scored by time
  verified:avg_seconds           string  moving average of verified job durations (for the wait estimate)
  verified:running               zset  verified jobs running now, scored by lease expiry (a crashed worker's
                                       entry lapses after the job budget)
  verified:idle_since            string  when a verified job last finished (the worker became free)
"""

import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

QUEUE_KEY = "verified:queue"
SEQ_KEY = "verified:seq"
AVG_KEY = "verified:avg_seconds"
RUNNING_KEY = "verified:running"
IDLE_SINCE_KEY = "verified:idle_since"
_AVG_WEIGHT = 0.3  # weight of the newest job time in the moving average


def _inflight_key(user_id: int) -> str:
    return f"verified:user:{user_id}:inflight"


def _hourly_key(user_id: int) -> str:
    return f"verified:user:{user_id}:hour"


# KEYS: inflight, hourly, queue, arrival counter. ARGV: now, max in flight, max per hour, job id, inflight ttl.
# Returns {1, position} | {-1, 0} (too many in flight) | {-2, seconds until the oldest admission is an hour old}
_ADMIT = """
for _, member in ipairs(redis.call('SMEMBERS', KEYS[1])) do
    local status = redis.call('HGET', 'job:' .. member, 'status')
    if (not status) or status == 'done' or status == 'error' or status == 'cancelled' then
        redis.call('SREM', KEYS[1], member)
    end
end
if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then
    return {-1, 0}
end
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 3600)
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then
    local oldest = redis.call('ZRANGE', KEYS[2], 0, 0, 'WITHSCORES')
    return {-2, math.ceil(tonumber(oldest[2]) + 3600 - now)}
end
redis.call('SADD', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
redis.call('ZADD', KEYS[2], now, ARGV[4])
redis.call('EXPIRE', KEYS[2], 3600)
redis.call('ZADD', KEYS[3], redis.call('INCR', KEYS[4]), ARGV[4])
return {1, redis.call('ZRANK', KEYS[3], ARGV[4]) + 1}
"""


@dataclass(frozen=True)
class Admission:
    admitted: bool
    reason: Optional[str] = None        # in_flight | hourly
    position: Optional[int] = None
    eta_s: Optional[int] = None
    retry_after_s: Optional[int] = None


def _redis():
    from app.services.answer_jobs import _redis as job_redis
    return job_redis()


async def average_seconds() -> float:
    value = await _redis().get(AVG_KEY)
    try:
        return float(value) if value else settings.VERIFIED_JOB_ESTIMATE_SECONDS
    except ValueError:
        return settings.VERIFIED_JOB_ESTIMATE_SECONDS


def _eta(position: int, average: float) -> int:
    """Roughly: the job running now plus each job ahead, then this one starts. Whole seconds."""
    return int(math.ceil(position * average))


async def admit(user_id: int, job_id: str) -> Admission:
    """Check the user's limits and join the line, atomically."""
    code, value = await _redis().eval(
        _ADMIT, 4, _inflight_key(user_id), _hourly_key(user_id), QUEUE_KEY, SEQ_KEY,
        time.time(), settings.VERIFIED_JOBS_IN_FLIGHT_PER_USER, settings.VERIFIED_JOBS_PER_HOUR, job_id,
        settings.ANSWER_JOB_TTL_SECONDS)
    code, value = int(code), int(value)
    if code == -1:
        return Admission(False, reason="in_flight")
    if code == -2:
        return Admission(False, reason="hourly", retry_after_s=max(1, value))
    return Admission(True, position=value, eta_s=_eta(value, await average_seconds()))


async def publish_positions() -> None:
    """Tell every waiting job its place in line when it changes; drop jobs that started, ended or expired."""
    from app.services.answer_jobs import TERMINAL, get_job, publish, _job_key

    redis = _redis()
    average = await average_seconds()
    position = 0
    for job_id in await redis.zrange(QUEUE_KEY, 0, -1):
        job = await get_job(job_id)
        if job is None or job.get("status") in TERMINAL or job.get("status") == "running":
            await redis.zrem(QUEUE_KEY, job_id)
            continue
        position += 1
        if job.get("queue_position") == str(position):
            continue
        fields = {"queue_position": str(position)}
        if position == 1 and not job.get("front_at"):
            fields["front_at"] = str(time.time())  # next in line: from now, a long wait means no worker (B5)
        await redis.hset(_job_key(job_id), mapping=fields)
        await publish(job_id, "queue", {"position": position, "eta_s": _eta(position, average)})


async def started(job_id: str) -> None:
    redis = _redis()
    await redis.zrem(QUEUE_KEY, job_id)
    await redis.zadd(RUNNING_KEY, {job_id: time.time() + settings.ANSWER_JOB_BUDGET_SECONDS + 60})
    await publish_positions()


async def front_wait_seconds(front_at: float) -> Optional[float]:
    """
    How long the job at the front has waited for a free verified worker: None while a verified job is running
    (waiting behind it is normal, however long it takes), else the time since it reached the front or since
    the worker became free, whichever is later. A long wait then means no verified worker is running.
    """
    redis = _redis()
    now = time.time()
    await redis.zremrangebyscore(RUNNING_KEY, "-inf", now)
    if await redis.zcard(RUNNING_KEY):
        return None
    idle_since = await redis.get(IDLE_SINCE_KEY)
    return now - max(front_at, float(idle_since) if idle_since else 0.0)


async def finished(job_id: str, user_id: Optional[int], seconds: Optional[float] = None) -> None:
    """The job ended (any way): free the user's slot, update the wait estimate, move the line up."""
    redis = _redis()
    await redis.zrem(QUEUE_KEY, job_id)
    if await redis.zrem(RUNNING_KEY, job_id):
        await redis.set(IDLE_SINCE_KEY, str(time.time()), ex=settings.ANSWER_JOB_TTL_SECONDS)
    if user_id is not None:
        await redis.srem(_inflight_key(user_id), job_id)
    if seconds is not None and seconds > 0:
        average = await average_seconds()
        await redis.set(AVG_KEY, str(round((1 - _AVG_WEIGHT) * average + _AVG_WEIGHT * seconds, 1)))
    await publish_positions()
