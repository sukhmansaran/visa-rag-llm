"""
Verification & Staleness Audit for IRCC Regulatory Rules (ircc_rules.yaml).
Ensures that all regulatory facts:
1. Include an official source_url pointing to canada.ca or provincial government.
2. Include an effective_from date.
3. Include a last_verified date.
4. Fails if last_verified is older than 90 days (preventing outdated regulatory figures).
"""

import pytest
from datetime import datetime, timezone, date
from pathlib import Path
import yaml

from app.services.rule_engine import RULES_DATA_PATH, load_ircc_rules, rule_engine


def test_ircc_rules_file_exists_and_loads():
    """Verify that ircc_rules.yaml exists and parses successfully."""
    assert RULES_DATA_PATH.exists(), f"Missing rules file at {RULES_DATA_PATH}"
    data = load_ircc_rules()
    assert isinstance(data, dict)
    assert "version" in data
    assert "last_updated" in data


def test_all_rule_facts_have_valid_source_and_verification_dates():
    """Verify each section in ircc_rules.yaml has source_url, effective_from, and last_verified."""
    data = load_ircc_rules()
    
    # Sections containing statutory rule facts
    rule_keys = [
        "proof_of_funds",
        "off_campus_work",
        "student_direct_stream",
        "post_graduation_work_permit",
        "provincial_attestation_letter",
        "express_entry_stem",
        "visitor_visa",
    ]

    for key in rule_keys:
        rule = data.get(key)
        assert rule is not None, f"Missing rule section: {key}"
        assert "rule_id" in rule, f"Rule {key} missing rule_id"
        assert "source_url" in rule, f"Rule {key} missing source_url"
        assert rule["source_url"].startswith("https://"), f"Rule {key} source_url must be HTTPS"
        assert any(
            domain in rule["source_url"] for domain in ["canada.ca", "gc.ca", "quebec.ca"]
        ), f"Rule {key} source_url must be an official government source"

        assert "effective_from" in rule, f"Rule {key} missing effective_from"
        assert "last_verified" in rule, f"Rule {key} missing last_verified"


def test_no_rule_fact_is_older_than_90_days():
    """
    Acceptance Criterion:
    A test fails if last_verified is older than 90 days from the current date.
    Prevents stale regulatory advice.
    """
    data = load_ircc_rules()
    rule_keys = [
        "proof_of_funds",
        "off_campus_work",
        "student_direct_stream",
        "post_graduation_work_permit",
        "provincial_attestation_letter",
        "express_entry_stem",
        "visitor_visa",
    ]

    # Real current date: a hardcoded date here meant the check could never actually go stale
    current_date = date.today()

    for key in rule_keys:
        rule = data[key]
        verified_str = rule["last_verified"]
        verified_date = datetime.strptime(verified_str, "%Y-%m-%d").date()

        days_stale = (current_date - verified_date).days
        assert days_stale >= 0, f"Rule {key} has future verification date: {verified_date}"
        assert days_stale <= 90, (
            f"Rule {key} last_verified ({verified_date}) is {days_stale} days old! "
            f"Regulatory facts must be re-verified against canada.ca at least every 90 days."
        )


def test_rule_engine_answers_contain_effective_dates_and_citations():
    """Verify that rule_engine.try_rule_answer includes effective date and source URL."""
    # 1. Work regulations
    work_facts = rule_engine.try_rule_answer("work", "canada", "student", query="How many hours can I work off-campus?")
    assert work_facts is not None
    assert "24 hours per week" in work_facts
    assert "as of November 8, 2024" in work_facts
    assert "https://www.canada.ca" in work_facts

    # 2. PGWP
    pgwp_facts = rule_engine.try_rule_answer("work", "canada", "student", query="What are the PGWP rules after graduation?")
    assert pgwp_facts is not None
    assert "November 1, 2024" in pgwp_facts
    assert "CLB 7" in pgwp_facts
    assert "https://www.canada.ca" in pgwp_facts

    # 3. Financial / POF
    pof_facts = rule_engine.try_rule_answer("financial", "canada", "student", query="How much proof of funds do I need?")
    assert pof_facts is not None
    current_single = rule_engine.current_single_applicant_funds()
    assert f"CAD ${current_single:,}" in pof_facts
    assert "TERMINATED" in pof_facts  # SDS status
    assert "https://www.canada.ca" in pof_facts


# Sections not yet checked by a person against source_url. Remove a key once the owner has reviewed it.
# All sections were reviewed by the owner on 2026-10-21 (M0.13 review sheet incl. the hardening-3 biometrics
# rows), so none remain. A new or changed section must be added here until it has been reviewed.
KNOWN_UNVERIFIED_SECTIONS = set()


def test_every_section_records_who_verified_it():
    data = load_ircc_rules()
    rule_keys = [k for k, v in data.items() if isinstance(v, dict) and "rule_id" in v]
    unverified = set()
    for key in rule_keys:
        verified_by = data[key].get("verified_by", "")
        assert verified_by, f"Rule {key} must record verified_by (who/what checked it, and when)"
        if "not yet checked" in verified_by:
            unverified.add(key)
    assert unverified == KNOWN_UNVERIFIED_SECTIONS, (
        f"Unverified sections changed: {sorted(unverified)}. Verify new data against canada.ca "
        f"and update KNOWN_UNVERIFIED_SECTIONS deliberately."
    )
