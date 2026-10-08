"""
Comprehensive test suite for the deterministic IRCC Rule Engine (Milestone 4 - Task 4.1).
Validates statutory mathematical calculations, CLB benchmark conversions,
and Provincial Attestation Letter (PAL) requirements.
"""

import pytest
from app.services.rule_engine import (
    RuleEngine,
    rule_engine,
    ProofOfFundsResult,
    CLBConversionResult,
    PALEvaluationResult,
)


class TestProofOfFundsCalculations:
    """Mathematical verification of IRCC Proof of Living Expenses statutory table."""

    def test_single_student_base_living_expenses(self):
        """Single student outside Quebec requires exactly CAD $20,635 living expenses."""
        result = rule_engine.calculate_proof_of_funds(family_members_count=1)
        assert result.family_count == 1
        assert result.base_living_cad == 20635
        assert result.additional_dependents_cad == 0
        assert result.total_required_cad == 20635.0
        assert "CAD $20,635.00" in result.breakdown

    def test_student_with_one_dependent(self):
        """Student + 1 family member (family size 2) requires CAD $25,690."""
        result = rule_engine.calculate_proof_of_funds(family_members_count=2)
        assert result.family_count == 2
        assert result.base_living_cad == 20635
        assert result.additional_dependents_cad == (25690 - 20635)
        assert result.total_required_cad == 25690.0

    def test_student_with_two_dependents_family_of_three(self):
        """Family of 3 requires CAD $31,583 living funds."""
        result = rule_engine.calculate_proof_of_funds(family_members_count=3)
        assert result.family_count == 3
        assert result.total_required_cad == 31583.0

    def test_family_of_five(self):
        """Family of 5 requires CAD $43,492 living funds."""
        result = rule_engine.calculate_proof_of_funds(family_members_count=5)
        assert result.family_count == 5
        assert result.total_required_cad == 43492.0

    def test_large_family_extrapolation_beyond_seven(self):
        """Families larger than 7 add CAD $5,559 per additional person."""
        # Family of 8: $54,611 (7 people) + $5,559 = $60,170
        result = rule_engine.calculate_proof_of_funds(family_members_count=8)
        assert result.family_count == 8
        assert result.total_required_cad == 54611.0 + 5559.0

    def test_tuition_and_transport_addition(self):
        """Calculates exact total sum including tuition and transportation."""
        result = rule_engine.calculate_proof_of_funds(
            family_members_count=2,
            tuition_cad=18500.50,
            transport_cad=3000.0,
        )
        expected_total = 25690.0 + 18500.50 + 3000.0
        assert result.total_required_cad == expected_total
        assert "First-Year Tuition: CAD $18,500.50" in result.breakdown
        assert "Round-Trip Transportation: CAD $3,000.00" in result.breakdown

    def test_quebec_specific_schedule(self):
        """Quebec living benchmark follows provincial schedule."""
        result = rule_engine.calculate_proof_of_funds(family_members_count=1, in_quebec=True)
        assert result.base_living_cad == 15078
        assert "MIFI" in result.authority_statute


