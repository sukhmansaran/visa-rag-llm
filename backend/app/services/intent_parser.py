"""
Intent Parser service to normalize user queries into structured metadata.
Uses regex/keyword matching only — no LLM calls to conserve API quota.
"""

from typing import Dict, Any
import re


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
    
    async def parse_intent(self, query: str) -> Dict[str, Any]:
        """Extract intent, country, and visa type from the query using rules."""
        query_lower = query.lower()
        
        # Detect intent
        intent_map = {
            'financial': ['funds', 'money', 'bank', 'cost', 'fee', 'account', 'financial', 'tuition', 'scholarship'],
            'checklist': ['document', 'checklist', 'require', 'need', 'list', 'paperwork'],
            'timing': ['time', 'how long', 'duration', 'processing', 'deadline', 'when'],
            'eligibility': ['eligible', 'can i', 'qualify', 'gpa', 'score', 'ielts', 'toefl', 'gre'],
            'sop': ['sop', 'statement of purpose', 'essay', 'personal statement'],
            'admission': ['admission', 'apply', 'application', 'masters', 'bachelor', 'phd', 'program', 'course'],
        }
        
        detected_intent = "general"
        for intent, keywords in intent_map.items():
            if any(keyword in query_lower for keyword in keywords):
                detected_intent = intent
                break
        
        # Detect country
        detected_country = "unknown"
        for pattern, country in self.COUNTRY_MAP.items():
            if pattern in query_lower:
                detected_country = country
                break
        
        # Detect visa type
        visa_type = "unknown"
        if any(w in query_lower for w in ['student', 'study', 'university', 'college', 'masters', 'bachelor', 'phd', 'admission']):
            visa_type = "Student"
        elif any(w in query_lower for w in ['tourist', 'travel', 'visit', 'vacation', 'holiday', 'trip']):
            visa_type = "Tourist"
        elif any(w in query_lower for w in ['work', 'job', 'employment', 'h1b']):
            visa_type = "Work"
        
        # Detect university context for country inference
        if detected_country == "unknown":
            for uni in self.UNIVERSITY_KEYWORDS:
                if uni in query_lower:
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
