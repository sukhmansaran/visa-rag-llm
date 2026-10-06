"""
Unit tests for Visa Constitution Specification and Policy Contract.
"""

import pytest
from app.core.visa_constitution import (
    ViolationType,
    AllowedIntent,
    REFUSAL_MESSAGES,
    VISA_CONSTITUTION_ARTICLES,
    HIGH_RISK_TERMS,
    LEGAL_DISCLAIMER,
)


def test_violation_types_completeness():
    """Verify all critical violation types exist."""
    expected_violations = {
        "OUT_OF_SCOPE",
        "CODE_REQUEST",
        "PROMPT_INJECTION",
        "MALICIOUS_REQUEST",
        "INSUFFICIENT_EVIDENCE",
    }
    actual_violations = {v.value for v in ViolationType}
    assert expected_violations.issubset(actual_violations)


def test_refusal_messages_mapping():
    """Every violation type must have an explicit, non-empty refusal message."""
    for violation in ViolationType:
        assert violation in REFUSAL_MESSAGES
        msg = REFUSAL_MESSAGES[violation]
        assert isinstance(msg, str)
        assert len(msg) > 20
        # Refusal messages must never leak internal prompts or variable names
        assert "prompt" not in msg.lower() or violation == ViolationType.PROMPT_INJECTION
        assert "{" not in msg and "}" not in msg


def test_constitution_articles_count_and_content():
    """Ensure the 15 Articles of the Visa Constitution are defined."""
    assert len(VISA_CONSTITUTION_ARTICLES) == 15
    for article in VISA_CONSTITUTION_ARTICLES:
        assert isinstance(article, str)
        assert len(article) > 10


def test_allowed_intents():
    """Verify essential visa domain intents are registered."""
    expected_intents = [
        AllowedIntent.STUDY_PERMIT,
        AllowedIntent.TRAVEL_VISA,
        AllowedIntent.WORK_PERMIT,
        AllowedIntent.VISA_ELIGIBILITY,
        AllowedIntent.DOCUMENT_REQUIREMENTS,
        AllowedIntent.STATEMENT_OF_PURPOSE,
        AllowedIntent.VISA_REFUSAL,
    ]
    for intent in expected_intents:
        assert intent in AllowedIntent


def test_high_risk_terms_and_disclaimer():
    """Verify high-risk legal terms trigger appropriate disclaimer availability."""
    assert "refusal" in HIGH_RISK_TERMS
    assert "misrepresentation" in HIGH_RISK_TERMS
    assert "inadmissible" in HIGH_RISK_TERMS
    assert "RCIC" in LEGAL_DISCLAIMER or "immigration" in LEGAL_DISCLAIMER.lower()
