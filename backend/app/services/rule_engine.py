"""
Rule Engine service for authoritative IRCC regulatory knowledge.
Provides verified factual context for prompt grounding in the RAG pipeline.
"""

from typing import Optional, Dict, Any


class RuleEngine:
    """Authoritative regulatory knowledge engine for Canadian immigration facts."""
    
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

        # 1. Express Entry & Skilled Tech / Software Engineer Eligibility
        if any(w in query_lower for w in ["express entry", "fsw", "federal skilled worker", "pr", "permanent residence"]) or \
           (any(w in query_lower for w in ["software engineer", "developer", "programmer", "python", "tech"]) and any(w in query_lower for w in ["apply", "eligible", "eligibility", "canada", "entry"])):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — EXPRESS ENTRY & STEM TECH PATHWAYS:\n"
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

        # 2. International Student Off-Campus Work Regulations
        if any(w in query_lower for w in [
            "work off-campus", "off campus", "work off campus", "hours can a student work", 
            "how many hours", "work while studying", "work on study permit", "student work"
        ]):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — INTERNATIONAL STUDENT WORK REGULATIONS:\n"
                "- Off-Campus Work Authorization: International students holding a valid Canadian study permit are authorized to work off-campus "
                "without a separate work permit if they meet all eligibility criteria.\n"
                "- Allowed Working Hours:\n"
                "  * Regular Academic Sessions: Eligible full-time students are permitted to work up to 20 hours per week off-campus during regular semesters.\n"
                "  * Scheduled Academic Breaks: Students are permitted to work full-time (up to 40 hours per week) during regularly scheduled academic breaks "
                "(such as winter break, summer vacation, and reading weeks) if they hold full-time status before and after the break.\n"
                "- Mandatory Eligibility Criteria:\n"
                "  1. Must be enrolled as a full-time student at a Designated Learning Institution (DLI).\n"
                "  2. Must be enrolled in a post-secondary academic, vocational, or professional training program that is at least 6 months in duration leading to a degree, diploma, or certificate.\n"
                "  3. The study permit must have a condition explicitly permitting off-campus work.\n"
                "  4. Must obtain a valid Social Insurance Number (SIN) from Service Canada prior to commencing any work.\n"
                "- On-Campus Work: International students may work an unrestricted number of hours on-campus at their institution if registered full-time.\n"
                "- Regulatory Authority: IRCC International Student Program Off-Campus Work Guidelines (IRPR Section 186(v))."
            )

        # 3. Post-Graduation Work Permit (PGWP) Guidelines
        if any(w in query_lower for w in [
            "pgwp", "post-graduation work permit", "post graduation", "work permit after graduation",
            "graduate from", "master's degree", "masters degree", "university of toronto"
        ]):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — POST-GRADUATION WORK PERMIT (PGWP):\n"
                "- Program & Institution Eligibility: Graduates from eligible programs at recognized Designated Learning Institutions (DLIs), "
                "including the University of Toronto, qualify for a Post-Graduation Work Permit (PGWP).\n"
                "- Duration of the PGWP:\n"
                "  * Programs 2 years or longer: Automatically eligible for a full 3-year PGWP.\n"
                "  * Master's Degree Special Policy: Under updated IRCC regulations, graduates of Master's degree programs are eligible for a 3-year PGWP "
                "even if their program duration was between 8 months and 2 years, acknowledging that master's graduates are high-demand candidates.\n"
                "  * For a 2-year Master's degree at University of Toronto: The applicant qualifies for the maximum 3-year PGWP.\n"
                "- Nature of Work Permit: The PGWP is an open work permit. It does not require a Labour Market Impact Assessment (LMIA) or a specific job offer, "
                "and allows the holder to work for any eligible Canadian employer in any location.\n"
                "- Application Deadline: The applicant must apply within 180 days of receiving their official completion letter or final transcripts from the institution.\n"
                "- Maintained Status: If applying before the study permit expires, graduates are legally authorized to work full-time while waiting for the PGWP decision.\n"
                "- Regulatory Authority: IRCC Post-Graduation Work Permit Program (PGWPP) Regulations."
            )

        # 4. Canada Student Visa Financial Requirements
        if any(w in query_lower for w in ["financial", "funds", "cost", "bank", "gic", "tuition", "living expense", "money", "fee", "sds"]) or \
           (country == "canada" and visa_type == "student" and intent == "financial"):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — STUDY PERMIT FINANCIAL REQUIREMENTS:\n"
                "- Cost of Living Requirement: The minimum proof of funds requirement for living expenses is CAD $20,635 per year for a single applicant studying in any Canadian province outside Quebec. "
                "(This threshold was updated by IRCC in 2024 to reflect realistic cost of living benchmarks).\n"
                "- First-Year Tuition: In addition to the CAD $20,635 living expenses, the applicant must demonstrate sufficient accessible funds to pay the entire first year of tuition fees.\n"
                "- Transportation & Settlement: Must demonstrate sufficient funds to cover round-trip transportation to Canada for the applicant and any accompanying family members.\n"
                "- Student Direct Stream (SDS) / GIC Requirement: Applicants applying through expedited streams (such as SDS) must purchase a Guaranteed Investment Certificate (GIC) of at least CAD $20,635 "
                "from a CDIC-insured participating Canadian financial institution and provide proof of full upfront tuition payment for the first year.\n"
                "- Acceptable Proof of Financial Support: Bank statements for the past 4 months, proof of a Canadian bank account, GIC certificate, loan approval letter, proof of scholarship/funding, or proof of paid tuition and housing.\n"
                "- Regulatory Authority: IRCC Proof of Financial Support Guidelines for International Students."
            )

        # 5. Canada Student Visa Document Checklist & Attestation
        if any(w in query_lower for w in ["checklist", "document", "pal", "attestation", "loa", "dli", "require", "paperwork"]) or \
           (country == "canada" and visa_type == "student" and intent == "checklist"):
            return (
                "OFFICIAL IRCC REGULATORY FACTS — CANADIAN STUDY PERMIT CHECKLIST:\n"
                "- Letter of Acceptance (LOA): Official unconditional acceptance letter from a Designated Learning Institution (DLI) containing the school's DLI number.\n"
                "- Provincial Attestation Letter (PAL): A mandatory Provincial Attestation Letter (PAL) or Territorial Attestation Letter (TAL) from the provincial government where the school is located "
                "(required for most post-secondary study permit applications).\n"
                "- Valid Travel Document: A valid passport with remaining validity covering the intended duration of studies.\n"
                "- Proof of Financial Support: Proof of funds covering CAD $20,635 living expenses plus first-year tuition (bank statements, GIC, payment receipts).\n"
                "- Statement of Purpose (SOP): A clear explanation of academic intent, course choice, post-graduation career goals, and ties ensuring temporary resident compliance.\n"
                "- Upfront Medical Exam & Police Certificates: If residing in designated countries or required for program clinical placements.\n"
                "- Regulatory Authority: IRCC Study Permit Document Checklist & PAL Guidelines."
            )

        # 6. General Canada Visitor / Tourist Requirements
        if any(w in query_lower for w in ["tourist", "visitor", "travel", "visit canada", "eta", "trv"]) or visa_type == "tourist":
            return (
                "OFFICIAL IRCC REGULATORY FACTS — CANADA VISITOR VISA & ETA:\n"
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

