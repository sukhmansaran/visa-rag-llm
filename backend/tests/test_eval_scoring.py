"""The evaluation scorer (scripts/eval_rag.py, M0.8) measures what it claims to."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eval_rag  # noqa: E402

CASE = {"id": "c", "type": "multi_part", "question": "How much money and how many hours?",
        "must_include": [[r"23,?448"], [r"\b24\b"]], "must_not": [r"\b40 hours"]}


def test_all_parts_answered():
    s = eval_rag.score(CASE, "You need 23,448 CAD [Source 1] and may work 24 hours a week [Source 2].",
                       "23,448 ... 24 hours", llm_called=True)
    assert s["passed"] and s["coverage"] == 1.0 and not s["ungrounded_numbers"]


def test_partial_answer_has_partial_coverage_and_fails():
    s = eval_rag.score(CASE, "You need 23,448 CAD.", "23,448", llm_called=True)
    assert not s["passed"] and s["coverage"] == 0.5 and s["missing"] == [[r"\b24\b"]]


def test_forbidden_claim_fails():
    s = eval_rag.score(CASE, "23,448 and 24, or even 40 hours.", "23,448 24", llm_called=True)
    assert not s["passed"] and s["forbidden"] == [r"\b40 hours"]


def test_invented_numbers_are_flagged_but_numbers_from_history_are_not():
    case = dict(CASE, history=[{"role": "user", "content": "I have 3 kids"}, {"role": "assistant", "content": "Noted, 35,888 CAD."}])
    s = eval_rag.score(case, "23,448 and 24 hours; for your family 35,888; a fee of 1,085.", "23,448 24", llm_called=True)
    assert s["ungrounded_numbers"] == ["1085"]


def test_gap_acknowledged_or_refused():
    case = {"id": "u", "type": "unanswerable", "question": "q", "must_include": [], "must_not": [],
            "expect_gap_acknowledged": True}
    assert eval_rag.score(case, "The official sources I have don't cover that.", "", llm_called=True)["passed"]
    assert eval_rag.score(case, "Refused.", "", llm_called=False)["passed"]  # no model call = refusal
    assert not eval_rag.score(case, "It costs 2,075 dollars.", "", llm_called=True)["passed"]


def test_expected_block_must_actually_be_blocked():
    case = {"id": "b", "type": "sensitive", "question": "q", "must_include": [], "must_not": [], "expect_blocked": True}
    assert eval_rag.score(case, "I can't help with that.", "", llm_called=False, source="guardrail_refusal")["passed"]
    s = eval_rag.score(case, "Here is how...", "", llm_called=True, source="llm_rag")
    assert not s["passed"] and s["blocked_ok"] is False


def test_tool_choice_checks_rule_engine_use():
    case = dict(CASE, expect_rules=True)
    answer = "23,448 and 24"
    assert eval_rag.score(case, answer, answer, llm_called=True, rules_used=True)["rules_ok"] is True
    s = eval_rag.score(case, answer, answer, llm_called=True, rules_used=False)
    assert s["rules_ok"] is False and not s["passed"]
    assert eval_rag.score(CASE, answer, answer, llm_called=True, rules_used=False)["rules_ok"] is None  # not expected


def test_placeholder_citation_is_flagged():
    assert eval_rag.score(CASE, "23,448 and 24 [Source N]", "23,448 24", llm_called=True)["placeholder_citation"]


def test_summary_aggregates_runs_and_marks_unstable_cases():
    def run(passed, source="llm_rag", coverage=1.0, rules_ok=None):
        return {"passed": passed, "coverage": coverage, "missing": [], "forbidden": [], "gap_ok": None,
                "blocked_ok": None, "rules_used": None, "rules_ok": rules_ok, "ungrounded_numbers": [],
                "placeholder_citation": False, "latency_s": 10.0, "source": source, "llm_called": source == "llm_rag",
                "prompt_tokens": 900, "tokens_per_second": 5.0}

    results = [
        {"id": "a", "type": "single", "passed": True, "stable": True, "run_results": [run(True), run(True), run(True)]},
        {"id": "b", "type": "multi_part", "passed": True, "stable": False,
         "run_results": [run(True), run(False, coverage=0.5), run(True)]},
        {"id": "c", "type": "tool_choice", "passed": False, "stable": True,
         "run_results": [run(False, rules_ok=False)] * 3},
    ]
    s = eval_rag.summarise("m", results, baseline=False, stream=False, runs=3)
    assert s["passed"] == 2 and s["cases"] == 3 and s["unstable_cases"] == ["b"]
    assert s["by_type"]["tool_choice"] == {"cases": 1, "passed": 0}
    assert s["multi_part_coverage"] == round((1 + 0.5 + 1) / 3, 2)
    assert s["tool_choice_accuracy"] == 0.0


def test_does_not_explicitly_state_counts_as_acknowledging_a_gap():
    case = {"id": "u", "type": "unanswerable", "question": "q", "must_include": [], "must_not": [],
            "expect_gap_acknowledged": True}
    answer = "The official IRCC regulatory facts do not explicitly state that you cannot get a second PGWP."
    assert eval_rag.score(case, answer, "", llm_called=True)["gap_ok"] is True


def test_numbers_in_the_apps_own_legal_notices_are_not_invented():
    """The app appends "Critical Legal Warning (Section 40 IRPA)"; the model didn't write that 40 (M0.14)."""
    from app.services.guardrails.legal_disclaimer import DISCLAIMER_MISREPRESENTATION
    answer = "I can't help with falsifying documents." + DISCLAIMER_MISREPRESENTATION
    assert eval_rag.score(CASE, answer, "", llm_called=True)["ungrounded_numbers"] == []
    # the model inventing the same number in its own text is still caught when it isn't a notice number
    assert eval_rag.score(CASE, "You need 12,345 CAD.", "", llm_called=True)["ungrounded_numbers"] == ["12345"]


def test_markdown_does_not_break_patterns():
    """A correct "apply at least 30 days **before** it expires" failed `before .{0,30}expir` (hardening 3)."""
    case = {"question": "q", "must_include": [[r"before .{0,30}expir"], [r"don.?t need"]]}
    answer = "Apply at least 30 days **before** it expires. You **don't** need a new letter."
    assert eval_rag.score(case, answer, "30 days", llm_called=True)["passed"]


def test_small_numbers_with_units_are_checked():
    """ "Biometrics are valid for 5 years" against sources saying 10 years must be flagged (hardening 3)."""
    case = {"question": "How long are biometrics valid?", "must_include": []}
    s = eval_rag.score(case, "They are valid for **5 years** [Source 1].", "give them once every 10 years",
                       llm_called=True)
    assert s["ungrounded_numbers"] == ["5"]
    ok = eval_rag.score(case, "A 3-year PGWP; step 1 is easy.", "you may get a PGWP valid for 3 years",
                        llm_called=True)
    assert ok["ungrounded_numbers"] == []  # "step 1" is numbering, "3-year" matches "3 years"


def test_a_number_beside_an_app_notice_is_still_checked():
    from app.services.guardrails.legal_disclaimer import DISCLAIMER_MISREPRESENTATION
    s = eval_rag.score(CASE, "Wait 7 days." + DISCLAIMER_MISREPRESENTATION, "", llm_called=True)
    assert s["ungrounded_numbers"] == ["7"]  # the notice's "5-year ban" and "Section 40" are ignored
