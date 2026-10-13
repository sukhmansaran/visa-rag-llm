"""
Intent Parser service to normalize user queries into structured metadata.
Uses regex/keyword matching only — no LLM calls to conserve API quota.
"""

from typing import Dict, Any
import re


def _has_term(text: str, term: str) -> bool:
    """Whole-word/phrase match (hyphens count as part of a word: "full-time" never matches "time")."""
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text) is not None


def _has_any(text: str, terms: list) -> bool:
    return any(_has_term(text, t) for t in terms)


class IntentParser:
    """Parses user queries into structured intents using rules only."""
    
    # Country detection patterns — Canada-only focus (other countries commented out)
    COUNTRY_MAP = {
        # 'usa': 'USA', 'us': 'USA', 'united states': 'USA', 'america': 'USA',
        # 'uk': 'UK', 'united kingdom': 'UK', 'britain': 'UK', 'england': 'UK',
        'canada': 'Canada', 'canadian': 'Canada',
        # 'australia': 'Australia', 'australian': 'Australia',
        # 'germany': 'Germany', 'german': 'Germany',
        # 'france': 'France', 'french': 'France',
        # 'japan': 'Japan', 'japanese': 'Japan',
        # 'netherlands': 'Netherlands', 'dutch': 'Netherlands',
        # 'new zealand': 'New Zealand',
        # 'ireland': 'Ireland', 'irish': 'Ireland',
        # 'singapore': 'Singapore',
        # 'south korea': 'South Korea', 'korea': 'South Korea',
        # 'thailand': 'Thailand', 'thai': 'Thailand',
        # 'india': 'India', 'indian': 'India',
        # 'china': 'China', 'chinese': 'China',
    }
    
    # University detection — Canada-focused (other countries' universities commented out)
    UNIVERSITY_KEYWORDS = [
        # 'mit', 'harvard', 'stanford', 'oxford', 'cambridge', 'caltech',
        # 'berkeley', 'yale', 'princeton', 'columbia',
        'toronto', 'mcgill',
        'ubc', 'waterloo', 'alberta', 'montreal', 'queens', 'dalhousie', 'ottawa',
        # 'melbourne', 'sydney', 'imperial', 'ucl', 'lse',
    ]
    
    # Intent keywords, matched as whole words/phrases (substring matching misfired on
    # "full-time" -> timing and "specialist" -> checklist). Order breaks ties.
    INTENT_KEYWORDS = {
        'financial': ['funds', 'money', 'bank', 'bank statement', 'cost', 'costs', 'fee', 'fees', 'account',
                      'financial', 'tuition', 'scholarship', 'scholarships', 'gic', 'proof of funds', 'afford'],
        'checklist': ['document', 'documents', 'checklist', 'require', 'required', 'requirements', 'paperwork',
                      'forms', 'what do i need', 'do i need'],
        'timing': ['how long', 'duration', 'processing time', 'processing times', 'deadline', 'deadlines',
                   'when', 'wait time', 'timeline', 'how soon'],
        'eligibility': ['eligible', 'eligibility', 'can i', 'qualify', 'gpa', 'score', 'scores', 'ielts',
                        'toefl', 'gre', 'celpip', 'pte', 'clb', 'crs'],
        'sop': ['sop', 'statement of purpose', 'essay', 'personal statement'],
        'admission': ['admission', 'admissions', 'apply', 'application', 'masters', "master's", 'bachelor',
                      "bachelor's", 'phd', 'program', 'programs', 'course', 'courses'],
    }
    _INTENT_REGEXES = {
        intent: [re.compile(rf"(?<![\w-]){re.escape(kw)}(?![\w-])") for kw in keywords]
        for intent, keywords in INTENT_KEYWORDS.items()
    }

    async def parse_intent(self, query: str) -> Dict[str, Any]:
        """Extract intent, country, and visa type from the query using rules."""
        query_lower = query.lower()

        # Detect intent: the intent with the most whole-word hits wins; ties keep declaration order
        detected_intent = "general"
        best_hits = 0
        for intent, patterns in self._INTENT_REGEXES.items():
            hits = sum(1 for pattern in patterns if pattern.search(query_lower))
            if hits > best_hits:
                detected_intent, best_hits = intent, hits
        
        # Detect country
        detected_country = "unknown"
        for pattern, country in self.COUNTRY_MAP.items():
            if _has_term(query_lower, pattern):
                detected_country = country
                break
        
        # Detect visa type
        visa_type = "unknown"
        if _has_any(query_lower, ['express entry', 'permanent residence', 'permanent resident', 'permanent residency', 'pr', 'pr card', 'fsw', 'cec', 'pnp', 'provincial nominee']):
            visa_type = "Express Entry"
            detected_country = "Canada"  # Express Entry & PNP are uniquely Canadian immigration programs
        elif _has_any(query_lower, ['student', 'students', 'study', 'studying', 'study permit', 'university', 'college', 'masters', "master's", 'bachelor', "bachelor's", 'phd', 'admission', 'dli']):
            visa_type = "Student"
        elif _has_any(query_lower, ['tourist', 'travel', 'visit', 'visitor', 'visiting', 'vacation', 'holiday', 'trip', 'super visa']):
            visa_type = "Tourist"
        elif _has_any(query_lower, ['work', 'working', 'job', 'employment', 'lmia', 'work permit', 'pgwp', 'software engineer', 'developer']):
            visa_type = "Work"
        
        # Detect university context for country inference
        if detected_country == "unknown":
            for uni in self.UNIVERSITY_KEYWORDS:
                if _has_term(query_lower, uni):
                    # Canada universities
                    if uni in ['toronto', 'mcgill', 'ubc', 'waterloo', 'alberta', 'montreal', 'queens', 'dalhousie', 'ottawa']:
                        detected_country = "Canada"
                    # Other countries commented out — Canada-only focus
                    # elif uni in ['mit', 'harvard', 'stanford', 'berkeley', 'yale', 'princeton', 'columbia', 'caltech']:
                    #     detected_country = "USA"
                    # elif uni in ['oxford', 'cambridge', 'imperial', 'ucl', 'lse']:
                    #     detected_country = "UK"
                    # elif uni in ['melbourne', 'sydney']:
                    #     detected_country = "Australia"
                    break
        
        return {
            "country": detected_country,
            "visa_type": visa_type,
            "intent": detected_intent,
        }


# Global instance
intent_parser = IntentParser()
