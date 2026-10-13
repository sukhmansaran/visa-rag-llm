"""
M0.4c spike: run the LangGraph spike graph inside a Celery task, then kill the worker mid-run and resume.

The task starts a run, or resumes the thread's pending run if a checkpoint exists, so a redelivered
message (acks_late + reject_on_worker_lost) continues where the killed worker stopped.

Start a worker (from backend/):
  .venv\\Scripts\\python.exe -m celery -A scripts.spikes.langgraph_spike_worker worker --pool=solo -Q langgraph_spike --loglevel=info
Send a task:
  .venv\\Scripts\\python.exe scripts\\spikes\\langgraph_spike_worker.py send --thread k1
"""

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from celery import Celery  # noqa: E402

from app.core.config import settings  # noqa: E402

QUEUE = "langgraph_spike"

app = Celery("langgraph_spike", broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND)
app.conf.update(
    task_default_queue=QUEUE,
    task_acks_late=True,               # ack only after the task finished ...
    task_reject_on_worker_lost=True,   # ... so a killed worker's task is redelivered
    worker_prefetch_multiplier=1,
    # Redis redelivers unacked messages after this; the app default is 1 hour, short here for the test.
    # Must exceed the longest run, or a still-running task is delivered twice.
    broker_transport_options={"visibility_timeout": 90},
    result_expires=3600,
)


@app.task(name="spike.run_graph")
def run_graph_task(thread_id: str, question: str) -> dict:
    from scripts.spikes import langgraph_spike as spike
    from app.services.llm import llm_service

    async def run():
        try:
            # Resume if this thread already has a pending checkpoint (redelivery after a crash), else start
            state = await spike.show_state(thread_id)
            if state["next"]:
                return await spike.run_graph(thread_id)
            if state["checkpoints"]:
                return {"thread": thread_id, "status": "already finished"}
            return await spike.run_graph(thread_id, question)
        finally:
            await llm_service.close()

    # psycopg async cannot run on Windows' default ProactorEventLoop
    return asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["send"])
    ap.add_argument("--thread", required=True)
    ap.add_argument("--question", default="How many hours can a study permit holder work off campus?")
    args = ap.parse_args()
    result = run_graph_task.apply_async(args=[args.thread, args.question], queue=QUEUE)
    print("sent", result.id)
