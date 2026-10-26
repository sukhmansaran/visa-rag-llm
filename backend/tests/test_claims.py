"""M4.1 claim splitting and M4.2 claim checks (code blocks, model advises) on the verified path."""

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import claims as cl
from app.services import evidence as ev
from app.services.prompt_registry import get_prompt, load_lock

DATA = json.loads((Path(__file__).parent / "data" / "entailment_cases.json").read_text(encoding="utf-8"))
PASSAGE = DATA["passages"]["bio_fee"]


# ---------------------------------------------------------------- M4.1 splitting

@pytest.mark.parametrize("answer,expected", [
    ("Biometrics are valid for 10 years. Children under 14 are exempt.",
     ["Biometrics are valid for 10 years.", "Children under 14 are exempt."]),
    ("It costs CAN$85 per person; families applying at the same time pay at most CAN$170.",
     ["It costs CAN$85 per person", "families applying at the same time pay at most CAN$170."]),
    ("You can work up to 24 hours a week, and unlimited hours in breaks.",
     ["You can work up to 24 hours a week, and unlimited hours in breaks."]),  # one number: one claim
    ("Yes.", []),
])
def test_split_claims(answer, expected):
    assert cl.split_claims(answer) == expected


# ---------------------------------------------------------------- M4.2 code layer: blocks, never a correct claim

def test_the_code_layer_never_blocks_a_correct_claim_in_the_set():
    for case in DATA["claims"]:
        if case["supported"]:
            assert cl.code_check(case["claim"], DATA["passages"][case["passage"]], case.get("question", "")) == [], case


@pytest.mark.parametrize("claim,problem", [
    ("Biometrics cost CAN$100 per person.", "numbers: 100"),
    ("Every applicant pays CAN$85.", "overreach: 'every'"),
    ("Children under 18 do not have to give biometrics.", "numbers: 18"),  # every local model accepted this one
])
def test_the_code_layer_blocks(claim, problem):
    passage = PASSAGE if "CAN$" in claim else DATA["passages"]["bio_exempt"]
    assert any(p.startswith(problem) for p in cl.code_check(claim, passage)), cl.code_check(claim, passage)


def test_numbers_the_user_gave_are_allowed():
    passage = DATA["passages"]["pgwp_length"]
    claim = "A 10-month diploma leads to a PGWP valid for up to 10 months."
    assert cl.code_check(claim, passage) and cl.code_check(claim, passage, "after a 10-month diploma?") == []


# ---------------------------------------------------------------- M4.2 on a part

SOURCES = {2: "Fee: CAN$85 per person; families applying at the same time pay a maximum total of CAN$170."}
GOOD = {"answer": "Biometrics cost CAN$85 per person.", "source_number": 2,
        "evidence_quote": "Fee: CAN$85 per person; families applying at the same time pay a maximum total of CAN$170."}


@pytest.mark.asyncio
async def test_a_doubted_claim_marks_the_part_partially_verified(fake_llm):
    fake_llm.when(r"Question: How much", GOOD)
    fake_llm.when(r"Claim:", {"supported": "partial", "reason": "per person only"})
    result = await ev.answer_part("How much is the biometrics fee?", "ctx", SOURCES, None)
    assert (result.status, result.partial, result.claims) == ("verified", True, 1)
    assert "(partially verified)" in ev.compose([result])


@pytest.mark.asyncio
async def test_a_supported_claim_is_plain_verified(fake_llm):
    fake_llm.when(r"Question: How much", GOOD)
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    result = await ev.answer_part("How much is the biometrics fee?", "ctx", SOURCES, None)
    assert (result.status, result.partial) == ("verified", False)
    assert "partially" not in ev.compose([result])


@pytest.mark.asyncio
async def test_a_claim_failing_the_code_check_blocks_the_part(fake_llm):
    fake_llm.when(r"Question: How much", {**GOOD, "answer": "Every applicant pays CAN$85."})
    result = await ev.answer_part("How much is the biometrics fee?", "ctx", SOURCES, None)
    assert result.status == "unverified" and any("overreach" in p for p in result.problems)
    assert not any(c["kind"] == "structured" and "Claim:" in c["user_prompt"] for c in fake_llm.calls)  # no model call


@pytest.mark.asyncio
async def test_the_model_check_can_be_switched_off(fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "VERIFY_CLAIMS_WITH_MODEL", False)
    fake_llm.when(r"Question: How much", GOOD)
    result = await ev.answer_part("How much is the biometrics fee?", "ctx", SOURCES, None)
    assert (result.status, result.partial) == ("verified", False)
    assert sum(c["kind"] == "structured" for c in fake_llm.calls) == 1  # the evidence call only


@pytest.mark.asyncio
async def test_an_unreadable_model_check_counts_as_a_doubt(fake_llm):
    fake_llm.when(r"Question: How much", GOOD)
    fake_llm.when(r"Claim:", "not json")
    result = await ev.answer_part("How much is the biometrics fee?", "ctx", SOURCES, None)
    assert (result.status, result.partial) == ("verified", True)


def test_the_prompt_is_registered_and_locked():
    prompt = get_prompt("entailment")
    assert load_lock()["entailment"][str(prompt.version)] == prompt.fingerprint


def test_the_entailment_set_is_well_formed():
    assert all(c["passage"] in DATA["passages"] for c in DATA["claims"])
    assert sum(not c["supported"] for c in DATA["claims"]) >= 25 and sum(c["supported"] for c in DATA["claims"]) >= 20
