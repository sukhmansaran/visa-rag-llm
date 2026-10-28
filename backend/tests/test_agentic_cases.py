"""M5.3 agentic cases are well-formed: unique ids, questions the guardrail lets through, compilable patterns, a
scripted reply wherever the agent is expected to ask, profiles the profile tool can return."""

import json
import re
from pathlib import Path

import pytest

from app.services.guardrails.input_guardrail import input_guardrail
from app.services.tools import ProfileResult, TOOLS

DATA = json.loads((Path(__file__).parent / "data" / "agentic_cases.json").read_text(encoding="utf-8"))
CASES = DATA["dev"] + DATA["holdout"]


def test_ids_are_unique_and_both_splits_exist():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) and DATA["dev"] and DATA["holdout"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_is_well_formed(case):
    assert input_guardrail.evaluate(case["question"]).allowed
    assert set(case["expect_tools"]) <= set(TOOLS)
    assert bool(case.get("user_reply")) == case["expect_ask"]
    for group in case["must_include"]:
        for pattern in group:
            re.compile(pattern)
    for pattern in case["must_not"]:
        re.compile(pattern)
    if "profile" in case:
        ProfileResult(**case["profile"])
