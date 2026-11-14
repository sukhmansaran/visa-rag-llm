"""
Latency and load on this machine (M8.2).

    cd backend
    python scripts/latency_report.py                              # per-path p50/p95 from the last eval gate report
    python scripts/latency_report.py --report logs/rag_eval.json  # ... from another eval report
    python scripts/latency_report.py --concurrency 3              # also: 3 questions at once against the model queue

Per path: the evaluation already times every case end to end and records the model's prompt-read and generation
time, so the table is computed from an eval report (no extra model calls). Paths are the route the API would choose
(fast / verified) and how the answer was produced (source).

Concurrency: the same question is answered once alone, then N different questions are started together, in this
process, through the real pipeline and the real model queue (LLM_MAX_CONCURRENT_CALLS slots shared through Redis).
It shows what a second and third user wait for. Needs Ollama and Redis; takes a few minutes. Questions are fixed
general ones; nothing personal is sent anywhere.

Writes logs/latency_report.json and prints the tables.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

QUESTIONS = [
    "How many hours can an international student work off campus during regular academic sessions?",
    "How much money does a single student need to show as proof of funds for a study permit?",
    "Who needs to give biometrics for a study permit application?",
    "What is a provincial attestation letter and who needs one?",
    "How long is a post-graduation work permit after a two-year program?",
    "Can my spouse work in Canada while I study?",
]


def percentile(values: List[float], p: float) -> float:
    """Nearest-rank percentile; with few values p95 is simply the largest or second largest."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p * (len(ordered) - 1))))]


def by_path(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for case in report["results"]:
        for run in case["run_results"]:
            groups.setdefault((run.get("route") or "?", run.get("source") or "?"), []).append(run)
    rows = []
    for (route, source), runs in sorted(groups.items()):
        latencies = [r["latency_s"] for r in runs]
        speeds = [r["tokens_per_second"] for r in runs if r.get("tokens_per_second")]
        reading = [r["prompt_s"] for r in runs if r.get("prompt_s") is not None]
        writing = [r["generation_s"] for r in runs if r.get("generation_s") is not None]
        rows.append({
            "route": route, "source": source, "n": len(runs),
            "p50_s": percentile(latencies, 0.5), "p95_s": percentile(latencies, 0.95), "max_s": max(latencies),
            # of the LAST model call in each request (what the eval records), not the sum over a verified answer
            "last_call_prompt_s_avg": round(sum(reading) / len(reading), 1) if reading else None,
            "last_call_generation_s_avg": round(sum(writing) / len(writing), 1) if writing else None,
            "tokens_per_second_avg": round(sum(speeds) / len(speeds), 1) if speeds else None,
        })
    return rows


def print_paths(rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    print(f"Per path ({summary.get('model')}, agent mode {summary.get('agent_mode')}, {summary.get('cases')} cases):")
    print(f"  {'route':<9} {'answered by':<18} {'n':>3} {'p50 s':>7} {'p95 s':>7} {'max s':>7} {'tok/s':>6}")
    for row in rows:
        print(f"  {row['route']:<9} {row['source']:<18} {row['n']:>3} {row['p50_s']:>7.1f} {row['p95_s']:>7.1f} "
              f"{row['max_s']:>7.1f} {row['tokens_per_second_avg'] or '':>6}")


async def _answer(question: str) -> Dict[str, Any]:
    from app.services import rag_pipeline as rag_module
    from app.services.tracing import TraceRecorder, activate_trace
    from app.services.triage import FAST, routed_as

    trace = TraceRecorder("latency", query=question)
    started = time.perf_counter()
    with activate_trace(trace), routed_as(FAST):
        result = await rag_module.rag_pipeline.process_query(query=question, context_metadata={"country": "Canada"})
    total = time.perf_counter() - started
    calls = trace.llm_calls or []
    waited = sum(getattr(c, "queue_wait_s", 0) or 0 for c in calls)  # LLMCallStats: time waiting for a model slot
    return {"total_s": round(total, 1), "model_calls": len(calls), "queue_wait_s": round(waited, 1),
            "source": (result.get("metrics") or {}).get("source"), "answered": bool(result.get("answer"))}


async def concurrency(n: int) -> Dict[str, Any]:
    from app.core.config import settings
    from app.services.cache_service import intent_cache

    intent_cache.clear()
    alone = await _answer(QUESTIONS[0])                 # also loads the model, so the next figures are warm
    intent_cache.clear()
    warm = await _answer(QUESTIONS[1])
    intent_cache.clear()
    started = time.perf_counter()
    together = await asyncio.gather(*[_answer(q) for q in QUESTIONS[2:2 + n]], return_exceptions=True)
    wall = time.perf_counter() - started
    finished = [r for r in together if isinstance(r, dict)]
    failed = [type(r).__name__ for r in together if not isinstance(r, dict)]
    return {"slots": settings.LLM_MAX_CONCURRENT_CALLS, "first_call_s": alone["total_s"], "alone_warm_s": warm["total_s"],
            "together": n, "wall_s": round(wall, 1), "each_s": sorted(r["total_s"] for r in finished),
            "queue_wait_s": sorted(r["queue_wait_s"] for r in finished), "failed": failed}


def print_concurrency(c: Dict[str, Any]) -> None:
    print(f"\nConcurrency (fast path, {c['slots']} model slot(s)):")
    print(f"  first answer (model loading): {c['first_call_s']} s; one answer alone, model warm: {c['alone_warm_s']} s")
    print(f"  {c['together']} started together: finished after {c['each_s']} s (all done in {c['wall_s']} s)")
    if any(c["queue_wait_s"]):
        print(f"  time spent waiting for the model slot: {c['queue_wait_s']} s")
    if c["failed"]:
        print(f"  failed: {c['failed']}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Latency per path and behaviour under concurrent requests.")
    parser.add_argument("--report", default=str(BACKEND / "logs" / "eval_gate_last.json"))
    parser.add_argument("--concurrency", type=int, default=0, help="also start N questions together (max 4)")
    parser.add_argument("--out", default=str(BACKEND / "logs" / "latency_report.json"))
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    rows = by_path(report)
    print_paths(rows, report["summary"])
    output: Dict[str, Any] = {"created": datetime.now().isoformat(timespec="seconds"), "eval_report": Path(args.report).name,
                              "eval_summary": {k: report["summary"].get(k) for k in ("model", "agent_mode", "cases", "runs")},
                              "paths": rows}
    if args.concurrency:
        from app.services.answer_jobs import close_redis
        from app.workers.async_runner import _release_loop_resources

        try:
            output["concurrency"] = await concurrency(min(args.concurrency, len(QUESTIONS) - 2))
        finally:
            await close_redis()
            await _release_loop_resources(dispose_engine=True)
        print_concurrency(output["concurrency"])
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nWritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