class TestCLBBenchmarkConversions:
    """Verification of language test conversions to Canadian Language Benchmark (CLB)."""

    def test_ielts_general_clb7_minimum_fsw_eligible(self):
        """IELTS General with 6.0 in all bands yields CLB 7 and is FSW eligible."""
        scores = {"listening": 6.0, "reading": 6.0, "writing": 6.0, "speaking": 6.0}
        result = rule_engine.convert_to_clb("ielts general", scores)
        assert result.individual_clb == {
            "listening": 7,
            "reading": 7,
            "writing": 7,
            "speaking": 7,
        }
        assert result.overall_clb == 7
        assert result.express_entry_fsw_eligible is True
        assert result.sds_eligible is True

    def test_ielts_general_high_scores_clb8_and_clb9(self):
        """IELTS scores L:8.5, R:8.0, W:7.5, S:7.5 achieve CLB 10."""
        scores = {"listening": 8.5, "reading": 8.0, "writing": 7.5, "speaking": 7.5}
        result = rule_engine.convert_to_clb("ielts general", scores)
        assert result.overall_clb == 10
        assert result.express_entry_fsw_eligible is True

    def test_ielts_single_weak_band_fails_fsw(self):
        """If one band is below 6.0 (e.g. Reading 5.5 = CLB 6), applicant is ineligible for FSW."""
        scores = {"listening": 7.0, "reading": 5.5, "writing": 6.5, "speaking": 6.5}
        result = rule_engine.convert_to_clb("ielts general", scores)
        assert result.individual_clb["reading"] == 6
        assert result.overall_clb == 6
        assert result.express_entry_fsw_eligible is False

    def test_celpip_direct_clb_mapping(self):
        """CELPIP scores map 1:1 to CLB levels."""
        scores = {"listening": 8.0, "reading": 7.0, "writing": 9.0, "speaking": 7.0}
        result = rule_engine.convert_to_clb("celpip general", scores)
        assert result.individual_clb["listening"] == 8
        assert result.individual_clb["reading"] == 7
        assert result.individual_clb["writing"] == 9
        assert result.individual_clb["speaking"] == 7
        assert result.overall_clb == 7
        assert result.express_entry_fsw_eligible is True

    def test_pte_core_clb7_benchmark(self):
        """PTE Core scores matching CLB 7 thresholds."""
        scores = {"listening": 65, "reading": 62, "writing": 72, "speaking": 70}
        result = rule_engine.convert_to_clb("pte core", scores)
        assert result.overall_clb == 7
        assert result.express_entry_fsw_eligible is True


class TestProvincialAttestationLetterPAL:
    """Verification of Provincial Attestation Letter (PAL) requirement and exemption criteria."""

    def test_undergraduate_degree_requires_pal(self):
        """Undergraduate bachelor's degree applicants require mandatory PAL."""
        result = rule_engine.evaluate_pal_requirement("Bachelor of Computer Science")
        assert result.is_required is True
        assert result.exemption_category is None
        assert "PAL MANDATORY" in result.summary

    def test_k12_minor_children_exempt_from_pal(self):
        """Primary and secondary school minors are exempt from PAL."""
        result = rule_engine.evaluate_pal_requirement("Secondary High School Grade 11", is_minor=True)
        assert result.is_required is False
        assert result.exemption_category == "K-12 Minor Student Exemption"
        assert "PAL EXEMPT" in result.summary

    def test_study_permit_extension_exempt_from_pal(self):
        """In-Canada study permit extensions are exempt from PAL."""
        result = rule_engine.evaluate_pal_requirement("Diploma", is_extension=True)
        assert result.is_required is False
        assert result.exemption_category == "Study Permit Extension Exemption"

    def test_short_term_exchange_exempt_from_pal(self):
        """Visiting exchange students under 6 months are exempt."""
        result = rule_engine.evaluate_pal_requirement("Short Term Exchange (< 6 months)")
        assert result.is_required is False
        assert "PAL EXEMPT" in result.summary


class TestDynamicQueryExtractionAndRuleAnswer:
    """Verifies that queries mentioning specific dependents or scores trigger exact statutory data."""

    def test_query_with_dependents_returns_calculated_proof_of_funds(self):
        """A question about proof of funds for 3 people extracts the exact CAD $31,583 calculation."""
        query = "How much proof of funds do I need for a family of 3 in Canada?"
        facts = rule_engine.try_rule_answer("financial", "canada", "student", query=query)
        assert facts is not None
        assert "STATUTORY PROOF OF FUNDS CALCULATION" in facts
        assert "CAD $31,583.00" in facts
        assert "3 individuals" in facts

    def test_query_with_ielts_score_returns_clb_breakdown(self):
        """A question mentioning IELTS scores outputs exact CLB breakdown."""
        query = "I took IELTS and got 6.5 in all bands. Can I apply for Express Entry?"
        facts = rule_engine.try_rule_answer("general", "canada", "pr", query=query)
        assert facts is not None
        assert "CANADIAN LANGUAGE BENCHMARK (CLB) CONVERSION" in facts
        assert "CLB 8" in facts or "CLB 7" in facts
        assert "ELIGIBLE" in facts

    def test_query_with_pal_extension_returns_exemption_rule(self):
        """A query asking about PAL for extension returns exemption rule."""
        query = "Do I need a PAL for an in-Canada study permit extension?"
        facts = rule_engine.try_rule_answer("checklist", "canada", "student", query=query)
        assert facts is not None
        assert "PROVINCIAL ATTESTATION LETTER (PAL) MANDATE" in facts
        assert "EXEMPT" in facts
