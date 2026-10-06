"""
SOP generation service using LLM and user profile.
"""

from typing import Optional, Dict, Any
from app.models.profile import Profile
from app.services.llm import llm_service  # Ollama-backed LLM service
from app.services.retrieval import retrieval_service


# SOP Templates by country/region — Canada-only focus (other countries commented out)
SOP_TEMPLATES = {
    # "US": {
    #     "max_words": 1000,
    #     "key_sections": [
    #         "Academic Background and Motivation",
    #         "Research/Professional Experience",
    #         "Why This Program and University",
    #         "Career Goals",
    #         "Conclusion"
    #     ],
    #     "tips": [
    #         "Focus on specific research interests and faculty",
    #         "Highlight unique experiences and perspectives",
    #         "Show clear connection between past and future goals",
    #         "Be specific about why this particular program"
    #     ]
    # },
    # "UK": {
    #     "max_words": 500,
    #     "key_sections": [
    #         "Academic Background",
    #         "Why This Course",
    #         "Career Aspirations",
    #         "Why This University"
    #     ],
    #     "tips": [
    #         "Be concise and direct",
    #         "Focus on academic achievements",
    #         "Explain course choice clearly",
    #         "Mention specific modules or faculty"
    #     ]
    # },
    "Canada": {
        "max_words": 1000,
        "key_sections": [
            "Introduction",
            "Academic Background",
            "Professional Experience",
            "Why Canada and This Program",
            "Future Plans"
        ],
        "tips": [
            "Explain why Canada specifically",
            "Show ties to home country",
            "Highlight relevant experience",
            "Demonstrate clear career path"
        ]
    },
    # "Australia": {
    #     "max_words": 600,
    #     "key_sections": [
    #         "Background and Motivation",
    #         "Academic Qualifications",
    #         "Why This Program",
    #         "Career Goals"
    #     ],
    #     "tips": [
    #         "Be straightforward and honest",
    #         "Focus on practical outcomes",
    #         "Explain program relevance",
    #         "Show commitment to studies"
    #     ]
    # },
    "default": {
        "max_words": 800,
        "key_sections": [
            "Introduction",
            "Academic Background",
            "Professional Experience",
            "Why This Program",
            "Career Goals",
            "Conclusion"
        ],
        "tips": [
            "Be authentic and personal",
            "Show passion for the field",
            "Connect past experiences to future goals",
            "Demonstrate fit with the program"
        ]
    }
}


async def generate_sop(
    profile: Profile,
    university: str,
    program: str,
    additional_info: Optional[str] = None,
) -> str:
    """
    Generate SOP draft using user profile and target program.
    
    Args:
        profile: User profile with education background
        university: Target university name
        program: Target program name
        additional_info: Optional additional information
        
    Returns:
        Generated SOP content
    """
    
    # Detect country from university name or use default
    country = _detect_country(university)
    template = SOP_TEMPLATES.get(country, SOP_TEMPLATES["default"])
    
    # Retrieve relevant context about the university and program
    context = await _retrieve_program_context(university, program)
    
    # Build comprehensive profile context
    profile_context = _build_profile_context(profile, university, program, additional_info)
    
    # Create SOP generation prompt
    system_prompt = _build_system_prompt(template)
    user_prompt = _build_user_prompt(profile_context, context, template, university, program)
    
    # Generate using Google Gemini
    # Note: local Ollama model — keep max_tokens reasonable to avoid slow responses
    sop_content = await llm_service.generate_answer(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context="",  # Context already in user_prompt
        temperature=0.7,  # More creative for SOP writing
        max_tokens=8000,  # High limit to account for thinking tokens in Gemini 2.5
    )
    
    return sop_content


def _detect_country(university: str) -> str:
    """Detect country from university name."""
    university_lower = university.lower()
    
    # Canada indicators
    if any(word in university_lower for word in ['toronto', 'mcgill', 'ubc', 'waterloo', 'alberta', 'montreal', 'queens', 'dalhousie', 'ottawa']):
        return "Canada"
    
    # Other countries commented out — Canada-only focus
    # # US indicators
    # if any(word in university_lower for word in ['mit', 'stanford', 'harvard', 'berkeley', 'ucla', 'nyu', 'columbia']):
    #     return "US"
    #
    # # UK indicators
    # if any(word in university_lower for word in ['oxford', 'cambridge', 'imperial', 'ucl', 'lse', 'edinburgh', 'manchester']):
    #     return "UK"
    #
    # # Australia indicators
    # if any(word in university_lower for word in ['melbourne', 'sydney', 'queensland', 'monash', 'unsw', 'anu']):
    #     return "Australia"
    
    return "default"


