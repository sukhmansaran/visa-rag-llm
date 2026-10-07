"""
Legal & High-Risk Disclaimer Engine (Milestone 3 - Task 3.3).
Detects high-risk Canadian immigration scenarios:
1. Refusals & rejections (e.g. section 216(1), refusal letters)
2. Section 40 misrepresentation & 5-year bans
3. Inadmissibility (criminal, medical, financial)
4. Removal orders & CBSA deportation enforcement
5. Judicial reviews, appeals (IAD), and procedural fairness letters (PFL)

Appends contextually tailored, authoritative legal advisories recommending
licensed RCIC consultants or Canadian immigration lawyers.
"""

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from app.core.logging_config import get_logger
from app.core.visa_constitution import HIGH_RISK_TERMS, LEGAL_DISCLAIMER

logger = get_logger(__name__)


class RiskCategory(str, Enum):
    """High-risk immigration legal categories."""
    REFUSAL = "REFUSAL"
    MISREPRESENTATION = "MISREPRESENTATION"
    INADMISSIBILITY = "INADMISSIBILITY"
    ENFORCEMENT = "ENFORCEMENT"
    LITIGATION_APPEAL = "LITIGATION_APPEAL"


@dataclass
class DisclaimerEvaluationResult:
    """Evaluation result from the legal disclaimer engine."""
    is_high_risk: bool
    risk_categories: List[str] = field(default_factory=list)
    detected_terms: List[str] = field(default_factory=list)
    disclaimer_text: Optional[str] = None
    annotated_text: str = ""


# Tailored, context-aware legal notices
DISCLAIMER_REFUSAL = (
    "\n\n> ⚠️ **Important Legal Advisory:** Visa refusal matters involve strict regulatory procedures, "
    "GCMS officer notes, and statutory reconsideration or reapplication deadlines. This assistant provides "
    "educational guidance only and is not a licensed RCIC or legal counsel. For refused applications, consult a "
    "Regulated Canadian Immigration Consultant (RCIC) or a Canadian immigration lawyer before reapplying."
)

DISCLAIMER_MISREPRESENTATION = (
    "\n\n> 🛑 **Critical Legal Warning (Section 40 IRPA):** Allegations of misrepresentation carry severe consequences "
    "under Canadian law, including an automatic 5-year ban from Canada and inadmissibility. Do NOT submit further "
    "documents without qualified legal advice. We strongly recommend immediate consultation with an authorized "
    "Canadian immigration lawyer specializing in litigation."
)

DISCLAIMER_INADMISSIBILITY_ENFORCEMENT = (
    "\n\n> ⚠️ **Urgent Legal Notice:** Removal orders, inadmissibility findings, and Federal Court judicial reviews "
    "involve strict statutory limitation periods and complex administrative law. Please retain an authorized "
    "Canadian immigration lawyer or licensed RCIC immediately to protect your legal rights."
)

DISCLAIMER_GENERAL = (
    "\n\n> ℹ️ **Legal Disclaimer:** This guidance is for educational and informational purposes only "
    "and does not constitute formal legal advice. Canadian immigration law changes frequently; "
    "consult a licensed RCIC or Canadian immigration attorney for individual case assessment."
)


