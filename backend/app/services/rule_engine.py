"""
Rule Engine service for deterministic visa answers.
Bypasses LLM for known, high-confidence policy data.
"""

from typing import Optional, Dict, Any

class RuleEngine:
    """Deterministic rule engine for visa answers."""
    
    def try_rule_answer(
        self, 
        intent: str, 
        country: str, 
        visa_type: str
    ) -> Optional[str]:
        """
        Check if a deterministic rule exists for the given combination.
        Returns the answer string if found, else None.
        """
        country = country.lower()
        visa_type = visa_type.lower()
        
        # Example: Canada Student Financial Requirements (Mandated in plan)
        if country == "canada" and visa_type == "student":
            if intent == "financial":
                return (
                    "**Canada Student Visa Financial Requirements (2025):**\n"
                    "- Minimum funds required: CAD 20,635 (for a single applicant outside Quebec).\n"
                    "- Proof of funds must cover tuition for the first year + living expenses.\n"
                    "- GIC (Guaranteed Investment Certificate) of CAD 20,635 is mandatory for SDS stream.\n"
                    "- Source: [IRCC Official]"
                )
            if intent == "checklist":
                return (
                    "**Canada Student Visa Document Checklist:**\n"
                    "- Letter of Acceptance (LOA) from a DLI.\n"
                    "- Valid Passport.\n"
                    "- Proof of Financial Support (GIC, Bank Statements).\n"
                    "- Statement of Purpose (SOP).\n"
                    "- Educational Documents (Transcripts, Certificates).\n"
                    "- Source: [IRCC Official]"
                )

        # Other countries commented out — Canada-only focus
        # # Example: UK Student Visa
        # if country == "uk" and visa_type == "student":
        #     if intent == "financial":
        #          return (
        #             "**UK Student Visa Financial Requirements:**\n"
        #             "- London: £1,334 per month (up to 9 months).\n"
        #             "- Outside London: £1,023 per month (up to 9 months).\n"
        #             "- Funds must be held for at least 28 consecutive days.\n"
        #             "- Source: [UKVI Official]"
        #         )
        
        return None

# Global instance
rule_engine = RuleEngine()
