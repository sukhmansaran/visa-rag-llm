"""
RAG answer-quality evaluation (v2, M0.8) against the live stack (Postgres, Chroma, Ollama).

Runs every case in tests/data/rag_eval_set.json through the real pipeline and scores:
  - facts / coverage: each must_include part matched (coverage = parts matched / parts; multi_part cases
                      report it as decomposition coverage until the M1 planner exists)
  - forbidden:        no must_not pattern matched
  - gap:              unanswerable cases say the sources don't cover it (or the pipeline refused)
  - blocked:          cases marked expect_blocked were stopped by the input guardrail
  - tool choice:      cases with expect_rules used (or didn't use) the rule engine, read from the request trace
  - ungrounded:       numbers in the answer (2+ digits) that are not in the context the model saw
  - latency:          per case and per answer path (llm_rag, cache, refusals)
Ollama is not perfectly repeatable even at temperature 0, so --runs N runs each case N times; a case passes
by majority and cases whose outcome varies are reported as unstable.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b                 # all cases, 1 run
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --runs 3        # majority of 3
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --critical      # quick gate subset
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --types distractor,sensitive
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --stream        # streaming path
  .venv\\Scripts\\python.exe scripts\\eval_rag.py --models llama3.2:3b --baseline      # old prompt + budgets
Results are written to logs/eval_<model>_<mode>_<timestamp>.json (or --out).
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.services import prompt_registry  # noqa: E402
from app.services import rag_pipeline as rag_module  # noqa: E402
from app.services.cache_service import intent_cache  # noqa: E402
from app.services.llm import llm_service  # noqa: E402
from app.services.tracing import TraceRecorder, activate_trace  # noqa: E402
from app.services.triage import FAST, VERIFIED, routed_as, triage  # noqa: E402

EVAL_SET = BACKEND / "tests" / "data" / "rag_eval_set.json"
GAP_PATTERNS = [
    r"don.?t cover", r"do not cover", r"not (covered|mentioned|specified|provided|included|stated)",
    r"cannot find", r"can.?t find", r"couldn.?t find", r"no (official )?information",
    r"(check|visit|consult) (the )?(official )?(canada\.ca|ircc|website|processing times)",
    r"verified official sources", r"\bRCIC\b",
    r"no such", r"does not (mention|exist|appear)", r"doesn.?t (exist|mention|appear)",
    r"not (a|an) (real|recogni[sz]ed|official|existing)",
    r"do(es)? not (explicitly )?(state|say|address|specify)", r"doesn.?t (explicitly )?(state|say|address|specify)",
]
PLACEHOLDER_CITATION = re.compile(r"\[Source N\]", re.IGNORECASE)
NUMBER_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")
# A single digit with a unit is a fact ("5 years", "3-year PGWP"), not list numbering (hardening 3: an answer
# saying biometrics last "5 years" against sources saying 10 was not flagged)
UNIT_NUMBER_RE = re.compile(r"(?<![\d.,])(\d)(?:\s*-\s*|\s+)(?:years?|months?|weeks?|days?|hours?)\b", re.IGNORECASE)
MARKDOWN_RE = re.compile(r"\*\*|__|\*|`")
FLAGS = re.IGNORECASE | re.DOTALL


def _baseline_prompt() -> str:
    """The pre-#5 system prompt, read from git so the comparison is exact."""
    src = subprocess.run(
        ["git", "show", "5e3106d:backend/app/services/rag_pipeline.py"],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    start = src.index('GROUNDED_SYSTEM_PROMPT = """') + len('GROUNDED_SYSTEM_PROMPT = """')
    return src[start:src.index('"""', start)]


def _without_app_notices(answer: str) -> str:
    """
    The answer minus the fixed legal notices the app appends (e.g. "Section 40 IRPA ... 5-year ban"). The model
    didn't write them, so their numbers aren't invented (M0.14 false alarm). Removing the notice text, rather than
    ignoring its numbers everywhere, keeps "5 years" written by the model checkable (hardening 3).
    """
    from app.services.guardrails import legal_disclaimer
    for name, notice in vars(legal_disclaimer).items():
        if name.startswith("DISCLAIMER_") and isinstance(notice, str):
            answer = answer.replace(_plain(notice).strip(), "").replace(notice.strip(), "")
    return answer


def _numbers(text: str) -> set:
    out = set()
    for raw in NUMBER_RE.findall(text or ""):
        digits = raw.replace("$", "").replace(",", "").rstrip(".")
        if len(digits.replace(".", "")) >= 2:  # skip list numbering / single digits
            out.add(digits)
    out.update(UNIT_NUMBER_RE.findall(text or ""))  # ...unless they carry a unit
    return out


def _plain(text: str) -> str:
    """The answer without markdown emphasis: "**before** it expires" must match like "before it expires"."""
    return MARKDOWN_RE.sub("", text or "")


def score(case: dict, answer: str, context: str, llm_called: bool, source: Optional[str] = None,
          rules_used: Optional[bool] = None) -> dict:
    """Score one answer. Returns pass/fail plus every component, so failures are explainable."""
    answer = _plain(answer)
    groups = case.get("must_include", [])
    missing = [group for group in groups if not any(re.search(p, answer, FLAGS) for p in group)]
    coverage = 1.0 if not groups else round((len(groups) - len(missing)) / len(groups), 3)
    forbidden = [p for p in case.get("must_not", []) if re.search(p, answer, FLAGS)]

    gap_ok = None
    if case.get("expect_gap_acknowledged"):
        gap_ok = (not llm_called) or any(re.search(p, answer, FLAGS) for p in GAP_PATTERNS)
    blocked_ok = None
    if case.get("expect_blocked"):
        blocked_ok = source == "guardrail_refusal"
    rules_ok = None
    if case.get("expect_rules") is not None and rules_used is not None:
        rules_ok = rules_used == case["expect_rules"]

    history_text = " ".join(t.get("content", "") for t in case.get("history", []))
    ungrounded = sorted(_numbers(_without_app_notices(answer)) - _numbers(context) - _numbers(case["question"])
                        - _numbers(history_text)) if llm_called else []
    placeholder = bool(PLACEHOLDER_CITATION.search(answer or ""))
    passed = not missing and not forbidden and gap_ok is not False and blocked_ok is not False and rules_ok is not False
    return {"passed": passed, "coverage": coverage, "missing": missing, "forbidden": forbidden, "gap_ok": gap_ok,
            "blocked_ok": blocked_ok, "rules_used": rules_used, "rules_ok": rules_ok,
            "ungrounded_numbers": ungrounded, "placeholder_citation": placeholder}


async def _ask(case: dict, stream: bool) -> Dict[str, Any]:
    history = case.get("history")
    if not stream:
        return await rag_module.rag_pipeline.process_query(
            query=case["question"], context_metadata={"country": "Canada"}, chat_history=history)
    done: Dict[str, Any] = {}
    async for event in rag_module.rag_pipeline.process_query_stream(
            query=case["question"], context_metadata={"country": "Canada"}, chat_history=history):
        if event.get("type") == "done":
            done = event
    return {"answer": done.get("full_response", ""), "sources": done.get("sources", []), "metrics": done.get("metrics", {})}


def _route(question: str) -> str:
    """The path the API would give this question (chat_jobs._answer_path): verified only with AGENT_MODE=on."""
    if settings.AGENT_MODE != "on":
        return FAST
    from app.services.guardrails.input_guardrail import input_guardrail
    return VERIFIED if input_guardrail.evaluate(question).allowed and triage(question).verified else FAST


async def run_case(case: dict, stream: bool, captured: dict) -> dict:
    intent_cache.clear()
    captured.clear()
    trace = TraceRecorder("eval", query=case["question"])
    path = _route(case["question"])
    t0 = time.perf_counter()
    with activate_trace(trace), routed_as(path):
        r = await _ask(case, stream)
    latency = time.perf_counter() - t0
    metrics = r.get("metrics", {})
    rules_step = next((s for s in trace.steps if s["name"] == "rules"), None)
    rules_used = bool(rules_step.get("rule_facts")) if rules_step else None
    llm = trace.llm_calls[-1] if trace.llm_calls else None
    s = score(case, r["answer"], captured.get("context", ""), metrics.get("llm_called", False),
              metrics.get("source"), rules_used)
    return {
        "latency_s": round(latency, 1), "route": path, "source": metrics.get("source"), "llm_called": metrics.get("llm_called"),
        "evidence": metrics.get("evidence"),
        "citations": [c.get("url") for c in r.get("sources", [])], "answer": r["answer"], **s,
        "prompt_tokens": llm.prompt_tokens if llm else None, "output_tokens": llm.output_tokens if llm else None,
        "prompt_s": llm.prompt_s if llm else None, "generation_s": llm.generation_s if llm else None,
        "tokens_per_second": llm.tokens_per_second if llm else None,
    }


def _describe(run: dict) -> str:
    extra = []
    if run["missing"]:
        extra.append(f"missing={run['missing']}")
    if run["forbidden"]:
        extra.append(f"forbidden={run['forbidden']}")
    if run["gap_ok"] is False:
        extra.append("gap-not-acknowledged")
    if run["blocked_ok"] is False:
        extra.append(f"not-blocked(source={run['source']})")
    if run["rules_ok"] is False:
        extra.append(f"rule-engine-used={run['rules_used']}")
    if run["ungrounded_numbers"]:
        extra.append(f"ungrounded={run['ungrounded_numbers']}")
    if run["placeholder_citation"]:
        extra.append("literal-[Source N]")
    return " ".join(extra)


async def run_model(model: str, cases: list, baseline: bool, stream: bool = False, runs: int = 1,
                    system_prompt: Optional[str] = None) -> dict:
    llm_service.model = model
    if system_prompt is not None:
        prompt_registry.set_override("grounded_answer", system_prompt)  # a variant, tagged grounded_answer@0:...
    if baseline:
        prompt_registry.set_override("grounded_answer", _baseline_prompt())
        settings.RAG_TOP_K, settings.RAG_CONTEXT_CHARS, settings.RAG_MAX_ANSWER_TOKENS = 3, 1500, 700

    captured: dict = {}
    original, original_stream = llm_service.generate_answer, llm_service.generate_answer_stream
    original_structured = llm_service.structured_call

    async def capture(*args, **kwargs):
        captured["context"] = kwargs.get("context", "")
        return await original(*args, **kwargs)

    def capture_stream(*args, **kwargs):
        captured["context"] = kwargs.get("context", "")
        return original_stream(*args, **kwargs)

    async def capture_structured(*args, **kwargs):
        # verified-path evidence answers (M3) are written by structured calls: their context is the answer's context
        if kwargs.get("role") == "answer":
            captured["context"] = kwargs.get("context", "")
        return await original_structured(*args, **kwargs)

    llm_service.generate_answer, llm_service.generate_answer_stream = capture, capture_stream
    llm_service.structured_call = capture_structured
    # Warm-up so model loading time isn't counted against the first question
    await original(system_prompt="Reply with OK.", user_prompt="OK", temperature=0.0, max_tokens=3)

    results = []
    try:
        for case in cases:
            case_runs = []
            for _ in range(runs):
                case_runs.append(await run_case(case, stream, captured))
            passes = sum(r["passed"] for r in case_runs)
            verdict = passes * 2 > runs
            stable = passes in (0, runs)
            results.append({"id": case["id"], "type": case["type"], "critical": case.get("critical", False),
                            "rules_keys": case.get("rules_keys", []), "passed": verdict, "passes": passes,
                            "runs": runs, "stable": stable, "run_results": case_runs,
                            # convenience copies from the first run (kept for v1 consumers)
                            **{k: case_runs[0][k] for k in ("answer", "source", "llm_called", "latency_s", "coverage",
                                                            "missing", "forbidden", "ungrounded_numbers")}})
            first = case_runs[0]
            status = "PASS" if verdict else "FAIL"
            spread = f"{passes}/{runs}" + ("" if stable else " UNSTABLE")
            print(f"  {status} {spread:<13} {first['latency_s']:6.1f}s  {case['type']:<12} {case['id']:<30} "
                  f"{_describe(first) if not verdict else ''}", flush=True)
    finally:
        llm_service.generate_answer, llm_service.generate_answer_stream = original, original_stream
        llm_service.structured_call = original_structured
    return {"summary": summarise(model, results, baseline, stream, runs), "results": results}


def _evidence_summary(results: List[dict]) -> Optional[dict]:
    """Verified-path evidence parts (M3) over all runs: schema validity, how parts ended, 'not covered' where the
    case is unanswerable vs answerable."""
    totals = {"verified": 0, "not_covered": 0, "unverified": 0, "invalid": 0}
    partial = 0
    unanswerable_runs = unanswerable_not_covered = answerable_not_covered = 0
    for res in results:
        for run in res["run_results"]:
            counts = run.get("evidence") or {}
            for key in totals:
                totals[key] += counts.get(key, 0)
            partial += counts.get("partial", 0)
            if counts:
                if res["type"] == "unanswerable":
                    unanswerable_runs += 1
                    unanswerable_not_covered += int(counts.get("not_covered", 0) > 0)
                else:
                    answerable_not_covered += counts.get("not_covered", 0)
    parts = sum(totals.values())
    if not parts:
        return None
    return {**totals, "parts": parts, "partially_verified": partial, "schema_valid": round(1 - totals["invalid"] / parts, 3),
            "unanswerable_runs_with_not_covered": f"{unanswerable_not_covered}/{unanswerable_runs}",
            "answerable_parts_not_covered": answerable_not_covered}


def summarise(model: str, results: List[dict], baseline: bool, stream: bool, runs: int) -> dict:
    all_runs = [r for res in results for r in res["run_results"]]
    llm_runs = [r for r in all_runs if r["llm_called"]]
    by_type: Dict[str, Dict[str, int]] = defaultdict(lambda: {"cases": 0, "passed": 0})
    for res in results:
        by_type[res["type"]]["cases"] += 1
        by_type[res["type"]]["passed"] += int(res["passed"])
    tool_runs = [r for r in all_runs if r["rules_ok"] is not None]
    multi = [r["coverage"] for res in results if res["type"] == "multi_part" for r in res["run_results"]]
    latency_by_path: Dict[str, List[float]] = defaultdict(list)
    for r in all_runs:
        latency_by_path[r["source"] or "none"].append(r["latency_s"])

    def avg(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 2) if values else None

    n = len(results)
    return {
        "model": model, "mode": _mode_name(baseline, stream), "eval_set_version": 2, "cases": n, "runs": runs,
        # which prompt text produced these answers (M0.12); "@0" means an unsaved variant
        "prompts": {"grounded_answer": prompt_registry.get_prompt("grounded_answer").tag},
        "passed": sum(r["passed"] for r in results),
        "pass_rate": round(sum(r["passed"] for r in results) / n, 3) if n else None,
        "unstable_cases": [r["id"] for r in results if not r["stable"]],
        "by_type": dict(sorted(by_type.items())),
        "coverage_avg": avg(r["coverage"] for r in all_runs),
        "multi_part_coverage": avg(multi),
        "tool_choice_accuracy": round(sum(r["rules_ok"] for r in tool_runs) / len(tool_runs), 3) if tool_runs else None,
        "evidence": _evidence_summary(results),
        "forbidden_hits": sum(bool(r["forbidden"]) for r in all_runs),
        "answers_with_ungrounded_numbers": sum(bool(r["ungrounded_numbers"]) for r in all_runs),
        "unsupported_number_rate": round(sum(bool(r["ungrounded_numbers"]) for r in llm_runs) / len(llm_runs), 3) if llm_runs else None,
        "placeholder_citations": sum(r["placeholder_citation"] for r in all_runs),
        "evidence_quote_validity": "not applicable until the verifier (M2/M4)",
        "latency_by_path": {k: avg(v) for k, v in sorted(latency_by_path.items())},
        "avg_latency_s": avg(r["latency_s"] for r in llm_runs),
        "avg_prompt_tokens": avg(r["prompt_tokens"] for r in all_runs),
        "avg_tokens_per_second": avg(r["tokens_per_second"] for r in all_runs),
    }


def _mode_name(baseline: bool, stream: bool) -> str:
    return (("baseline" if baseline else "current") + ("_stream" if stream else "")
            + ("_agent" if settings.AGENT_MODE == "on" else ""))


def select_cases(args) -> list:
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.critical:
        cases = [c for c in cases if c.get("critical")]
    if args.types:
        wanted = set(args.types.split(","))
        cases = [c for c in cases if c["type"] in wanted]
    if args.limit:
        cases = cases[: args.limit]
    return cases


async def main(argv=None) -> List[dict]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=settings.OLLAMA_MODEL)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--critical", action="store_true", help="only cases marked critical (the quick gate)")
    ap.add_argument("--types", default="", help="comma-separated case types")
    ap.add_argument("--runs", type=int, default=1, help="run each case N times; pass by majority")
    ap.add_argument("--baseline", action="store_true", help="old prompt + old context/answer budgets")
    ap.add_argument("--stream", action="store_true", help="evaluate the streaming path (process_query_stream)")
    ap.add_argument("--out", default="", help="write the report here instead of logs/")
    ap.add_argument("--system-prompt-file", default="", help="evaluate this system prompt instead of the pipeline's")
    ap.add_argument("--agent-mode", choices=["off", "shadow", "on"], default=None,
                    help="AGENT_MODE for this run; 'on' routes each case as the API would (verified path, M2.3)")
    args = ap.parse_args(argv)
    if args.agent_mode:
        settings.AGENT_MODE = args.agent_mode
    # Every case must be answered, not served from an earlier run's verified-answer cache (M4.6)
    settings.VERIFIED_CACHE_ENABLED = False
    system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8") if args.system_prompt_file else None

    cases = select_cases(args)
    reports = []
    for model in args.models.split(","):
        mode = _mode_name(args.baseline, args.stream)
        print(f"\n=== {model} ({mode}) - {len(cases)} cases x {args.runs} run(s) ===", flush=True)
        report = await run_model(model.strip(), cases, args.baseline, args.stream, args.runs, system_prompt)
        if args.out:
            path = Path(args.out)
        else:
            (BACKEND / "logs").mkdir(exist_ok=True)
            path = BACKEND / "logs" / f"eval_{model.replace(':', '-')}_{mode}_{datetime.now():%Y%m%d_%H%M%S}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("SUMMARY", json.dumps(report["summary"]), flush=True)
        print(f"saved {path}", flush=True)
        reports.append(report)
    await llm_service.close()
    await engine.dispose()
    return reports


if __name__ == "__main__":
    asyncio.run(main())
