"""
Decomposition evaluation (M2.2) on tests/data/decomposition_cases.json with the real model.

    cd backend
    .venv\\Scripts\\python.exe scripts\\eval_decomposition.py            # writes logs/eval_decomposition.json

A part counts as covered when some final sub-question is about all of the part's topics and keeps its facts.
Reports coverage of the final split (the done-criterion: >= 95%) and of the model's own proposals; acronym
expansions the model invented (counted in its proposals, which the validators must stop) and in the final
sub-questions (must be 0); which path each case took; time per case.
Exit code 0 when coverage >= 95% and no invented expansion reached the final split.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services.decomposition import acronym_problems, decompose  # noqa: E402
from app.services.topics import detect_topics  # noqa: E402

CASES = BACKEND / "tests" / "data" / "decomposition_cases.json"


def covered(part: dict, subs) -> bool:
    for sub in subs:
        topics = set(detect_topics(sub).topics)
        if set(part["topics"]) <= topics and all(f in sub.lower() for f in part["facts"]):
            return True
    return False


async def main() -> int:
    path = Path(sys.argv[sys.argv.index("--cases") + 1]) if "--cases" in sys.argv else CASES
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    rows, parts_total, parts_final, parts_model, invented, added, final_invented = [], 0, 0, 0, 0, 0, 0
    for case in cases:
        started = time.perf_counter()
        result = await decompose(case["question"])
        seconds = round(time.perf_counter() - started, 1)
        final_hits = sum(covered(p, result.sub_questions) for p in case["parts"])
        model_hits = sum(covered(p, result.proposed) for p in case["parts"]) if result.proposed else None
        acronym_issues = acronym_problems(case["question"], list(result.proposed))
        n_invented = sum("expands" in a for a in acronym_issues)
        n_added = sum("adds" in a for a in acronym_issues)
        parts_total += len(case["parts"])
        parts_final += final_hits
        parts_model += model_hits if model_hits is not None else final_hits  # no model call: the question itself
        invented += n_invented
        added += n_added
        final_invented += sum("expands" in a for a in acronym_problems(case["question"], list(result.sub_questions)))
        rows.append({"id": case["id"], "method": result.method, "seconds": seconds,
                     "covered": f"{final_hits}/{len(case['parts'])}", "model_covered": model_hits,
                     "sub_questions": list(result.sub_questions), "proposed": list(result.proposed),
                     "problems": list(result.problems), "invented_expansions": n_invented})
        print(f"{result.method:<8} {final_hits}/{len(case['parts'])} {seconds:>5}s  {case['id']:<24} "
              f"{'; '.join(result.problems)[:110]}", flush=True)
        for sub in result.sub_questions:
            print(f"           - {sub}")

    summary = {
        "cases": len(cases), "coverage": round(parts_final / parts_total, 3),
        "model_coverage": round(parts_model / parts_total, 3), "invented_expansions_proposed": invented,
        "added_acronyms_proposed": added, "invented_expansions_final": final_invented,
        "methods": {m: sum(r["method"] == m for r in rows) for m in ("single", "model", "fallback")},
        "avg_seconds_with_model": round(sum(r["seconds"] for r in rows if r["method"] != "single")
                                        / max(1, sum(r["method"] != "single" for r in rows)), 1),
    }
    out = BACKEND / "logs" / ("eval_decomposition.json" if path == CASES else f"eval_decomposition_{path.stem}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("SUMMARY", json.dumps(summary))
    ok = summary["coverage"] >= 0.95 and final_invented == 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
