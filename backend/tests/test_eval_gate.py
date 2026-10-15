"""The regression gate (scripts/eval_gate.py, M0.8) decides correctly; no Ollama needed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eval_gate  # noqa: E402

KEY = "off_campus_work.academic_session_max_hours_per_week"


def run(passed=True, ungrounded=()):
    return {"passed": passed, "ungrounded_numbers": list(ungrounded)}


def result(case_id, passed, runs=None, rules_keys=(), critical=True):
    runs = runs or [run(passed)]
    passes = sum(r["passed"] for r in runs)
    return {"id": case_id, "type": "single", "critical": critical, "rules_keys": list(rules_keys), "passed": passed,
            "passes": passes, "runs": len(runs), "stable": passes in (0, len(runs)), "run_results": runs}


def baseline(cases):
    return {"created": "2026-10-15", "model": "m", "summary": {"passed": 1, "cases": 1},
            "cases": {cid: {"passed": p, "ungrounded": u, "rules_values": rv} for cid, (p, u, rv) in cases.items()}}


def test_a_case_that_used_to_pass_and_now_fails_is_a_regression():
    findings = eval_gate.compare(baseline({"a": (True, False, {})}), [result("a", False)])
    assert findings["regressions"] == ["a (0/1 passed)"]


def test_improvements_and_still_failing_cases_do_not_fail_the_gate():
    findings = eval_gate.compare(baseline({"a": (False, False, {}), "b": (False, False, {})}),
                                 [result("a", True), result("b", False)])
    assert findings["improvements"] == ["a"] and not findings["regressions"]


def test_newly_invented_numbers_are_flagged():
    runs = [run(True, ["1085"]), run(True, ["1085"]), run(True)]
    findings = eval_gate.compare(baseline({"a": (True, False, {})}), [result("a", True, runs)])
    assert findings["new_ungrounded"] == ["a ['1085']"]
    # a case that already invented numbers in the baseline is not a new finding
    findings = eval_gate.compare(baseline({"a": (True, True, {})}), [result("a", True, runs)])
    assert not findings["new_ungrounded"]


def test_a_changed_rule_flags_the_cases_that_depend_on_it():
    current = eval_gate.rule_values([KEY])[KEY]
    unchanged = eval_gate.compare(baseline({"a": (True, False, {KEY: current})}), [result("a", True, rules_keys=[KEY])])
    assert not unchanged["rule_changes"]
    changed = eval_gate.compare(baseline({"a": (True, False, {KEY: current - 4})}), [result("a", True, rules_keys=[KEY])])
    assert changed["rule_changes"] == [f"a ({KEY})"]


def test_new_cases_are_reported_not_gated():
    findings = eval_gate.compare(baseline({}), [result("brand_new", False)])
    assert findings["new_cases"] == ["brand_new"] and not findings["regressions"]


def test_rule_values_resolve_nested_keys():
    values = eval_gate.rule_values([KEY, "proof_of_funds.does_not_exist"])
    assert values[KEY] == 24 and values["proof_of_funds.does_not_exist"] is None


def test_baseline_requires_three_runs_and_the_full_set():
    report = {"summary": {"runs": 1, "model": "m"}, "results": []}
    with pytest.raises(SystemExit, match="--runs 3"):
        eval_gate.build_baseline(report, {})
    report = {"summary": {"runs": 3, "model": "m"}, "results": [result("a", True)]}
    with pytest.raises(SystemExit, match="full set"):
        eval_gate.build_baseline(report, {})


def test_accepting_a_fixed_case_requires_three_runs_and_a_majority_pass():
    base = baseline({"a": (False, False, {}), "b": (True, False, {})})
    versions = {"model_digest": "d", "prompt_version": "p", "rules_version": "r"}
    fixed = {"summary": {"runs": 3}, "results": [result("a", True, [run(True), run(True), run(False)])]}

    assert eval_gate.accept_cases(base, fixed, versions, "2026-10-15") == ["a"]
    assert base["cases"]["a"]["passed"] is True and base["summary"]["passed"] == 2
    assert base["history"][-1]["accepted"] == ["a"] and base["rules_version"] == "r"

    with pytest.raises(SystemExit, match="--runs 3"):
        eval_gate.accept_cases(base, {"summary": {"runs": 1}, "results": []}, versions, "x")
    still_failing = {"summary": {"runs": 3}, "results": [result("b", False, [run(False)] * 3)]}
    with pytest.raises(SystemExit, match="did not pass"):
        eval_gate.accept_cases(base, still_failing, versions, "x")
    unknown = {"summary": {"runs": 3}, "results": [result("zzz", True, [run(True)] * 3)]}
    with pytest.raises(SystemExit, match="not in the baseline"):
        eval_gate.accept_cases(base, unknown, versions, "x")
