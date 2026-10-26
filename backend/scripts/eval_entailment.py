"""
Claim check evaluation (M4.2) on tests/data/entailment_cases.json with the real model.

    cd backend
    .venv\\Scripts\\python.exe scripts\\eval_entailment.py         # writes logs/eval_entailment.json

Two layers (see app/services/claims.py): the code check blocks, the model check only marks a part "partially
verified". Reported: unsupported claims blocked by code / flagged by the model / either; correct claims blocked by
code (must be 0) and flagged by the model; unreadable model outputs; time per claim.
Re-scoped done-criterion (owner decision 2026-10-26): no correct claim blocked, and >= 90% of unsupported claims
blocked or flagged. Exit code 0 when both hold.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.services.claims import UNCHECKED, YES, check_claim, code_check  # noqa: E402
from app.services.llm import llm_service  # noqa: E402

CASES = BACKEND / "tests" / "data" / "entailment_cases.json"


async def main() -> int:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    rows = []
    for case in data["claims"]:
        passage = data["passages"][case["passage"]]
        started = time.perf_counter()
        blocked = code_check(case["claim"], passage, case.get("question", ""))
        verdict = await check_claim(case["claim"], passage)
        flagged = verdict.supported != YES
        rows.append({**case, "blocked": blocked, "verdict": verdict.supported, "reason": verdict.reason,
                     "seconds": round(time.perf_counter() - started, 1)})
        wrong = (case["supported"] and blocked) or (not case["supported"] and not blocked and not flagged)
        print(f"{'WRONG' if wrong else 'ok   '} code={'block' if blocked else 'pass '} model={verdict.supported:<9} "
              f"{'good' if case['supported'] else 'bad '} {case['claim'][:80]}", flush=True)

    bad = [r for r in rows if not r["supported"]]
    good = [r for r in rows if r["supported"]]
    summary = {
        "claims": len(rows),
        "unsupported_blocked_by_code": f"{sum(bool(r['blocked']) for r in bad)}/{len(bad)}",
        "unsupported_flagged_by_model": f"{sum(r['verdict'] != YES for r in bad)}/{len(bad)}",
        "unsupported_blocked_or_flagged": f"{sum(bool(r['blocked']) or r['verdict'] != YES for r in bad)}/{len(bad)}",
        "correct_blocked_by_code": f"{sum(bool(r['blocked']) for r in good)}/{len(good)}",
        "correct_flagged_by_model": f"{sum(r['verdict'] != YES for r in good)}/{len(good)}",
        "unreadable": sum(r["verdict"] == UNCHECKED for r in rows),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1),
    }
    out = BACKEND / "logs" / "eval_entailment.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("SUMMARY", json.dumps(summary))
    covered = sum(bool(r["blocked"]) or r["verdict"] != YES for r in bad) / len(bad)
    ok = not any(r["blocked"] for r in good) and covered >= 0.9
    print("RESULT:", "PASS" if ok else "FAIL")
    await llm_service.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
