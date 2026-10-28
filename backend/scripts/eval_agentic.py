"""
Agentic evaluation (M5.3) against the live stack (Postgres, Chroma, Ollama): tests/data/agentic_cases.json through the
real pipeline with the agent loop on (verified path, verified-answer cache off). The 'profile' tool returns each case's
profile (nothing is read from or written to the database for it). When the agent asks a question, the case's scripted
reply is sent as the next turn and that answer is scored.

Per case:
  success    the ask decision is right and every must_include group matches, no must_not does
  ask        asked exactly when expect_ask (and the reply then led to a passing answer)
  tools      every expect_tools tool was used (the pipeline's own first search and rule facts count)
  steps / invalid / fallback   the agent's decisions, choices code refused, the router taking over
Targets (set when the cases were written): success >= 12/16, ask decision right >= 14/16.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\eval_agentic.py                       # dev + holdout, the configured agent model
  .venv\\Scripts\\python.exe scripts\\eval_agentic.py --split dev --agent-model qwen3:4b
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

CASES = BACKEND / "tests" / "data" / "agentic_cases.json"
FLAGS = re.IGNORECASE | re.DOTALL


def score_answer(case: Dict[str, Any], answer: str) -> Dict[str, Any]:
    missing = [group for group in case.get("must_include", []) if not any(re.search(p, answer, FLAGS) for p in group)]
    forbidden = [p for p in case.get("must_not", []) if re.search(p, answer, FLAGS)]
    return {"missing": missing, "forbidden": forbidden, "answer_ok": not missing and not forbidden}


def tools_used(trace) -> set:
    used = {"knowledge_base_search"}  # the pipeline always searches first
    for step in trace.steps:
        if step["name"] == "rules" and step.get("rule_facts"):
            used.add("rules")
        if step["name"] == "agent_step" and step.get("valid") and step.get("action") in (
                "rules", "knowledge_base_search", "profile", "processing_times_link"):
            used.add(step["action"])
    return used


async def run_turn(question: str, chat_history: Optional[List[Dict[str, str]]]):
    from app.services import rag_pipeline as rp
    from app.services.tracing import TraceRecorder, activate_trace
    from app.services.triage import routed_as

    trace = TraceRecorder("eval.agentic", query=question)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(question, chat_history=chat_history)
    return result, trace


async def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import tools

    async def stub_profile(_args):
        return tools.ProfileResult(**(case.get("profile") or {"found": False}))

    real = tools.TOOLS["profile"]
    tools.TOOLS["profile"] = tools.Tool(real.name, real.description, real.args_model, real.result_model, stub_profile)
    started = time.perf_counter()
    try:
        result, trace = await run_turn(case["question"], None)
        asked = result["metrics"].get("source") == "agent_ask"
        used = tools_used(trace)
        turns = [{"answer": result["answer"], "agent": result["metrics"].get("agent")}]
        final = result
        if asked and case.get("user_reply"):
            history = [{"role": "user", "content": case["question"]}, {"role": "assistant", "content": result["answer"]}]
            final, trace2 = await run_turn(case["user_reply"], history)
            used |= tools_used(trace2)
            turns.append({"answer": final["answer"], "agent": final["metrics"].get("agent"),
                          "blocked": final.get("guardrail_blocked", False)})
    finally:
        tools.TOOLS["profile"] = real
    scored = score_answer(case, final["answer"])
    ask_ok = asked == case["expect_ask"]
    tools_ok = set(case.get("expect_tools", [])) <= used
    agents = [t["agent"] for t in turns if t.get("agent")]
    return {
        "id": case["id"], "question": case["question"], "expect_ask": case["expect_ask"], "asked": asked,
        "ask_ok": ask_ok, "tools_ok": tools_ok, "tools_used": sorted(used), **scored,
        "success": ask_ok and scored["answer_ok"],
        "steps": sum(a["steps"] for a in agents), "invalid": sum(a["invalid"] for a in agents),
        "fallback": any(a["outcome"] == "fallback" for a in agents), "outcomes": [a["outcome"] for a in agents],
        "turns": turns, "seconds": round(time.perf_counter() - started, 1)}


async def main(argv=None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--agent-model", default="", help="LLM_MODEL_AGENT for this run")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    from app.core.config import settings

    settings.AGENT_MODE = "on"
    settings.AGENT_LOOP = True
    settings.VERIFIED_CACHE_ENABLED = False  # every case answered, never from an earlier run
    if args.agent_model:
        settings.LLM_MODEL_AGENT = args.agent_model
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = [c for split in (("dev", "holdout") if args.split == "all" else (args.split,)) for c in data[split]]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    results = []
    for case in cases:
        r = await run_case(case)
        results.append(r)
        print(f"{'PASS' if r['success'] else 'FAIL'} {r['id']:<34} ask {r['asked']!s:<5}(want {r['expect_ask']!s:<5}) "
              f"tools {'ok' if r['tools_ok'] else 'MISSING'} steps {r['steps']} invalid {r['invalid']} "
              f"{'fallback ' if r['fallback'] else ''}{r['seconds']}s")
        if not r["answer_ok"]:
            print(f"     missing {r['missing']} forbidden {r['forbidden']}: {r['turns'][-1]['answer'][:200]!r}")

    n = len(results)
    summary = {
        "agent_model": settings.LLM_MODEL_AGENT or settings.OLLAMA_MODEL, "split": args.split, "cases": n,
        "success": sum(r["success"] for r in results), "ask_ok": sum(r["ask_ok"] for r in results),
        "tools_ok": sum(r["tools_ok"] for r in results), "fallbacks": sum(r["fallback"] for r in results),
        "avg_steps": round(sum(r["steps"] for r in results) / n, 2) if n else None,
        "invalid_rate": round(sum(r["invalid"] for r in results) / max(1, sum(r["steps"] for r in results)), 3),
        "avg_seconds": round(sum(r["seconds"] for r in results) / n, 1) if n else None,
    }
    print(json.dumps(summary, indent=2))
    out = Path(args.out) if args.out else BACKEND / "logs" / (
        f"eval_agentic_{summary['agent_model'].replace(':', '-')}_{datetime.now():%Y%m%d_%H%M%S}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    from app.services.llm import llm_service
    await llm_service.close()
    return {"summary": summary, "results": results}


if __name__ == "__main__":
    asyncio.run(main())