async def _retrieve_program_context(university: str, program: str) -> str:
    """Retrieve relevant information about the university and program from vector store."""
    try:
        query = f"{university} {program} admission requirements curriculum faculty research"
        chunks = await retrieval_service.retrieve(query=query, top_k=5)
        
        if chunks:
            context_parts = []
            for chunk in chunks[:3]:  # Use top 3 chunks
                text = chunk.get('text', '')
                url = chunk.get('metadata', {}).get('url', '')
                context_parts.append(f"- {text[:300]}... (Source: {url})")
            
            return "\n".join(context_parts)
        return ""
    except Exception as e:
        # If retrieval fails, continue without context (common if OpenAI key not configured)
        print(f"[SOP] Note: Could not retrieve program context (vector search disabled): {str(e)[:100]}")
        return ""


def _build_profile_context(
    profile: Profile,
    university: str,
    program: str,
    additional_info: Optional[str]
) -> Dict[str, Any]:
    """Build structured profile context."""
    return {
        "name": f"{profile.first_name or ''} {profile.last_name or ''}".strip() or "Applicant",
        "education_level": profile.education_level or "Not specified",
        "field_of_study": profile.field_of_study or "Not specified",
        "gpa": profile.gpa or "Not specified",
        "test_scores": _format_test_scores(profile.test_scores),
        "work_experience": f"{profile.work_experience or 0} years",
        "university": university,
        "program": program,
        "additional_info": additional_info or "None provided"
    }


def _build_system_prompt(template: Dict[str, Any]) -> str:
    """Build system prompt for SOP generation."""
    return f"""You are an expert Statement of Purpose writer with years of experience helping students gain admission to top universities worldwide.

Your task is to write a compelling, authentic, and well-structured SOP that:
1. Highlights the candidate's unique strengths and experiences
2. Demonstrates genuine passion and motivation
3. Shows clear fit with the target program
4. Follows best practices for SOP writing
5. Stays within {template['max_words']} words

Key principles:
- Be authentic and personal (avoid clichés)
- Use specific examples and achievements
- Show, don't just tell
- Connect past experiences to future goals
- Demonstrate research about the program
- Maintain professional yet engaging tone
- Use active voice and strong verbs

Structure the SOP with these sections:
{chr(10).join([f"- {section}" for section in template['key_sections']])}

Important tips for this region:
{chr(10).join([f"- {tip}" for tip in template['tips']])}"""


def _build_user_prompt(
    profile_context: Dict[str, Any],
    program_context: str,
    template: Dict[str, Any],
    university: str,
    program: str
) -> str:
    """Build user prompt with all context."""
    
    prompt = f"""Write a Statement of Purpose for the following candidate:

**Candidate Profile:**
- Name: {profile_context['name']}
- Current Education: {profile_context['education_level']} in {profile_context['field_of_study']}
- GPA: {profile_context['gpa']}
- Test Scores: {profile_context['test_scores']}
- Work Experience: {profile_context['work_experience']}

**Target Program:**
- University: {university}
- Program: {program}

**Additional Information:**
{profile_context['additional_info']}
"""

    if program_context:
        prompt += f"""
**Program Information (from research):**
{program_context}
"""

    prompt += f"""
**Requirements:**
- Maximum length: {template['max_words']} words
- Include all required sections
- Make it personal and compelling
- Use specific examples from the candidate's background
- Show genuine interest in the program
- Avoid generic statements

Generate the complete SOP now:"""

    return prompt


def _format_test_scores(test_scores: dict) -> str:
    """Format test scores for display."""
    if not test_scores:
        return "Not specified"
    
    formatted = []
    for test_name, scores in test_scores.items():
        if isinstance(scores, dict):
            score_str = ", ".join([f"{k.title()}: {v}" for k, v in scores.items()])
            formatted.append(f"{test_name.upper()}: {score_str}")
        else:
            formatted.append(f"{test_name.upper()}: {scores}")
    
    return " | ".join(formatted) if formatted else "Not specified"
