"""
Structured-output probe for the LLM gateway (M0.4 definition of done: >= 99% valid per role).

Runs N structured_call()s per role against the live Ollama model and reports:
  - valid on the first attempt, valid after the one corrective retry, failed;
  - for the verifier role, judgment accuracy against known labels (does the model see support correctly?);
  - Ollama's accounting: prompt / output tokens and generation speed.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\probe_structured.py                 # 50 calls per role
  .venv\\Scripts\\python.exe scripts\\probe_structured.py --n 10 --roles verifier --model phi4-mini
Results are written to logs/probe_structured_<model>_<timestamp>.json
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from pydantic import BaseModel, Field  # noqa: E402

from app.core.exceptions import LLMStructuredOutputError  # noqa: E402
from app.services.llm import llm_service, record_llm_calls  # noqa: E402

EVAL_SET = BACKEND / "tests" / "data" / "rag_eval_set.json"

Topic = Literal["study_permit", "work", "proof_of_funds", "pal", "pgwp", "language", "biometrics",
                "processing_times", "visitor", "express_entry", "family", "other"]


class PlannerOut(BaseModel):
    sub_questions: List[str] = Field(min_length=1, max_length=4)
    topics: List[Topic] = Field(min_length=1, max_length=4)
    needs_calculation: bool


class AnswerOut(BaseModel):
    answer: str = Field(min_length=1, max_length=1200)
    cited_sources: List[int] = Field(max_length=4)
    sources_cover_question: bool


class VerifierOut(BaseModel):
    supported: bool
    evidence_quote: str = Field(max_length=400)


PLANNER_SYSTEM = (
    "You analyse Canadian immigration questions before they are answered. Split the question into 1 to 4 "
    "short, self-contained sub-questions, choose the topics it touches, and say whether it needs a numeric "
    "calculation (for example proof of funds for a family size). Reply only with JSON."
)
ANSWER_SYSTEM = (
    "Answer the question using only the numbered sources. Put the numbers of the sources you used in "
    "cited_sources. If the sources do not answer the question, say so in the answer and set "
    "sources_cover_question to false. Reply only with JSON."
)
VERIFIER_SYSTEM = (
    "Decide whether the SOURCE states the CLAIM. supported is true only if the source says it; otherwise false. "
    "evidence_quote must be an exact sentence copied from the source that decides it, or an empty string "
    "if nothing in the source is relevant. Reply only with JSON."
)

SOURCES = [
    "Full-time students may work off campus up to 24 hours per week while classes are in session. "
    "During scheduled breaks, such as the winter holidays or summer break, they may work full-time.",
    "From September 1, 2026, a single applicant must show 23,448 CAD for living expenses, in addition to "
    "the first year of tuition and travel costs.",
    "Most applicants need to give biometrics. Children under 14 and applicants over 79 do not need to give "
    "biometrics for a temporary residence application.",
    "Biometrics are valid for 10 years. You do not need to give them again if they are still valid.",
    "Master's and doctoral students at a public designated learning institution do not need a provincial "
    "or territorial attestation letter (PAL) for applications received on or after January 1, 2026.",
]

# (claim, source index, label): half supported, half not (wrong number, wrong condition, unrelated)
VERIFIER_CASES = [
    ("Students can work 24 hours per week off campus during classes.", 0, True),
    ("Students can work full-time during scheduled breaks.", 0, True),
    ("Students can work 40 hours per week off campus during classes.", 0, False),
    ("Students cannot work at all during the summer break.", 0, False),
    ("A single applicant needs 23,448 CAD for living expenses from September 1, 2026.", 1, True),
    ("A single applicant needs 20,635 CAD for living expenses from September 1, 2026.", 1, False),
    ("Tuition is included in the 23,448 CAD amount.", 1, False),
    ("Children under 14 do not need to give biometrics.", 2, True),
    ("Applicants over 79 must always give biometrics.", 2, False),
    ("Biometrics stay valid for 10 years.", 3, True),
    ("Biometrics must be given again every year.", 3, False),
    ("Master's students at a public DLI do not need a PAL from January 1, 2026.", 4, True),
    ("All college diploma students are exempt from the PAL.", 4, False),
    ("Students can work 24 hours per week off campus.", 2, False),  # unrelated source
]


def planner_inputs(n: int) -> List[dict]:
    questions = [c["question"] for c in json.loads(EVAL_SET.read_text(encoding="utf-8"))["cases"]]
    questions += [
        "I'm a master's student with my wife and two kids, how much money do we need and can she work?",
        "Can I work off campus while studying and do I need a PAL?",
        "How long does a visitor visa take from India and do I need biometrics?",
    ]
    return [{"system": PLANNER_SYSTEM, "user": f"Question: {questions[i % len(questions)]}", "context": ""}
            for i in range(n)]


def answer_inputs(n: int) -> List[dict]:
    questions = [
        "How many hours can I work off campus during classes?", "How much money does a single applicant need?",
        "Does my 10-year-old need biometrics?", "Do master's students need a PAL in 2026?",
        "How long are biometrics valid?", "How much does a work permit cost?",  # not covered by the sources
    ]
    context = "\n\n".join(f"[Source {i + 1}] {s}" for i, s in enumerate(SOURCES))
    return [{"system": ANSWER_SYSTEM, "user": f"Question: {questions[i % len(questions)]}", "context": context}
            for i in range(n)]


def verifier_inputs(n: int) -> List[dict]:
    out = []
    for i in range(n):
        claim, src, label = VERIFIER_CASES[i % len(VERIFIER_CASES)]
        out.append({"system": VERIFIER_SYSTEM, "user": f"CLAIM: {claim}\n\nSOURCE: {SOURCES[src]}",
                    "context": "", "label": label, "source": SOURCES[src]})
    return out


ROLE_SPECS = {
    "planner": (PlannerOut, planner_inputs, 200),
    "answer": (AnswerOut, answer_inputs, 350),
    "verifier": (VerifierOut, verifier_inputs, 150),
}


async def probe_role(role: str, n: int, model: str) -> dict:
    schema, make_inputs, max_tokens = ROLE_SPECS[role]
    rows = []
    for i, item in enumerate(make_inputs(n)):
        t0 = time.perf_counter()
        with record_llm_calls() as calls:
            try:
                out = await llm_service.structured_call(schema, item["system"], item["user"], context=item["context"],
                                                        role=role, model=model, max_tokens=max_tokens)
                status, value = ("valid_first" if len(calls) == 1 else "valid_after_retry"), out.model_dump()
            except LLMStructuredOutputError as e:
                status, value = "failed", {"error": e.details.get("last_error", "")[:300]}
        row = {"i": i, "status": status, "seconds": round(time.perf_counter() - t0, 1), "output": value,
               "prompt_tokens": calls[-1].prompt_tokens if calls else None,
               "output_tokens": calls[-1].output_tokens if calls else None,
               "tokens_per_second": calls[-1].tokens_per_second if calls else None}
        if role == "verifier" and status != "failed":
            row["label"] = item["label"]
            row["correct"] = value["supported"] == item["label"]
            quote = value["evidence_quote"].strip()
            row["quote_in_source"] = (not quote) or quote.rstrip(".") in item["source"]
        rows.append(row)
        print(f"  {role:<8} {i + 1:>3}/{n} {status:<17} {row['seconds']:5.1f}s"
              + (f"  correct={row.get('correct')}" if role == "verifier" else ""), flush=True)

    def count(status):
        return sum(r["status"] == status for r in rows)

    valid = count("valid_first") + count("valid_after_retry")
    summary = {"role": role, "model": model, "calls": n, "valid_first": count("valid_first"),
               "valid_after_retry": count("valid_after_retry"), "failed": count("failed"),
               "valid_rate": round(valid / n, 4),
               "avg_seconds": round(sum(r["seconds"] for r in rows) / n, 1),
               "avg_tokens_per_second": round(sum(r["tokens_per_second"] or 0 for r in rows) / n, 2)}
    if role == "verifier":
        judged = [r for r in rows if "correct" in r]
        summary["judgment_accuracy"] = round(sum(r["correct"] for r in judged) / max(1, len(judged)), 4)
        summary["quote_copied_from_source"] = round(sum(r["quote_in_source"] for r in judged) / max(1, len(judged)), 4)
    return {"summary": summary, "rows": rows}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="calls per role")
    ap.add_argument("--roles", default="planner,answer,verifier")
    ap.add_argument("--model", default=llm_service.model)
    args = ap.parse_args()

    # Warm-up so model loading time isn't counted against the first call
    await llm_service.generate_answer(system_prompt="Reply with OK.", user_prompt="OK", temperature=0.0,
                                      max_tokens=3, model=args.model, role="warmup")
    report = {}
    for role in args.roles.split(","):
        print(f"\n=== {role} ({args.model}) - {args.n} calls ===", flush=True)
        report[role] = await probe_role(role.strip(), args.n, args.model)
        print("SUMMARY", json.dumps(report[role]["summary"]), flush=True)

    out_dir = BACKEND / "logs"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"probe_structured_{args.model.replace(':', '-')}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path}", flush=True)
    await llm_service.close()


if __name__ == "__main__":
    asyncio.run(main())
