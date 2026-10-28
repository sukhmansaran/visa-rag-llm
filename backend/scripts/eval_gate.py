"""
Answer-quality regression gate (M0.8). Exit code 0 = PASS, 1 = FAIL.

Compares a fresh evaluation with the stored baseline (tests/data/rag_eval_baseline.json) and fails on:
  - a regression: a case that passed in the baseline now fails (majority of runs);
  - newly invented numbers: a case whose answers now contain numbers missing from its sources, where the
    baseline had none;
  - a changed rule: a value in ircc_rules.yaml that a case depends on (its rules_keys) differs from the
    baseline. Re-check those cases by hand, then refresh the baseline.
Improvements and new cases are reported but never fail the gate.

Model builds (M0.11): the quick gate fails at once if a configured model's build differs from its pin in
app/data/model_pins.yaml, since a few critical cases can't vouch for a new build. --full still runs (that is
how a new build is evaluated) and says so; after reviewing it, update the baseline and run
scripts/pin_models.py --accept.

Ollama is not perfectly repeatable even at temperature 0, so in quick mode a baseline-passing case that fails
is re-run twice more and judged by majority of 3 before it counts as a regression.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\eval_gate.py                    # quick: critical cases, 1 run (+ re-checks)
  .venv\\Scripts\\python.exe scripts\\eval_gate.py --full             # all cases, 3 runs each
  .venv\\Scripts\\python.exe scripts\\eval_gate.py --system-prompt-file broken.txt   # gate a prompt variant
  .venv\\Scripts\\python.exe scripts\\eval_gate.py --update-baseline logs\\eval_full.json   # after a reviewed full run
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import yaml  # noqa: E402

import eval_rag  # noqa: E402

BASELINE = BACKEND / "tests" / "data" / "rag_eval_baseline.json"
RULES_FILE = BACKEND / "app" / "data" / "ircc_rules.yaml"


def rule_values(keys: List[str]) -> Dict[str, Any]:
    rules = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    values = {}
    for key in keys:
        node: Any = rules
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        values[key] = json.loads(json.dumps(node, default=str))
    return values


def _ungrounded_majority(result: dict) -> bool:
    runs = result["run_results"]
    return sum(bool(r["ungrounded_numbers"]) for r in runs) * 2 > len(runs)


async def _versions(model: str) -> Dict[str, Any]:
    from app.services.llm import llm_service
    from app.services.rule_engine import get_rules_content_hash
    from app.services.tracing import _prompt_version

    digest = await llm_service.model_digest(model)
    await llm_service.close()
    return {"model": model, "model_digest": digest, "prompt_version": _prompt_version(),
            "rules_version": get_rules_content_hash()}


def pin_gate_problem(pin_report, full: bool) -> str:
    """Why the gate can't judge these model builds ('' if it can). Quick runs need pinned builds."""
    if pin_report.ok:
        return ""
    problems = "; ".join(pin_report.problems())
    if full:
        return f"note: model builds differ from their pins ({problems}). This full run evaluates the new builds."
    return (f"FAIL: model builds differ from their pins ({problems}). The quick gate can't judge a new build: run "
            "--full, review it, refresh the baseline, then scripts/pin_models.py --accept.")


def build_baseline(report: dict, versions: dict) -> dict:
    results = report["results"]
    if report["summary"]["runs"] < 3:
        raise SystemExit("A baseline needs a run with --runs 3 or more (Ollama varies between runs).")
    cases = json.loads(eval_rag.EVAL_SET.read_text(encoding="utf-8"))["cases"]
    if len(results) != len(cases):
        raise SystemExit(f"A baseline needs the full set ({len(cases)} cases); this report has {len(results)}.")
    return {
        "created": date.today().isoformat(), **versions,
        # the gate replays this mode: a verified-path baseline compared with fast-path runs would be meaningless
        "agent_mode": report["summary"].get("agent_mode", "shadow"),
        "eval_set_version": report["summary"].get("eval_set_version"), "runs": report["summary"]["runs"],
        "summary": report["summary"],
        "cases": {r["id"]: {"type": r["type"], "critical": r["critical"], "passed": r["passed"], "passes": r["passes"],
                            "runs": r["runs"], "ungrounded": _ungrounded_majority(r),
                            "rules_values": rule_values(r.get("rules_keys", []))} for r in results},
    }


def accept_cases(baseline: dict, report: dict, versions: dict, today: str) -> List[str]:
    """
    Record fixed cases as passing in the baseline without a full re-run. Only cases that passed by majority in a
    report with 3+ runs are accepted; each acceptance is logged in baseline["history"]. Returns the accepted ids.
    """
    if report["summary"]["runs"] < 3:
        raise SystemExit("Accepting cases needs a report with --runs 3 or more.")
    accepted = []
    for r in report["results"]:
        if r["id"] not in baseline["cases"]:
            raise SystemExit(f"{r['id']} is not in the baseline; refresh the full baseline to add new cases.")
        if not r["passed"]:
            raise SystemExit(f"{r['id']} did not pass by majority ({r['passes']}/{r['runs']}); not accepted.")
        baseline["cases"][r["id"]].update(passed=True, passes=r["passes"], runs=r["runs"],
                                          ungrounded=_ungrounded_majority(r),
                                          rules_values=rule_values(r.get("rules_keys", [])))
        accepted.append(r["id"])
    baseline["summary"]["passed"] = sum(c["passed"] for c in baseline["cases"].values())
    baseline.setdefault("history", []).append({"date": today, "accepted": accepted, **versions})
    for key in ("model_digest", "prompt_version", "rules_version"):
        baseline[key] = versions[key]
    return accepted


