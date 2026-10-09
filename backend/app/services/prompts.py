"""
Prompt templates for LLM answer generation.
"""

from typing import Dict, Any


# Base system prompt
SYSTEM_PROMPT = """You are an expert immigration and university application advisor. Your role is to provide accurate, helpful information about visa requirements, university applications, and study abroad processes.

CRITICAL RULES:
1. ALWAYS cite your sources using [Source N] references
2. ONLY use information from the provided context
3. If the context doesn't contain enough information, say so explicitly
4. Never make up facts or requirements
5. Always recommend consulting official sources for final decisions
6. Include the disclaimer about consulting official authorities

When citing:
- Use [Source 1], [Source 2], etc. to reference specific information
- Each factual claim must have at least one citation
- Provide the source URL and retrieval date for transparency"""


# General Q&A prompt
QA_PROMPT = """Context:
{context}

User Question: {query}

Provide a comprehensive answer based ONLY on the context above. Structure your response as follows:

1. Direct answer to the question
2. Supporting details with citations [Source N]
3. Important notes or caveats
4. Recommendation to verify with official sources

Remember to cite every factual claim using [Source N] format.

IMPORTANT: Add this disclaimer at the end:
"⚠️ This information is for guidance only. Always verify with official embassy websites or authorized immigration consultants for the most current requirements."

Answer:"""


# Visa-specific prompt
VISA_PROMPT = """Context:
{context}

User Question (Visa-related): {query}

Provide detailed visa guidance based on the context. Include:

1. **Visa Type**: Which visa applies
2. **Eligibility**: Who can apply
3. **Required Documents**: Complete list with citations [Source N]
4. **Process**: Step-by-step application process
5. **Timeline**: Processing times if available
6. **Fees**: Application costs if mentioned
7. **Important Notes**: Any critical requirements or recent changes

Cite each requirement using [Source N] format.

Disclaimer:
"⚠️ Visa requirements change frequently. Always verify with the official embassy website or authorized immigration consultant. This information was retrieved on {retrieval_date}."

Answer:"""


# University selection prompt
UNIVERSITY_PROMPT = """Context:
{context}

User Profile:
{user_profile}

User Question: {query}

Based on the context and user profile, provide university guidance including:

1. **Recommended Universities**: Match user's profile with options
2. **Admission Requirements**: GPA, test scores, prerequisites [Source N]
3. **Application Process**: Steps and deadlines
4. **Costs**: Tuition and living expenses if available
5. **Scholarship Opportunities**: If mentioned in context

Cite all facts using [Source N] format.

Disclaimer:
"⚠️ University requirements vary and change. Always verify with the official university website or admissions office."

Answer:"""


# Document checklist prompt
CHECKLIST_PROMPT = """Context:
{context}

User Question: {query}
Application Type: {application_type}

Create a comprehensive checklist of required documents based on the context:

**Required Documents:**
- [ ] Document 1 [Source N]
- [ ] Document 2 [Source N]
...

**Additional Recommendations:**
- Suggested but not mandatory documents

**Important Notes:**
- Any specific formatting or authentication requirements
- Submission deadlines if mentioned

Every item must have a citation [Source N].

Disclaimer:
"⚠️ Document requirements may vary. Confirm with the official institution before submitting."

Answer:"""


# SOP guidance prompt (for chat-based SOP advice)
SOP_GUIDANCE_PROMPT = """Context:
{context}

User Profile:
{user_profile}

User Question: {query}

Provide comprehensive SOP writing guidance based on the context and profile. Include:

1. **Structure**: Recommended sections for their target country/university
2. **Key Points to Address**: Based on visa/university requirements [Source N]
3. **Content Suggestions**: What to emphasize given their background
4. **Do's and Don'ts**: Best practices from official sources
5. **Length and Format**: Word limits and formatting requirements
6. **Common Mistakes**: What to avoid

Cite all requirements and recommendations using [Source N] format.

Disclaimer:
"⚠️ SOP requirements vary by institution. Always check the specific university's application guidelines."

Answer:"""

SOP_PROMPT = SOP_GUIDANCE_PROMPT


# SOP review prompt (for providing feedback on existing SOPs)
SOP_REVIEW_PROMPT = """You are an expert SOP reviewer with experience in university admissions.

Review the following Statement of Purpose and provide detailed feedback:

**SOP Content:**
{sop_content}

**Target Program:**
- University: {university}
- Program: {program}

**Evaluation Criteria:**
1. **Structure & Organization** (1-10)
2. **Content Quality** (1-10)
3. **Authenticity & Voice** (1-10)
4. **Clarity & Grammar** (1-10)
5. **Fit with Program** (1-10)

Provide:
1. Overall score and summary
2. Strengths (what works well)
3. Areas for improvement (specific suggestions)
4. Line-by-line feedback on key sections
5. Recommended revisions

Be constructive, specific, and actionable in your feedback."""


def get_prompt_template(query_type: str = "general") -> str:
    """
    Get the appropriate prompt template.
    
    Args:
        query_type: Type of query (general, visa, university, checklist, sop)
        
    Returns:
        Prompt template string
    """
    templates = {
        "general": QA_PROMPT,
        "visa": VISA_PROMPT,
        "university": UNIVERSITY_PROMPT,
        "checklist": CHECKLIST_PROMPT,
        "sop": SOP_PROMPT,
    }
    
    return templates.get(query_type, QA_PROMPT)


def build_prompt(
    query: str,
    context: str,
    query_type: str = "general",
    user_profile: Dict[str, Any] = None,
    **kwargs
) -> str:
    """
    Build a complete prompt from template.
    
    Args:
        query: User query
        context: Retrieved context
        query_type: Type of query
        user_profile: Optional user profile dict
        **kwargs: Additional template variables
        
    Returns:
        Formatted prompt string
    """
    template = get_prompt_template(query_type)
    
    # Get latest retrieval date from context
    import re
    dates = re.findall(r'Retrieved: ([^\)]+)', context)
    retrieval_date = dates[0] if dates else "recently"
    
    # Format user profile if provided
    profile_str = ""
    if user_profile:
        profile_str = "\n".join([f"- {k}: {v}" for k, v in user_profile.items()])
    
    # Safely resolve application_type (explicit kwargs > user_profile > fallback)
    format_kwargs = kwargs.copy()
    app_type = format_kwargs.pop('application_type', None)
    if not app_type and user_profile:
        app_type = user_profile.get('application_type') or user_profile.get('target_degree')
    if not app_type:
        app_type = 'N/A'
    
    return template.format(
        query=query,
        context=context,
        user_profile=profile_str,
        retrieval_date=retrieval_date,
        application_type=app_type,
        **format_kwargs
    )
