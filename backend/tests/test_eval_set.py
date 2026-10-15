"""
The evaluation set (M0.8) is well-formed: known case types, unique ids, compilable patterns, follow-up cases
carry history, unanswerable cases expect a gap, and every rules_keys entry exists in ircc_rules.yaml, so a
renamed or removed rule cannot silently orphan the cases that check it.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parent.parent
EVAL_SET = json.loads((BACKEND / "tests" / "data" / "rag_eval_set.json").read_text(encoding="utf-8"))
RULES = yaml.safe_load((BACKEND / "app" / "data" / "ircc_rules.yaml").read_text(encoding="utf-8"))
CASES = EVAL_SET["cases"]
TYPES = {"single", "multi_part", "tool_choice", "freshness", "distractor", "sensitive", "unanswerable", "follow_up", "language"}


def _rule_value(key: str):
    node = RULES
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(key)
        node = node[part]
    return node


def test_set_size_and_unique_ids():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    assert len(CASES) >= 60
    assert EVAL_SET["version"] == 2


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_is_well_formed(case):
    assert case["type"] in TYPES
    assert case["question"].strip()
    for group in case["must_include"]:
        assert isinstance(group, list) and group, "each part is a non-empty list of alternatives"
        for pattern in group:
            re.compile(pattern)
    for pattern in case["must_not"]:
        re.compile(pattern)
    if case["type"] == "follow_up":
        assert case.get("history") and all(t["role"] in ("user", "assistant") for t in case["history"])
    if case["type"] == "unanswerable":
        assert case.get("expect_gap_acknowledged") is True
    if case["type"] == "multi_part":
        assert len(case["must_include"]) >= 2, "a multi-part case checks every part"
    if not (case.get("expect_blocked") or case["type"] in ("unanswerable", "language")):
        assert case["must_include"], "an answerable case must check something"


@pytest.mark.parametrize("case", [c for c in CASES if c.get("rules_keys")], ids=lambda c: c["id"])
def test_rules_keys_exist_in_the_rules_file(case):
    for key in case["rules_keys"]:
        _rule_value(key)  # raises KeyError if the rule moved or was renamed


def test_every_type_is_covered():
    assert {c["type"] for c in CASES} == TYPES
    assert sum(c["critical"] for c in CASES) >= 15  # the quick gate needs a meaningful sample
