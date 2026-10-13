"""
M0.4c LangGraph spike: a 3-node graph over existing Pendu services with a Postgres checkpointer.

Nodes: analyse (input guardrail + intent) -> retrieve (Chroma) -> answer (LLM gateway).
Every node start/finish is appended to logs/langgraph_spike_nodes.jsonl, so a resumed run shows exactly
which nodes ran again. Node updates are streamed (stream_mode="updates") and logged to
logs/langgraph_spike_events.jsonl.

Checkpoints go to a separate database (visa_chatbot_agent_spike), never the dev database.
Windows: psycopg async needs a SelectorEventLoop (the default ProactorEventLoop fails), so every entry
point runs with asyncio.run(..., loop_factory=asyncio.SelectorEventLoop).

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\spikes\\langgraph_spike.py run    --thread t1 --question "..."
  .venv\\Scripts\\python.exe scripts\\spikes\\langgraph_spike.py resume --thread t1
  .venv\\Scripts\\python.exe scripts\\spikes\\langgraph_spike.py state  --thread t1
  .venv\\Scripts\\python.exe scripts\\spikes\\langgraph_spike.py bench  --n 20
Env: SPIKE_SLOW_SECONDS=<n> makes the retrieve node sleep (a window to kill the worker).
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, TypedDict

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.guardrails.input_guardrail import input_guardrail  # noqa: E402
from app.services.intent_parser import intent_parser  # noqa: E402
from app.services.llm import llm_service  # noqa: E402
from app.services.rag_pipeline import GROUNDED_SYSTEM_PROMPT  # noqa: E402
from app.services.retrieval import retrieval_service  # noqa: E402

LOGS = BACKEND / "logs"
NODE_LOG = LOGS / "langgraph_spike_nodes.jsonl"
EVENT_LOG = LOGS / "langgraph_spike_events.jsonl"
SPIKE_DB = "visa_chatbot_agent_spike"
SPIKE_DSN = re.sub(r"^postgresql\+asyncpg://", "postgresql://", settings.DATABASE_URL).rsplit("/", 1)[0] + "/" + SPIKE_DB


class SpikeState(TypedDict, total=False):
    question: str
    allowed: bool
    intent: str
    chunks: List[Dict[str, Any]]
    answer: str


def _log(path: Path, record: Dict[str, Any]) -> None:
    LOGS.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="milliseconds"), "pid": os.getpid(), **record}) + "\n")


def _bench(config: Dict[str, Any]) -> bool:
    return bool(config.get("configurable", {}).get("bench"))


def _thread(config: Dict[str, Any]) -> str:
    return config.get("configurable", {}).get("thread_id", "?")


async def analyse(state: SpikeState, config) -> SpikeState:
    if not _bench(config):
        _log(NODE_LOG, {"thread": _thread(config), "node": "analyse", "phase": "start"})
    verdict = input_guardrail.evaluate(state["question"])
    intent = (await intent_parser.parse_intent(state["question"])).get("intent", "general")
    if not _bench(config):
        _log(NODE_LOG, {"thread": _thread(config), "node": "analyse", "phase": "end"})
    return {"allowed": verdict.allowed, "intent": intent}


async def retrieve(state: SpikeState, config) -> SpikeState:
    if _bench(config):
        return {"chunks": [{"text": "bench", "score": 1.0}]}
    _log(NODE_LOG, {"thread": _thread(config), "node": "retrieve", "phase": "start"})
    chunks = await retrieval_service.retrieve(query=state["question"], country="Canada", visa_type="Student",
                                              intent=state.get("intent", "general"), top_k=settings.RAG_TOP_K)
    slow = float(os.getenv("SPIKE_SLOW_SECONDS", "0"))
    if slow:
        await asyncio.sleep(slow)
    _log(NODE_LOG, {"thread": _thread(config), "node": "retrieve", "phase": "end", "chunks": len(chunks)})
    # Keep checkpoints small: text, score and URL only
    return {"chunks": [{"text": c.get("text", "")[:1200], "score": c.get("score"),
                        "url": (c.get("metadata") or {}).get("url")} for c in chunks]}


async def answer(state: SpikeState, config) -> SpikeState:
    if _bench(config):
        return {"answer": "bench"}
    _log(NODE_LOG, {"thread": _thread(config), "node": "answer", "phase": "start"})
    context = "\n\n".join(f"[Source {i + 1}] {c['text']}" for i, c in enumerate(state.get("chunks", [])))
    text = await llm_service.generate_answer(system_prompt=GROUNDED_SYSTEM_PROMPT, user_prompt=f"User Question: {state['question']}",
                                             context=context, temperature=0.0, max_tokens=200, role="answer")
    _log(NODE_LOG, {"thread": _thread(config), "node": "answer", "phase": "end"})
    return {"answer": text}


def build_graph():
    graph = StateGraph(SpikeState)
    graph.add_node("analyse", analyse)
    graph.add_node("retrieve", retrieve)
    graph.add_node("answer", answer)
    graph.add_edge(START, "analyse")
    graph.add_conditional_edges("analyse", lambda s: "retrieve" if s.get("allowed") else END)
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)
    return graph


@asynccontextmanager
async def postgres_checkpointer():
    async with AsyncPostgresSaver.from_conn_string(SPIKE_DSN) as saver:
        await saver.setup()  # creates the checkpoint tables in the spike database (idempotent)
        yield saver


async def run_graph(thread_id: str, question: str = None) -> Dict[str, Any]:
    """Start a run, or resume the pending one for this thread when no question is given."""
    async with postgres_checkpointer() as saver:
        app = build_graph().compile(checkpointer=saver)
        config = {"configurable": {"thread_id": thread_id}}
        existing = await app.aget_state(config)
        if question is None:
            if not existing.next:
                return {"thread": thread_id, "status": "nothing to resume", "values": existing.values}
            graph_input, mode = None, f"resume (next: {list(existing.next)})"
        else:
            graph_input, mode = {"question": question}, "start"
        _log(EVENT_LOG, {"thread": thread_id, "event": "run", "mode": mode})
        print(f"[{thread_id}] {mode}", flush=True)
        async for update in app.astream(graph_input, config, stream_mode="updates"):
            for node, values in update.items():
                summary = {k: (f"{len(v)} items" if isinstance(v, list) else str(v)[:80]) for k, v in (values or {}).items()}
                _log(EVENT_LOG, {"thread": thread_id, "event": "node_done", "node": node, "update": summary})
                print(f"[{thread_id}] {node} done: {summary}", flush=True)
        final = await app.aget_state(config)
        return {"thread": thread_id, "status": "finished" if not final.next else "paused",
                "answer": final.values.get("answer"), "next": list(final.next)}


async def show_state(thread_id: str) -> Dict[str, Any]:
    async with postgres_checkpointer() as saver:
        app = build_graph().compile(checkpointer=saver)
        config = {"configurable": {"thread_id": thread_id}}
        state = await app.aget_state(config)
        history = [c async for c in app.aget_state_history(config)]
        return {"next": list(state.next), "keys": sorted(state.values), "checkpoints": len(history),
                "answer": (state.values.get("answer") or "")[:200]}


async def bench(n: int) -> Dict[str, Any]:
    """Framework + checkpoint overhead per run, with trivial node bodies (no retrieval, no model)."""
    question = "How many hours can a study permit holder work off campus?"
    cfg = {"configurable": {"bench": True}}

    t0 = time.perf_counter()
    for _ in range(n):
        state: SpikeState = {"question": question}
        state.update(await analyse(state, cfg))
        state.update(await retrieve(state, cfg))
        state.update(await answer(state, cfg))
    direct_ms = (time.perf_counter() - t0) * 1000 / n

    app = build_graph().compile(checkpointer=InMemorySaver())
    t0 = time.perf_counter()
    for i in range(n):
        await app.ainvoke({"question": question}, {"configurable": {"thread_id": f"mem-{i}", "bench": True}})
    memory_ms = (time.perf_counter() - t0) * 1000 / n

    async with postgres_checkpointer() as saver:
        app = build_graph().compile(checkpointer=saver)
        stamp = datetime.now().strftime("%H%M%S")
        t0 = time.perf_counter()
        for i in range(n):
            await app.ainvoke({"question": question}, {"configurable": {"thread_id": f"bench-{stamp}-{i}", "bench": True}})
        postgres_ms = (time.perf_counter() - t0) * 1000 / n

    return {"runs": n, "direct_ms": round(direct_ms, 1), "graph_in_memory_ms": round(memory_ms, 1),
            "graph_postgres_ms": round(postgres_ms, 1),
            "overhead_postgres_vs_direct_ms": round(postgres_ms - direct_ms, 1)}


async def _main(args) -> None:
    try:
        if args.cmd == "run":
            result = await run_graph(args.thread, args.question)
        elif args.cmd == "resume":
            result = await run_graph(args.thread)
        elif args.cmd == "state":
            result = await show_state(args.thread)
        else:
            result = await bench(args.n)
        print("RESULT", json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        await llm_service.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "resume", "state", "bench"])
    ap.add_argument("--thread", default="spike-1")
    ap.add_argument("--question", default="How many hours can a study permit holder work off campus?")
    ap.add_argument("--n", type=int, default=20)
    asyncio.run(_main(ap.parse_args()), loop_factory=asyncio.SelectorEventLoop)
