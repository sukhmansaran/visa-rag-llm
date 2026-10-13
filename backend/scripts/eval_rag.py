"""
RAG answer-quality evaluation against the live stack (Postgres, Chroma, Ollama).

For each model it runs every case in tests/data/rag_eval_set.json through the real
rag_pipeline.process_query and scores:
  - facts:      every must_include group matched
  - forbidden:  no must_not pattern matched
  - gap:        for unanswerable cases, the answer says the sources don't cover it (or refuses)
  - ungrounded: numbers in the answer (2+ digits) that do not appear in the context the model saw
  - latency:    seconds per answer (model warm)

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b,phi4-mini
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --baseline      # old prompt + budgets
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models qwen3:4b --limit 5
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --stream        # streaming path
Results are written to logs/eval_<model>_<mode>_<timestamp>.json
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.services import rag_pipeline as rag_module  # noqa: E402
from app.services.cache_service import intent_cache  # noqa: E402
from app.services.llm import llm_service  # noqa: E402

EVAL_SET = BACKEND / "tests" / "data" / "rag_eval_set.json"
GAP_PATTERNS = [
    r"don.?t cover", r"do not cover", r"not (covered|mentioned|specified|provided|included|stated)",
    r"cannot find", r"can.?t find", r"couldn.?t find", r"no (official )?information",
    r"(check|visit|consult) (the )?(official )?(canada\.ca|ircc|website|processing times)",
    r"verified official sources", r"\bRCIC\b",
    r"no such", r"does not (mention|exist|appear)", r"doesn.?t (exist|mention|appear)",
    r"not (a|an) (real|recogni[sz]ed|official|existing)",
]
PLACEHOLDER_CITATION = re.compile(r"\[Source N\]", re.IGNORECASE)
NUMBER_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")


def _baseline_prompt() -> str:
    """The pre-#5 system prompt, read from git so the comparison is exact."""
    src = subprocess.run(
        ["git", "show", "5e3106d:backend/app/services/rag_pipeline.py"],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    start = src.index('GROUNDED_SYSTEM_PROMPT = """') + len('GROUNDED_SYSTEM_PROMPT = """')
    return src[start:src.index('"""', start)]


def _numbers(text: str) -> set:
    out = set()
    for raw in NUMBER_RE.findall(text or ""):
        digits = raw.replace("$", "").replace(",", "").rstrip(".")
        if len(digits.replace(".", "")) >= 2:  # skip list numbering / single digits
            out.add(digits)
    return out


def score(case: dict, answer: str, context: str, llm_called: bool) -> dict:
    flags = re.IGNORECASE | re.DOTALL
    missing = [group for group in case.get("must_include", []) if not any(re.search(p, answer, flags) for p in group)]
    forbidden = [p for p in case.get("must_not", []) if re.search(p, answer, flags)]
    gap_ok = None
    if case.get("expect_gap_acknowledged"):
        gap_ok = (not llm_called) or any(re.search(p, answer, flags) for p in GAP_PATTERNS)
    ungrounded = sorted(_numbers(answer) - _numbers(context) - _numbers(case["question"])) if llm_called else []
    placeholder = bool(PLACEHOLDER_CITATION.search(answer or ""))
    passed = not missing and not forbidden and gap_ok is not False
    return {"passed": passed, "missing": missing, "forbidden": forbidden, "gap_ok": gap_ok,
            "ungrounded_numbers": ungrounded, "placeholder_citation": placeholder}


async def _ask_streaming(question: str) -> dict:
    """Run the streaming pipeline and fold its events into process_query's result shape."""
    done = {}
    async for event in rag_module.rag_pipeline.process_query_stream(query=question, context_metadata={"country": "Canada"}):
        if event.get("type") == "done":
            done = event
    return {"answer": done.get("full_response", ""), "sources": done.get("sources", []), "metrics": done.get("metrics", {})}


async def run_model(model: str, cases: list, baseline: bool, stream: bool = False) -> dict:
    llm_service.model = model
    if baseline:
        rag_module.GROUNDED_SYSTEM_PROMPT = _baseline_prompt()
        settings.RAG_TOP_K, settings.RAG_CONTEXT_CHARS, settings.RAG_MAX_ANSWER_TOKENS = 3, 1500, 700

    captured = {}
    original = llm_service.generate_answer
    original_stream = llm_service.generate_answer_stream

    async def capture(*args, **kwargs):
        captured["context"] = kwargs.get("context", "")
        return await original(*args, **kwargs)

    def capture_stream(*args, **kwargs):
        captured["context"] = kwargs.get("context", "")
        return original_stream(*args, **kwargs)

    llm_service.generate_answer = capture
    llm_service.generate_answer_stream = capture_stream

    # Warm-up so model loading time isn't counted against the first question
    await original(system_prompt="Reply with OK.", user_prompt="OK", temperature=0.0, max_tokens=3)

    results = []
    for case in cases:
        intent_cache.clear()
        captured.clear()
        t0 = time.perf_counter()
        if stream:
            r = await _ask_streaming(case["question"])
        else:
            r = await rag_module.rag_pipeline.process_query(query=case["question"], context_metadata={"country": "Canada"})
        latency = time.perf_counter() - t0
        metrics = r["metrics"]
        s = score(case, r["answer"], captured.get("context", ""), metrics.get("llm_called", False))
        results.append({
            "id": case["id"], "latency_s": round(latency, 1), "source": metrics.get("source"),
            "llm_called": metrics.get("llm_called"), "citations": [c.get("url") for c in r.get("sources", [])],
            "answer": r["answer"], **s,
        })
        status = "PASS" if s["passed"] else "FAIL"
        extra = []
        if s["missing"]: extra.append(f"missing={s['missing']}")
        if s["forbidden"]: extra.append(f"forbidden={s['forbidden']}")
        if s["gap_ok"] is False: extra.append("gap-not-acknowledged")
        if s["ungrounded_numbers"]: extra.append(f"ungrounded={s['ungrounded_numbers']}")
        if s["placeholder_citation"]: extra.append("literal-[Source N]")
        print(f"  {status} {latency:6.1f}s  {case['id']:<30} {' '.join(extra)}", flush=True)

    llm_service.generate_answer = original
    llm_service.generate_answer_stream = original_stream
    n = len(results)
    summary = {
        "model": model, "mode": _mode_name(baseline, stream), "cases": n,
        "passed": sum(r["passed"] for r in results),
        "facts_ok": sum(not r["missing"] for r in results),
        "forbidden_hits": sum(bool(r["forbidden"]) for r in results),
        "answers_with_ungrounded_numbers": sum(bool(r["ungrounded_numbers"]) for r in results),
        "placeholder_citations": sum(r["placeholder_citation"] for r in results),
        "avg_latency_s": round(sum(r["latency_s"] for r in results if r["llm_called"]) / max(1, sum(r["llm_called"] for r in results)), 1),
    }
    return {"summary": summary, "results": results}


def _mode_name(baseline: bool, stream: bool) -> str:
    return ("baseline" if baseline else "current") + ("_stream" if stream else "")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--baseline", action="store_true", help="old prompt + old context/answer budgets")
    ap.add_argument("--stream", action="store_true", help="evaluate the streaming path (process_query_stream)")
    args = ap.parse_args()

    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]

    out_dir = BACKEND / "logs"
    out_dir.mkdir(exist_ok=True)
    for model in args.models.split(","):
        mode = _mode_name(args.baseline, args.stream)
        print(f"\n=== {model} ({mode}) - {len(cases)} cases ===", flush=True)
        report = await run_model(model.strip(), cases, args.baseline, args.stream)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"eval_{model.replace(':', '-')}_{mode}_{stamp}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("SUMMARY", json.dumps(report["summary"]), flush=True)
        print(f"saved {path}", flush=True)
    await llm_service.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