def compare(baseline: dict, results: List[dict]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"regressions": [], "new_ungrounded": [], "rule_changes": [], "improvements": [],
                                 "new_cases": [], "unstable": []}
    for r in results:
        base = baseline["cases"].get(r["id"])
        if base is None:
            out["new_cases"].append(r["id"])
            continue
        changed = [k for k, v in rule_values(r.get("rules_keys", [])).items() if base["rules_values"].get(k) != v]
        if changed:
            out["rule_changes"].append(f"{r['id']} ({', '.join(changed)})")
        if base["passed"] and not r["passed"]:
            out["regressions"].append(f"{r['id']} ({r['passes']}/{r['runs']} passed)")
        elif not base["passed"] and r["passed"]:
            out["improvements"].append(r["id"])
        if not base["ungrounded"] and _ungrounded_majority(r):
            numbers = sorted({n for run in r["run_results"] for n in run["ungrounded_numbers"]})
            out["new_ungrounded"].append(f"{r['id']} {numbers}")
        if not r["stable"]:
            out["unstable"].append(r["id"])
    return out


async def run_gate(args) -> int:
    if args.accept:
        if not BASELINE.exists():
            print("FAIL: no baseline to update.")
            return 1
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        report = json.loads(Path(args.accept).read_text(encoding="utf-8"))
        accepted = accept_cases(baseline, report, await _versions(baseline["model"]), date.today().isoformat())
        BASELINE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Accepted as passing: {', '.join(accepted)} -> baseline now {baseline['summary']['passed']}/{len(baseline['cases'])}")
        return 0

    if args.update_baseline:
        report = json.loads(Path(args.update_baseline).read_text(encoding="utf-8"))
        baseline = build_baseline(report, await _versions(report["summary"]["model"]))
        if BASELINE.exists():  # relabels and acceptances stay on record
            baseline["history"] = json.loads(BASELINE.read_text(encoding="utf-8")).get("history", [])
        baseline.setdefault("history", []).append({"date": baseline["created"], "baseline": "rebuilt",
                                                   "agent_mode": baseline["agent_mode"],
                                                   "passed": baseline["summary"]["passed"]})
        BASELINE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        s = baseline["summary"]
        print(f"Baseline written: {s['passed']}/{s['cases']} cases pass ({s['runs']} runs) -> {BASELINE}")
        return 0

    if not BASELINE.exists():
        print("FAIL: no baseline yet. Run a full evaluation (--runs 3) and --update-baseline it.")
        return 1
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    from app.services.model_pins import check_pins
    pins = await check_pins()
    pin_problem = pin_gate_problem(pins, args.full)
    if pin_problem:
        print(pin_problem)
        if not args.full:
            return 1

    argv = ["--models", baseline["model"], "--out", str(BACKEND / "logs" / "eval_gate_last.json"),
            "--agent-mode", baseline.get("agent_mode", "shadow")]
    argv += ["--runs", "3"] if args.full else ["--critical", "--runs", "1"]
    if args.system_prompt_file:
        argv += ["--system-prompt-file", args.system_prompt_file]
    report = (await eval_rag.main(argv))[0]
    results = report["results"]

    if not args.full:
        # Re-check baseline-passing cases that failed once: judge them by majority of 3 before calling a regression
        suspects = [r["id"] for r in results if not r["passed"] and baseline["cases"].get(r["id"], {}).get("passed")]
        if suspects:
            print(f"\nRe-checking {len(suspects)} case(s) that failed once: {', '.join(suspects)}")
            recheck_argv = ["--models", baseline["model"], "--only", ",".join(suspects), "--runs", "2",
                            "--out", str(BACKEND / "logs" / "eval_gate_recheck.json")]
            if args.system_prompt_file:
                recheck_argv += ["--system-prompt-file", args.system_prompt_file]
            rechecked = {r["id"]: r for r in (await eval_rag.main(recheck_argv))[0]["results"]}
            for r in results:
                if r["id"] in rechecked:
                    runs = r["run_results"] + rechecked[r["id"]]["run_results"]
                    passes = sum(x["passed"] for x in runs)
                    r.update(run_results=runs, runs=len(runs), passes=passes, passed=passes * 2 > len(runs),
                             stable=passes in (0, len(runs)))

    findings = compare(baseline, results)
    versions = await _versions(baseline["model"])
    failed = bool(findings["regressions"] or findings["new_ungrounded"] or findings["rule_changes"])

    print("\n" + "=" * 72)
    print(f"Eval gate ({'full' if args.full else 'quick'}): {sum(r['passed'] for r in results)}/{len(results)} cases pass "
          f"| baseline {baseline['created']}: {baseline['summary']['passed']}/{baseline['summary']['cases']}")
    for key, label in (("regressions", "REGRESSION"), ("new_ungrounded", "NEW INVENTED NUMBERS"),
                       ("rule_changes", "RULE CHANGED - re-check, then refresh the baseline"),
                       ("improvements", "improved"), ("new_cases", "new case (not gated until the baseline is refreshed)"),
                       ("unstable", "unstable across runs")):
        for item in findings[key]:
            print(f"  {label}: {item}")
    for key in ("model_digest", "prompt_version", "rules_version"):
        if versions[key] != baseline.get(key):
            print(f"  note: {key} changed since the baseline ({baseline.get(key)} -> {versions[key]})")
    if pin_problem:
        print("  note: evaluated on unpinned model builds; if this run is acceptable, refresh the baseline and run "
              "scripts/pin_models.py --accept")
    print(f"RESULT: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="all cases, 3 runs each (slow)")
    ap.add_argument("--system-prompt-file", default="")
    ap.add_argument("--update-baseline", default="", help="write the baseline from this full-run report")
    ap.add_argument("--accept", default="", help="mark the (fixed) cases in this 3+ run report as passing in the baseline")
    return asyncio.run(run_gate(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
