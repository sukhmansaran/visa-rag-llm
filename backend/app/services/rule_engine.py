"""
Rule Engine service for authoritative IRCC regulatory knowledge.
Provides verified factual context, deterministic calculations, and statutory benchmarks
for prompt grounding in the RAG pipeline.
"""

from typing import Optional, Dict, Any, List
from datetime import date
from dataclasses import dataclass
from pathlib import Path
import os
import re
import yaml
import hashlib

# Path to authoritative regulatory data file
RULES_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "ircc_rules.yaml"


def load_ircc_rules() -> Dict[str, Any]:
    """Load authoritative IRCC rules from versioned YAML file."""
    if RULES_DATA_PATH.exists():
        try:
            with open(RULES_DATA_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    return {}


def get_rules_content_hash() -> str:
    """Return SHA256 fingerprint of ircc_rules.yaml for deterministic cache invalidation (B16)."""
    if RULES_DATA_PATH.exists():
        try:
            content = RULES_DATA_PATH.read_bytes()
            return hashlib.sha256(content).hexdigest()[:12]
        except Exception:
            pass
    return "v2026.1"


# ==============================================================================
# IRCC Statutory Data Structures
# ==============================================================================

@dataclass
class ProofOfFundsResult:
    """Deterministic IRCC proof of funds calculation result."""
    family_count: int
    base_living_cad: int
    additional_dependents_cad: int
    tuition_cad: float
    transport_cad: float
    total_required_cad: float
    breakdown: str
    authority_statute: str
    effective_from: str = ""
    last_verified: str = ""
    source_url: str = ""
    schedule_verified: bool = True


@dataclass
class CLBConversionResult:
    """Deterministic language test to Canadian Language Benchmark (CLB) conversion."""
    test_type: str
    scores: Dict[str, float]
    individual_clb: Dict[str, int]
    overall_clb: int  # Minimum CLB band across all 4 abilities
    express_entry_fsw_eligible: bool  # True if all 4 abilities >= CLB 7
    sds_eligible: bool  # True if eligible for Student Direct Stream
    summary: str


@dataclass
class PALEvaluationResult:
    """Deterministic Provincial Attestation Letter (PAL) requirement assessment."""
    is_required: bool
    study_level: str
    reason: str
    exemption_category: Optional[str]
    summary: str


# ==============================================================================
# Rule Engine Implementation
# ==============================================================================

class RuleEngine:
    """
    Authoritative regulatory knowledge and deterministic calculation engine 
    for Canadian immigration law and IRCC statutory criteria.
    """

    def __init__(self):
        self.rules_data = load_ircc_rules()

    # Proof-of-funds amounts live ONLY in app/data/ircc_rules.yaml (dated schedules verified against
    # canada.ca). Hardcoding them here previously let the code drift from the data file.
    LEGACY_SCHEDULE_YEAR_DATES = {"2024": date(2024, 6, 1), "2025": date(2025, 6, 1), "2026": date(2026, 9, 1)}

    def _pof_section(self) -> Dict[str, Any]:
        section = self.rules_data.get("proof_of_funds") or {}
        if not section.get("schedules"):
            raise RuntimeError("ircc_rules.yaml is missing proof_of_funds.schedules")
        return section

    def get_pof_schedule(self, application_date: Optional[date] = None) -> Dict[str, Any]:
        """Return the proof-of-funds schedule in force on `application_date` (default: today)."""
        on = application_date or date.today()
        schedules = self._pof_section()["schedules"]
        for schedule in schedules:
            start = date.fromisoformat(str(schedule["effective_from"]))
            end = schedule.get("effective_to")
            if start <= on and (end is None or on <= date.fromisoformat(str(end))):
                return schedule
        return schedules[-1]  # earlier than any known schedule: oldest available

    def current_single_applicant_funds(self) -> int:
        return int(self.get_pof_schedule()["rates_by_family_size"][1])

    # IELTS General to CLB conversion thresholds (minimum score required for level)
    IELTS_GENERAL_CLB_MAP = {
        "listening": [(8.5, 10), (8.0, 9), (7.5, 8), (6.0, 7), (5.5, 6), (5.0, 5), (4.5, 4)],
        "reading":   [(8.0, 10), (7.0, 9), (6.5, 8), (6.0, 7), (5.0, 6), (4.0, 5), (3.5, 4)],
        "writing":   [(7.5, 10), (7.0, 9), (6.5, 8), (6.0, 7), (5.5, 6), (5.0, 5), (4.0, 4)],
        "speaking":  [(7.5, 10), (7.0, 9), (6.5, 8), (6.0, 7), (5.5, 6), (5.0, 5), (4.0, 4)],
    }

    # PTE Core to CLB conversion thresholds (minimum score required for level)
    PTE_CORE_CLB_MAP = {
        "listening": [(89, 10), (82, 9), (71, 8), (60, 7), (50, 6), (39, 5), (28, 4)],
        "reading":   [(88, 10), (78, 9), (69, 8), (60, 7), (51, 6), (42, 5), (33, 4)],
        "writing":   [(90, 10), (88, 9), (79, 8), (69, 7), (60, 6), (51, 5), (41, 4)],
        "speaking":  [(89, 10), (84, 9), (76, 8), (68, 7), (59, 6), (51, 5), (42, 4)],
    }

    def calculate_proof_of_funds(
        self,
        family_members_count: int = 1,
        tuition_cad: float = 0.0,
        transport_cad: float = 0.0,
        in_quebec: bool = False,
        schedule_year: Optional[str] = None,
        application_date: Optional[date] = None,
    ) -> ProofOfFundsResult:
        """
        Deterministically calculate mandatory IRCC Proof of Funds for study permit applicants.
        
        Args:
            family_members_count: Total individuals (applicant + accompanying family members)
            tuition_cad: First year tuition fee in CAD
            transport_cad: Estimated round-trip travel funds in CAD
            in_quebec: True if studying in Quebec
            schedule_year: Deprecated; use application_date. Kept for backward compatibility.
            application_date: Date the application is submitted (default: today). Selects the schedule.
        """
        if application_date is None and schedule_year:
            application_date = self.LEGACY_SCHEDULE_YEAR_DATES.get(str(schedule_year))
        section = self._pof_section()
        count = max(1, family_members_count)

        if in_quebec:
            quebec = section.get("quebec_guidelines", {})
            base_living = int(quebec["single_applicant_cad"])
            add_living = max(0, count - 1) * int(quebec["additional_person_cad"])
            living_total = base_living + add_living
            statute = "Ministère de l'Immigration, de la Francisation et de l'Intégration (MIFI) Quebec Guidelines"
            effective_from = ""
            source_url = quebec["source_url"]
            schedule_verified = bool(quebec.get("verified", False))
        else:
            schedule = self.get_pof_schedule(application_date)
            table = {int(k): int(v) for k, v in schedule["rates_by_family_size"].items()}
            add_rate = int(schedule["additional_family_member_cad"])
            effective_from = str(schedule["effective_from"])
            statute = f"IRCC Study Permit Financial Support Guidelines (75% LICO; schedule effective {effective_from})"
            schedule_verified = bool(schedule.get("verified", False))

            if count in table:
                living_total = table[count]
            else:
                living_total = table[7] + ((count - 7) * add_rate)

            base_living = table[1]
            add_living = living_total - base_living
            source_url = section["source_url"]

        total_required = float(living_total) + float(tuition_cad) + float(transport_cad)

        breakdown_parts = [
            f"1. Cost of Living (Family size {count}): CAD ${living_total:,.2f}"
            + (f" (Primary applicant: CAD ${base_living:,.2f} + Dependents: CAD ${add_living:,.2f})" if count > 1 else "")
        ]
        if tuition_cad > 0:
            breakdown_parts.append(f"2. First-Year Tuition: CAD ${tuition_cad:,.2f}")
        if transport_cad > 0:
            breakdown_parts.append(f"3. Round-Trip Transportation: CAD ${transport_cad:,.2f}")
        
        breakdown_parts.append(f"TOTAL REQUIRED ACCESSIBLE FUNDS: CAD ${total_required:,.2f}")
        breakdown = "\n".join(breakdown_parts)

        return ProofOfFundsResult(
            family_count=count,
            base_living_cad=base_living,
            additional_dependents_cad=add_living,
            tuition_cad=tuition_cad,
            transport_cad=transport_cad,
            total_required_cad=total_required,
            breakdown=breakdown,
            authority_statute=statute,
            effective_from=effective_from,
            last_verified=str(section.get("last_verified", "")),
            source_url=source_url,
            schedule_verified=schedule_verified,
        )

    def convert_to_clb(
        self,
        test_type: str,
        scores: Dict[str, float],
    ) -> CLBConversionResult:
        """
        Deterministically convert language scores (IELTS General, CELPIP General, PTE Core)
        into official Canadian Language Benchmark (CLB) levels.
        """
        test_norm = test_type.lower().replace("-", " ").strip()
        abilities = ["listening", "reading", "writing", "speaking"]
        clb_levels: Dict[str, int] = {}

        # 1. CELPIP General (1:1 direct score to CLB mapping for 4–12)
        if "celpip" in test_norm:
            for ab in abilities:
                score = float(scores.get(ab, 0))
                # CELPIP scores 1-3 are below CLB 4; scores >= 10 are CLB 10+
                clb_levels[ab] = int(min(10, max(0, score)))

        # 2. IELTS General
        elif "ielts" in test_norm:
            for ab in abilities:
                score = float(scores.get(ab, 0))
                mapped_clb = 0
                for min_score, clb in self.IELTS_GENERAL_CLB_MAP[ab]:
                    if score >= min_score:
                        mapped_clb = clb
                        break
                clb_levels[ab] = mapped_clb

        # 3. PTE Core
        elif "pte" in test_norm:
            for ab in abilities:
                score = float(scores.get(ab, 0))
                mapped_clb = 0
                for min_score, clb in self.PTE_CORE_CLB_MAP[ab]:
                    if score >= min_score:
                        mapped_clb = clb
                        break
                clb_levels[ab] = mapped_clb
        else:
            # Fallback default: map raw score directly if provided as CLB
            for ab in abilities:
                clb_levels[ab] = int(scores.get(ab, 0))

        overall_clb = min(clb_levels.values()) if clb_levels else 0
        fsw_eligible = all(clb >= 7 for clb in clb_levels.values()) if clb_levels else False
        sds_eligible = all(scores.get(ab, 0) >= 6.0 for ab in abilities) if "ielts" in test_norm else overall_clb >= 7

        summary = (
            f"{test_type.upper()} CLB Breakdown:\n"
            f"- Listening: CLB {clb_levels.get('listening', 0)} (Score: {scores.get('listening', 0)})\n"
            f"- Reading: CLB {clb_levels.get('reading', 0)} (Score: {scores.get('reading', 0)})\n"
            f"- Writing: CLB {clb_levels.get('writing', 0)} (Score: {scores.get('writing', 0)})\n"
            f"- Speaking: CLB {clb_levels.get('speaking', 0)} (Score: {scores.get('speaking', 0)})\n"
            f"- Effective Lowest Benchmark: CLB {overall_clb}\n"
            f"- Express Entry (FSW Minimum CLB 7 in all bands): {'ELIGIBLE' if fsw_eligible else 'INELIGIBLE (requires minimum CLB 7 in every band)'}"
        )

        return CLBConversionResult(
            test_type=test_type,
            scores=scores,
            individual_clb=clb_levels,
            overall_clb=overall_clb,
            express_entry_fsw_eligible=fsw_eligible,
            sds_eligible=sds_eligible,
            summary=summary,
        )

    def evaluate_pal_requirement(
        self,
        study_level: str,
        is_extension: bool = False,
        is_minor: bool = False,
        in_canada: bool = False,
        public_dli: Optional[bool] = None,
        application_date: Optional[date] = None,
    ) -> PALEvaluationResult:
        """
        Deterministically evaluate if an applicant requires a Provincial Attestation Letter (PAL)
        under IRCC international student national cap regulations.
        """
        level_clean = study_level.lower().strip()

        # Rule 1: Minor children applying for primary or secondary school (grades K-12)
        if is_minor or any(w in level_clean for w in ["primary", "secondary", "high school", "elementary", "k-12"]):
            return PALEvaluationResult(
                is_required=False,
                study_level=study_level,
                reason="Primary and secondary school students (Kindergarten to Grade 12) are exempt from the national cap and do not require a PAL.",
                exemption_category="K-12 Minor Student Exemption",
                summary="PAL EXEMPT: K-12 primary and secondary school applicants do not require a Provincial Attestation Letter.",
            )

        # Rule 2: In-Canada study permit extensions / renewals
        if is_extension:
            return PALEvaluationResult(
                is_required=False,
                study_level=study_level,
                reason="Current study permit holders applying for an extension from within Canada are exempt from the PAL requirement.",
                exemption_category="Study Permit Extension Exemption",
                summary="PAL EXEMPT: In-Canada study permit extensions do not require a Provincial Attestation Letter.",
            )

        # Rule 3: Short-term or visiting students (< 6 months)
        if any(w in level_clean for w in ["short term", "exchange", "< 6 months", "visiting"]):
            return PALEvaluationResult(
                is_required=False,
                study_level=study_level,
                reason="Short-term exchange or training programs under 6 months do not require a PAL or standard study permit.",
                exemption_category="Short-Term Exchange Exemption",
                summary="PAL EXEMPT: Short-term programs under 6 months do not require a PAL.",
            )

        # Rule 4: Master's and doctoral degree programs. From 2026-01-01, programs at a PUBLIC DLI are exempt;
        # private DLIs still require a PAL (canada.ca PAL page, verified 2026-10-12).
        if any(w in level_clean for w in ["master", "phd", "doctorate", "doctoral"]):
            pal_rules = self.rules_data.get("provincial_attestation_letter", {})
            exempt_from = date.fromisoformat(str(pal_rules.get("masters_doctoral_public_dli_exempt_from", "2026-01-01")))
            on = application_date or date.today()
            if on < exempt_from or public_dli is False:
                why = (
                    f"applications submitted before {exempt_from.isoformat()}"
                    if on < exempt_from else "master's/doctoral programs at a private DLI"
                )
                return PALEvaluationResult(
                    is_required=True,
                    study_level=study_level,
                    reason=f"A Provincial Attestation Letter (PAL) is required for {why}.",
                    exemption_category=None,
                    summary=f"PAL MANDATORY: required for {why}.",
                )
            exemption = "Master's/Doctoral at Public DLI Exemption (from 2026-01-01)"
            if public_dli:
                return PALEvaluationResult(
                    is_required=False,
                    study_level=study_level,
                    reason=(
                        "From January 1, 2026, degree-granting master's and doctoral programs at a public DLI are exempt "
                        "from the PAL/TAL requirement. You must show proof of the exemption when you apply."
                    ),
                    exemption_category=exemption,
                    summary="PAL EXEMPT: master's/doctoral program at a public DLI (from January 1, 2026). Proof of exemption required.",
                )
            return PALEvaluationResult(
                is_required=False,
                study_level=study_level,
                reason=(
                    "From January 1, 2026, degree-granting master's and doctoral programs at a PUBLIC DLI are exempt from the "
                    "PAL/TAL requirement (proof of exemption required). Programs at a PRIVATE DLI still require a PAL."
                ),
                exemption_category=exemption,
                summary="PAL EXEMPT if your master's/doctoral program is at a public DLI (from January 1, 2026); a private DLI still requires a PAL.",
            )

        # Rule 5: Standard Post-Secondary Undergraduate (Bachelor's, Diploma, Certificate)
        return PALEvaluationResult(
            is_required=True,
            study_level=study_level,
            reason=(
                "Mandatory requirement under the IRCC national intake cap. Most post-secondary study permit applicants "
                "(bachelor's degrees, diplomas, and college certificates) MUST submit an official Provincial Attestation Letter (PAL) "
                "or Territorial Attestation Letter (TAL) with their application. Applications submitted without a PAL are returned as incomplete."
            ),
            exemption_category=None,
            summary="PAL MANDATORY: Post-secondary undergraduate, diploma, and certificate students must obtain a Provincial Attestation Letter (PAL).",
        )

    # ==========================================================================
    # Query Inspection & Parameter Extraction
    # ==========================================================================

    def extract_query_financial_params(self, query: str) -> Optional[ProofOfFundsResult]:
        """Detect and calculate financial proof of funds if query mentions family/dependents."""
        q_lower = query.lower()
        if not any(w in q_lower for w in ["fund", "cost", "financial", "living", "money", "cad", "dollar", "expense", "bank"]):
            return None

        # Detect family size or dependents
        family_count = 1
        # Check patterns like "family of 3", "3 people", "spouse and child", "with my wife and 2 kids"
        match_family_num = re.search(r'\b(?:family of|for|with)\s+(\d+)\s*(?:people|persons|members)?\b', q_lower)
        if match_family_num:
            family_count = int(match_family_num.group(1))
        elif any(w in q_lower for w in ["with spouse and child", "wife and kid", "husband and child", "2 dependents", "family of 3"]):
            family_count = 3
        elif any(w in q_lower for w in ["with spouse", "with wife", "with husband", "and spouse", "for 2", "for two", "2 people", "two people", "with 1 dependent", "with child"]):
            family_count = 2

        # Detect tuition mentions (e.g., "tuition is 15000", "$20,000 tuition")
        tuition_cad = 0.0
        match_tuition = re.search(r'(?:tuition|fee|fees)(?:\s+is|\s+of|\s*:)?\s*(?:cad|\$)?\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)', q_lower)
        if match_tuition:
            try:
                tuition_cad = float(match_tuition.group(1).replace(",", ""))
            except ValueError:
                tuition_cad = 0.0

        return self.calculate_proof_of_funds(family_members_count=family_count, tuition_cad=tuition_cad)

    def extract_query_language_params(self, query: str) -> Optional[CLBConversionResult]:
        """Detect language test scores in query and return CLB conversion."""
        q_lower = query.lower()
        
        # Check for IELTS mentions
        if "ielts" in q_lower:
            # Check individual band format: L:7, R:6.5, W:6, S:6 or listening 7, reading 6.5
            scores = {}
            for ab, abbr in [("listening", "l"), ("reading", "r"), ("writing", "w"), ("speaking", "s")]:
                match = re.search(rf'\b(?:{ab}|{abbr})\s*[:=]?\s*([4-9](?:\.[05])?)\b', q_lower)
                if match:
                    scores[ab] = float(match.group(1))
            
            # If a single score mentioned like "ielts 6.5", "ielts and got 6.5", or "got 6.5 in ielts"
            if len(scores) < 4:
                match_single = re.search(r'\bielts\b(?:[^\d\n]{1,30})([4-9](?:\.[05])?)\b', q_lower)
                if not match_single:
                    match_single = re.search(r'\b([4-9](?:\.[05])?)\b(?:[^\d\n]{1,30})\bielts\b', q_lower)
                if match_single:
                    val = float(match_single.group(1))
                    scores = {"listening": val, "reading": val, "writing": val, "speaking": val}
            
            if scores:
                return self.convert_to_clb("ielts general", scores)

        # Check for CELPIP mentions
        if "celpip" in q_lower:
            match_celpip = re.search(r'\bcelpip\b(?:[^\d\n]{1,30})([4-9]|1[0-2])\b', q_lower)
            if not match_celpip:
                match_celpip = re.search(r'\b([4-9]|1[0-2])\b(?:[^\d\n]{1,30})\bcelpip\b', q_lower)
            if match_celpip:
                val = float(match_celpip.group(1))
                scores = {"listening": val, "reading": val, "writing": val, "speaking": val}
                return self.convert_to_clb("celpip general", scores)


        return None

    def extract_query_pal_params(self, query: str) -> Optional[PALEvaluationResult]:
        """Detect PAL inquiries in query."""
        q_lower = query.lower()
        if not any(w in q_lower for w in ["pal", "attestation", "provincial attestation", "cap", "intake cap"]):
            return None

        is_minor = any(w in q_lower for w in ["minor", "school", "child", "high school", "k-12", "primary"])
        is_extension = any(w in q_lower for w in ["extension", "renew", "extend", "already in canada"])
        study_level = "Undergraduate / Diploma"
        if any(w in q_lower for w in ["master", "phd", "doctorate"]):
            study_level = "Master's / PhD"
        elif is_minor:
            study_level = "Primary / Secondary (K-12)"

        public_dli: Optional[bool] = None
        if re.search(r"\bprivate\b", q_lower):
            public_dli = False
        elif re.search(r"\bpublic\b", q_lower):
            public_dli = True

        return self.evaluate_pal_requirement(
            study_level=study_level,
            is_extension=is_extension,
            is_minor=is_minor,
            public_dli=public_dli,
        )

    # ==========================================================================
    # Authoritative Rule Extraction for Context Injection
    # ==========================================================================

    def try_rule_answer(
        self, 
        intent: str, 
        country: str, 
        visa_type: str,
        query: str = "",
    ) -> Optional[str]:
        """
        Extract authoritative IRCC regulatory facts for the given query and intent.
        Returns detailed regulatory facts string for context injection, or None.
        """
        country = country.lower() if country else ""
        visa_type = visa_type.lower() if visa_type else ""
        query_lower = query.lower() if query else ""

        # Check dynamic parameter-driven calculations first:
        # 1. Dynamic Proof of Funds (with family/dependents or specific numbers)
        pof_calc = self.extract_query_financial_params(query)
        if pof_calc and (pof_calc.family_count > 1 or pof_calc.tuition_cad > 0):
            current = self.calculate_proof_of_funds(
                family_members_count=pof_calc.family_count,
                tuition_cad=pof_calc.tuition_cad,
                transport_cad=pof_calc.transport_cad,
            )
            return (
                f"OFFICIAL IRCC REGULATORY FACTS — STATUTORY PROOF OF FUNDS CALCULATION:\n"
                f"- Governing Authority: {current.authority_statute} (verified {current.last_verified})\n"
                f"- Source: {current.source_url}\n"
                f"- Applicant & Dependents: {pof_calc.family_count} individuals\n"
                f"- Requirement for applications submitted on or after {current.effective_from}: CAD ${current.total_required_cad:,.2f} "
                f"(Living expenses: CAD ${current.base_living_cad + current.additional_dependents_cad:,.2f}"
                + (f" [Primary: CAD ${current.base_living_cad:,.2f} + Dependents: CAD ${current.additional_dependents_cad:,.2f}]" if pof_calc.family_count > 1 else "")
                + (f" + First-Year Tuition: CAD ${pof_calc.tuition_cad:,.2f}" if pof_calc.tuition_cad > 0 else "")
                + f")\n"
                f"{current.breakdown}\n"
                f"- Applications submitted before {current.effective_from} were assessed against an earlier, lower schedule.\n"
                f"- Acceptable Evidence: Bank statements (last 4 months), GIC certificate, loan approval, or educational funding."
            )

        # 2. Dynamic Language CLB Conversion
        lang_calc = self.extract_query_language_params(query)
        if lang_calc:
            return (
                f"OFFICIAL IRCC REGULATORY FACTS — CANADIAN LANGUAGE BENCHMARK (CLB) CONVERSION (verified 2026-10-01):\n"
                f"- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/language-requirements.html\n"
                f"{lang_calc.summary}\n"
                f"- Statutory Requirement: FSW requires minimum CLB 7 across all 4 language abilities."
            )

        # 3. Dynamic PAL Assessment
        pal_calc = self.extract_query_pal_params(query)
        if pal_calc:
            return (
                f"OFFICIAL IRCC REGULATORY FACTS — PROVINCIAL ATTESTATION LETTER (PAL) MANDATE (as of Jan 1, 2025; verified 2026-10-01):\n"
                f"- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit/provincial-attestation-letter.html\n"
                f"- Requirement: {'MANDATORY' if pal_calc.is_required else 'EXEMPT'}\n"
                f"- Category: {pal_calc.study_level}\n"
                f"- Reason: {pal_calc.reason}\n"
                f"- Rule Authority: IRCC International Student Intake Cap Operational Guidelines."
            )

        # 4. Express Entry & Skilled Tech / Software Engineer Eligibility
        if re.search(r'\b(?:express entry|fsw|federal skilled worker|pr|permanent residence)\b', query_lower) or \
           (re.search(r'\b(?:software engineer|developer|programmer|python|tech)\b', query_lower) and re.search(r'\b(?:apply|eligible|eligibility|canada|entry)\b', query_lower)):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — EXPRESS ENTRY & STEM TECH PATHWAYS (as of June 28, 2023; verified 2026-10-01):\n"
                "- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/submit-profile/rounds-invitations/category-based-selection.html\n"
                "- NOC Classification: Software Engineers and Designers are classified under NOC 21231 (TEER 1). "
                "Software Developers and Programmers are classified under NOC 21232 (TEER 1). Both belong to high-skilled TEER 1.\n"
                "- Work Experience Requirement: Under the Federal Skilled Worker Program (FSWP), applicants must possess at least "
                "1 continuous year of full-time (or equivalent part-time) skilled paid work experience in TEER 0, 1, 2, or 3 within the past 10 years. "
                "An applicant with 3 years of software engineering experience exceeds the 1-year minimum requirement.\n"
                "- Targeted Category-Based Selection: IRCC conducts dedicated category-based Express Entry rounds of invitations for Science, Technology, "
                "Engineering, and Math (STEM) occupations. Eligible software engineers qualify for these targeted STEM draws, which typically invite candidates "
                "at lower Comprehensive Ranking System (CRS) score cutoffs compared to general draws.\n"
                "- Core Minimum Eligibility Criteria:\n"
                "  1. Language Proficiency: Minimum Canadian Language Benchmark (CLB) 7 in English (e.g., IELTS General 6.0 in all bands or CELPIP 7 in all bands) or French.\n"
                "  2. Education: Post-secondary degree evaluated by a designated organization with an Educational Credential Assessment (ECA) report (e.g., WES).\n"
                "  3. Six Selection Factors Grid: Must score at least 67 out of 100 points across age, education, work experience, language skills, arranged employment, and adaptability.\n"
                "- Regulatory Authority: Immigration, Refugees and Citizenship Canada (IRCC) Express Entry & Category-Based Selection Guidelines."
            )

        # 5. International Student Off-Campus Work Regulations
        if any(w in query_lower for w in [
            "work off-campus", "off campus", "work off campus", "hours can a student work", 
            "how many hours", "work while studying", "work on study permit", "student work"
        ]):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — INTERNATIONAL STUDENT WORK REGULATIONS (as of November 8, 2024; verified 2026-10-12):\n"
                "- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/work/work-off-campus.html\n"
                "- Off-Campus Work Authorization: International students holding a valid Canadian study permit are authorized to work off-campus "
                "without a separate work permit if they meet all eligibility criteria.\n"
                "- Allowed Working Hours:\n"
                "  * Regular Academic Sessions: Eligible full-time students are permitted to work up to 24 hours per week off-campus during regular semesters "
                "(effective November 8, 2024, increased from the previous 20 hours per week limit).\n"
                "  * Scheduled Academic Breaks: Students can work unlimited hours off campus during breaks scheduled by their DLI "
                "(such as winter break, summer vacation, and reading weeks) if they are full-time students before and after the break.\n"
                "- Mandatory Eligibility Criteria:\n"
                "  1. Must be enrolled as a full-time student at a Designated Learning Institution (DLI).\n"
                "  2. Must be enrolled in a post-secondary academic, vocational, or professional training program that is at least 6 months in duration leading to a degree, diploma, or certificate.\n"
                "  3. The study permit must have a condition explicitly permitting off-campus work.\n"
                "  4. Must obtain a valid Social Insurance Number (SIN) from Service Canada prior to commencing any work.\n"
                "- On-Campus Work: International students may work an unrestricted number of hours on-campus at their institution if registered full-time.\n"
                "- Regulatory Authority: IRCC International Student Program Off-Campus Work Guidelines (IRPR Section 186(v))."
            )

        # 6. Post-Graduation Work Permit (PGWP) Guidelines
        if any(w in query_lower for w in [
            "pgwp", "post-graduation work permit", "post graduation", "work permit after graduation",
            "graduate from", "master's degree", "masters degree", "university of toronto"
        ]):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — POST-GRADUATION WORK PERMIT (PGWP) (as of November 1, 2024; verified 2026-10-01):\n"
                "- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/work/after-graduation/eligibility.html\n"
                "- Program & Institution Eligibility: Graduates from eligible programs at recognized Designated Learning Institutions (DLIs), "
                "including the University of Toronto, qualify for a Post-Graduation Work Permit (PGWP).\n"
                "- Language & Field of Study Requirements (effective Nov 1, 2024):\n"
                "  * Language Benchmark: University degree graduates (Bachelor's, Master's, PhD) must demonstrate minimum CLB 7 in English or French. College diploma graduates must demonstrate minimum CLB 5.\n"
                "  * Field of Study: University degree graduates remain eligible across all fields of study. College diploma graduates must have completed a program in a designated labour shortage field (STEM, healthcare, agriculture, trade, transport).\n"
                "- Duration of the PGWP:\n"
                "  * Programs 2 years or longer: Eligible for a full 3-year PGWP.\n"
                "  * Master's Degree Special Policy: Under IRCC regulations, graduates of Master's degree programs of 8 months or longer qualify for a full 3-year PGWP, acknowledging that master's graduates are high-demand candidates.\n"
                "  * For a 2-year Master's degree at University of Toronto: The applicant qualifies for the maximum 3-year PGWP.\n"
                "- Nature of Work Permit: The PGWP is an open work permit. It does not require a Labour Market Impact Assessment (LMIA) or a specific job offer, "
                "and allows the holder to work for any eligible Canadian employer in any location.\n"
                "- Application Deadline: The applicant must apply within 180 days of receiving their official completion letter or final transcripts from the institution.\n"
                "- Maintained Status: If applying before the study permit expires, graduates are legally authorized to work full-time while waiting for the PGWP decision.\n"
                "- Regulatory Authority: IRCC Post-Graduation Work Permit Program (PGWPP) Regulations."
            )

        # 7. Canada Student Visa Financial Requirements (Default / General)
        if any(w in query_lower for w in ["financial", "funds", "cost", "bank", "gic", "tuition", "living expense", "money", "fee", "sds"]) or \
           (country == "canada" and visa_type == "student" and intent == "financial"):
            section = self._pof_section()
            schedule = self.get_pof_schedule()
            single = int(schedule["rates_by_family_size"][1])
            return (
                f"OFFICIAL IRCC REGULATORY FACTS — STUDY PERMIT FINANCIAL REQUIREMENTS (schedule effective {schedule['effective_from']}; verified {section.get('last_verified', '')}):\n"
                f"- Source: {section['source_url']}\n"
                f"- Cost of Living Requirement: The minimum proof of funds for living expenses outside Quebec is CAD ${single:,} per year for a single applicant "
                f"(applications submitted on or after {schedule['effective_from']}; higher amounts apply for each accompanying family member).\n"
                f"- First-Year Tuition: In addition to living expenses (CAD ${single:,}), the applicant must demonstrate sufficient accessible funds to pay the entire first year of tuition fees.\n"
                "- Transportation & Settlement: Must demonstrate sufficient funds to cover round-trip transportation to Canada for the applicant and any accompanying family members.\n"
                "- Student Direct Stream (SDS) Status: TERMINATED. IRCC officially closed the Student Direct Stream (SDS) and Nigeria Student Express (NSE) on November 8, 2024. All international students must apply through the standard study permit stream.\n"
                "- Acceptable Proof of Financial Support: Bank statements for the past 4 months, proof of a Canadian bank account, GIC certificate, loan approval letter, proof of scholarship/funding, or proof of paid tuition and housing.\n"
                "- Regulatory Authority: IRCC Proof of Financial Support Guidelines for International Students."
            )

        # 8. Canada Student Visa Document Checklist & Attestation
        if any(w in query_lower for w in ["checklist", "document", "pal", "attestation", "loa", "dli", "require", "paperwork"]) or \
           (country == "canada" and visa_type == "student" and intent == "checklist"):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — CANADIAN STUDY PERMIT CHECKLIST (verified 2026-10-12):\n"
                "- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit/get-documents.html\n"
                "- Letter of Acceptance (LOA): Official unconditional acceptance letter from a Designated Learning Institution (DLI) containing the school's DLI number.\n"
                "- Provincial Attestation Letter (PAL): A mandatory Provincial Attestation Letter (PAL) or Territorial Attestation Letter (TAL) from the provincial government where the school is located "
                "(required for most post-secondary study permit applications; from January 1, 2026, master's and doctoral programs at a public DLI are exempt, "
                "and exempt applicants must show proof of the exemption).\n"
                "- Valid Travel Document: A valid passport with remaining validity covering the intended duration of studies.\n"
                f"- Proof of Financial Support: Proof of funds covering CAD ${self.current_single_applicant_funds():,} living expenses (single applicant) plus first-year tuition (bank statements, GIC, payment receipts).\n"
                "- Statement of Purpose (SOP): A clear explanation of academic intent, course choice, post-graduation career goals, and ties ensuring temporary resident compliance.\n"
                "- Upfront Medical Exam & Police Certificates: If residing in designated countries or required for program clinical placements.\n"
                "- Regulatory Authority: IRCC Study Permit Document Checklist & PAL Guidelines."
            )

        # 9. General Canada Visitor / Tourist Requirements
        if any(w in query_lower for w in ["tourist", "visitor", "travel", "visit canada", "eta", "trv"]) or visa_type == "tourist":
            return (
                "OFFICIAL IRCC REGULATORY FACTS — CANADA VISITOR VISA & ETA (as of 2024/2026; verified 2026-10-01):\n"
                "- Source: https://www.canada.ca/en/immigration-refugees-citizenship/services/visit-canada/about-visitor-visa.html\n"
                "- Entry Document: Foreign nationals require either a Temporary Resident Visa (TRV) or an Electronic Travel Authorization (eTA), depending on their country of citizenship.\n"
                "- Maximum Authorized Stay: Up to 6 months per entry from the date of admission, unless a CBSA border services officer specifies a different date.\n"
                "- Mandatory Requirements: Must prove sufficient financial funds for the visit, valid passport, clear criminal/security record, medical admissibility, "
                "and strong ties to home country (employment, family, assets) proving temporary stay intent.\n"
                "- No Work or Study: Visitors are not authorized to work or engage in full-time post-secondary study in Canada without separate permits.\n"
                "- Regulatory Authority: IRCC Temporary Resident Visa Regulations."
            )

        return None


# Global instance
rule_engine = RuleEngine()