class LegalDisclaimerEngine:
    """
    Deterministic rule engine that tags sensitive legal inquiries
    and injects compliant RCIC/lawyer escalation disclaimers.
    """

    # Precompiled regex patterns mapping terms to specific risk categories
    CATEGORY_PATTERNS: Dict[RiskCategory, List[re.Pattern]] = {
        RiskCategory.MISREPRESENTATION: [
            re.compile(r"\bmisrepresent(?:ation|ed|ing)?\b", re.IGNORECASE),
            re.compile(r"\bsection\s+40\b", re.IGNORECASE),
            re.compile(r"\b40\(1\)\(a\)\b", re.IGNORECASE),
            re.compile(r"\b5-?year\s+ban\b", re.IGNORECASE),
            re.compile(r"\bfake\s+(?:document|job\s+offer|bank\s+statement)\b", re.IGNORECASE),
            re.compile(r"\bfraudulent\b", re.IGNORECASE),
        ],
        RiskCategory.ENFORCEMENT: [
            re.compile(r"\bdeport(?:ation|ed)?\b", re.IGNORECASE),
            re.compile(r"\bremoval\s+order\b", re.IGNORECASE),
            re.compile(r"\bdeparture\s+order\b", re.IGNORECASE),
            re.compile(r"\bexclusion\s+order\b", re.IGNORECASE),
            re.compile(r"\bcbsa\s+(?:detention|arrest|investigation)\b", re.IGNORECASE),
        ],
        RiskCategory.LITIGATION_APPEAL: [
            re.compile(r"\bjudicial\s+review\b", re.IGNORECASE),
            re.compile(r"\bfederal\s+court\b", re.IGNORECASE),
            re.compile(r"\bimmigration\s+appeal\s+division\b", re.IGNORECASE),
            re.compile(r"\biad\s+appeal\b", re.IGNORECASE),
            re.compile(r"\bprocedural\s+fairness(?:\s+letter)?\b", re.IGNORECASE),
            re.compile(r"\bpfl\b", re.IGNORECASE),
            re.compile(r"\bappeal\s+a\s+(?:refusal|decision|rejection)\b", re.IGNORECASE),
        ],
        RiskCategory.INADMISSIBILITY: [
            re.compile(r"\binadmissib(?:le|ility)\b", re.IGNORECASE),
            re.compile(r"\bcriminal\s+inadmissibility\b", re.IGNORECASE),
            re.compile(r"\bmedical\s+inadmissibility\b", re.IGNORECASE),
            re.compile(r"\btemporary\s+resident\s+permit\b|\btrp\b", re.IGNORECASE),
            re.compile(r"\bcriminal\s+rehabilitation\b", re.IGNORECASE),
        ],
        RiskCategory.REFUSAL: [
            re.compile(r"\brefus(?:e|es|ed|ing|al|als)\b", re.IGNORECASE),
            re.compile(r"\breject(?:s|ed|ing|ion|ions)?\b", re.IGNORECASE),
            re.compile(r"\bdeni(?:ed|al|als|es)\b|\bdenying\b", re.IGNORECASE),
            re.compile(r"\bsection\s+216(?:[\(\s]*1[\)\s]*)?\b", re.IGNORECASE),
            re.compile(r"\bgcms\s+notes?\b", re.IGNORECASE),
            re.compile(r"\brefusal\s+letter\b", re.IGNORECASE),
            re.compile(r"\bvisa\s+denied\b", re.IGNORECASE),
        ],
    }

    def detect_risk(self, text: str) -> tuple[List[RiskCategory], List[str]]:
        """
        Scan text for high-risk categories and matched keyword tokens.
        Returns (categories, detected_terms).
        """
        if not text:
            return [], []

        matched_categories: Set[RiskCategory] = set()
        detected_terms: List[str] = []

        for category, patterns in self.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    matched_categories.add(category)
                    term = match.group(0)
                    if term.lower() not in [t.lower() for t in detected_terms]:
                        detected_terms.append(term)

        # Order categories by severity: Misrepresentation > Enforcement > Litigation > Inadmissibility > Refusal
        severity_order = [
            RiskCategory.MISREPRESENTATION,
            RiskCategory.ENFORCEMENT,
            RiskCategory.LITIGATION_APPEAL,
            RiskCategory.INADMISSIBILITY,
            RiskCategory.REFUSAL,
        ]
        sorted_categories = [cat for cat in severity_order if cat in matched_categories]
        return sorted_categories, detected_terms

    def get_contextual_disclaimer(self, categories: List[RiskCategory]) -> str:
        """Select highest-priority tailored legal disclaimer for the given risk categories."""
        if RiskCategory.MISREPRESENTATION in categories:
            return DISCLAIMER_MISREPRESENTATION
        if RiskCategory.ENFORCEMENT in categories or RiskCategory.LITIGATION_APPEAL in categories:
            return DISCLAIMER_INADMISSIBILITY_ENFORCEMENT
        if RiskCategory.INADMISSIBILITY in categories or RiskCategory.REFUSAL in categories:
            return DISCLAIMER_REFUSAL
        return DISCLAIMER_GENERAL

    def evaluate(self, query: str, response_text: str = "") -> DisclaimerEvaluationResult:
        """
        Evaluate user query and generated response text.
        Determines risk categories and attaches disclaimer if applicable.
        """
        combined = f"{query}\n{response_text}"
        categories, terms = self.detect_risk(combined)

        if not categories:
            return DisclaimerEvaluationResult(
                is_high_risk=False,
                risk_categories=[],
                detected_terms=[],
                disclaimer_text=None,
                annotated_text=response_text,
            )

        disclaimer = self.get_contextual_disclaimer(categories)

        # Prevent duplicate disclaimer if already present in response text
        has_existing_disclaimer = (
            "Important Legal Advisory" in response_text
            or "Critical Legal Warning" in response_text
            or "Urgent Legal Notice" in response_text
            or "Regulated Canadian Immigration Consultant (RCIC)" in response_text
        )

        annotated = response_text
        if not has_existing_disclaimer:
            annotated = response_text + disclaimer

        logger.info(
            f"[LEGAL_DISCLAIMER_ENGINE] High-risk scenario detected: {[c.value for c in categories]} "
            f"Terms: {terms}"
        )

        return DisclaimerEvaluationResult(
            is_high_risk=True,
            risk_categories=[c.value for c in categories],
            detected_terms=terms,
            disclaimer_text=disclaimer,
            annotated_text=annotated,
        )


# Global singleton instance
legal_disclaimer_engine = LegalDisclaimerEngine()
