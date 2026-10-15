"""
Closed programs (SDS / Nigeria Student Express): any question naming one gets the closure fact from
ircc_rules.yaml, whatever the detected intent. Found by the M0.8 eval: "How do I apply under the Student
Direct Stream?" was answered with application steps for a program IRCC ended on 2024-11-08.
"""

import pytest

from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.rule_engine import rule_engine


@pytest.mark.parametrize("query", [
    "How do I apply under the Student Direct Stream to get faster processing?",
    "Is SDS still open for Indian students?",
    "What IELTS score do I need for the student-direct-stream?",
    "Nigeria Student Express requirements",
    "Can I use the Nigerian student express?",
])
def test_questions_naming_a_closed_program_get_the_closure_fact(query):
    fact = rule_engine.discontinued_program_fact(query)
    assert fact and "PROGRAM CLOSED" in fact
    assert "November 8, 2024" in fact and "regular study permit" in fact
    assert "end-student-direct-stream-nigeria-student-express" in fact  # cites the IRCC notice


@pytest.mark.parametrize("query", [
    "How many hours can I work off campus?",
    "What are the study permit documents?",
    "Is the PDS form required?",          # no false hit on similar letters
    "",
])
def test_other_questions_get_no_closure_fact(query):
    assert rule_engine.discontinued_program_fact(query) is None


def test_the_fact_follows_the_rules_file(monkeypatch):
    section = dict(rule_engine.rules_data["student_direct_stream"], termination_notice="TEST NOTICE TEXT")
    monkeypatch.setitem(rule_engine.rules_data, "student_direct_stream", section)
    assert "TEST NOTICE TEXT" in rule_engine.discontinued_program_fact("Is SDS open?")

    monkeypatch.setitem(rule_engine.rules_data, "student_direct_stream", dict(section, is_active=True))
    assert rule_engine.discontinued_program_fact("Is SDS open?") is None  # reopened -> no closure claim


def test_funds_answer_uses_the_same_notice():
    funds = rule_engine.try_rule_answer("financial", "canada", "student", query="How much money do I need?")
    assert rule_engine.rules_data["student_direct_stream"]["termination_notice"] in funds


@pytest.mark.asyncio
async def test_pipeline_gives_the_model_the_closure_fact(fake_llm, monkeypatch):
    from app.services.tracing import TraceRecorder, activate_trace

    async def no_chunks(**_):
        return []

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", no_chunks)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"PROGRAM CLOSED", "The Student Direct Stream ended on November 8, 2024 [Source 1].")

    trace = TraceRecorder("test", query="How do I apply under the Student Direct Stream?")
    with activate_trace(trace):
        result = await rp.rag_pipeline.process_query("How do I apply under the Student Direct Stream?", db=object())

    assert result["answer"].startswith("The Student Direct Stream ended")
    assert "PROGRAM CLOSED" in fake_llm.calls[0]["context"]
    rules_step = next(s for s in trace.steps if s["name"] == "rules")
    assert rules_step["closed_program_fact"] is True and rules_step["rule_facts"] is True
