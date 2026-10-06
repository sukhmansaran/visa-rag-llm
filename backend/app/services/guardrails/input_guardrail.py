"""
Pre-LLM Input Guardrail.
Deterministic, multi-layered filter detecting:
1. Code generation & programming requests
2. Prompt injection & jailbreak attempts
3. Out-of-scope non-immigration inquiries
4. Multi-turn conversational drift
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from app.core.visa_constitution import ViolationType, REFUSAL_MESSAGES


@dataclass
class GuardrailResult:
    """Result returned by the input guardrail evaluation."""
    allowed: bool
    violation: Optional[ViolationType] = None
    refusal_message: Optional[str] = None
    reason: Optional[str] = None
    intent: Optional[str] = None


class InputGuardrail:
    """
    Deterministic input guardrail protecting the Visa RAG LLM.
    Zero LLM overhead: executes purely via compiled patterns and heuristics.
    """

    # --- 1. PROMPT INJECTION & JAILBREAK PATTERNS ---
    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?(your\s+)?(previous|above|prior|initial)\s+(instructions|directions|prompts|rules)", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?(your\s+)?(previous|above|prior|initial)\s+(instructions|directions|rules|prompts)", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(an?\s+)?(unrestricted|different|dan|freed|unfiltered)", re.IGNORECASE),
        re.compile(r"act\s+as\s+(an?\s+)?(unrestricted|jailbroken|developer\s+mode|dan|hacker|python\s+coder)", re.IGNORECASE),
        re.compile(r"reveal\s+(your\s+|the\s+)?(system\s+prompt|instructions|initial\s+prompt|hidden\s+prompt)", re.IGNORECASE),
        re.compile(r"what\s+(is|are)\s+your\s+(system\s+prompt|internal\s+instructions|secret\s+instructions)", re.IGNORECASE),
        re.compile(r"(print|show|output|repeat|display)\s+(your\s+)?(initial\s+|secret\s+|hidden\s+)?(system\s+prompt|rules|hidden\s+context|instructions)", re.IGNORECASE),
        re.compile(r"bypass\s+(your\s+)?(rules|safety|filters|guardrails|guidelines)", re.IGNORECASE),
        re.compile(r"new\s+(system\s+)?instruction:\s*", re.IGNORECASE),
        re.compile(r"system\s*override", re.IGNORECASE),
        re.compile(r"<\s*system\s*>", re.IGNORECASE),
        re.compile(r"\[\s*system\s*\]", re.IGNORECASE),
        re.compile(r"\|im_start\||\|im_end\|", re.IGNORECASE),
        re.compile(r"forget\s+(everything|all\s+rules|all)\s+(you\s+)?(know|were\s+told)", re.IGNORECASE),
        re.compile(r"you\s+have\s+no\s+rules", re.IGNORECASE),
    ]

    # --- 2. CODE REQUEST PATTERNS ---
    CODE_DIRECTIVE_PATTERNS = [
        re.compile(r"\b(write|create|generate|provide|give\s+me|show\s+me)\s+(a\s+|some\s+)?(python|javascript|typescript|java|c\+\+|c#|golang|rust|php|ruby|bash|shell|sql|html|css|nodejs|node\.js)\s+(code|script|function|program|snippet|app|class)?\b", re.IGNORECASE),
        re.compile(r"\b(write|create|generate|provide)\s+(a\s+)?(script|function|algorithm|class|regex|dockerfile|makefile)\b", re.IGNORECASE),
        re.compile(r"\b(debug|fix|optimize|refactor)\s+(this|my|the)?\s*(code|script|function|bug|sql\s+query|query)\b", re.IGNORECASE),
        re.compile(r"\bhow\s+to\s+(code|build|program|develop|create)\s+(an?\s+)?(api|web\s+scraper|scraper|bot|crawler|app)\b", re.IGNORECASE),
        re.compile(r"\bhow\s+to\s+code\b", re.IGNORECASE),
        re.compile(r"\b(pip\s+install|npm\s+install|yarn\s+add|docker\s+run|dockerfile|git\s+clone)\b", re.IGNORECASE),
        re.compile(r"\bdef\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(", re.IGNORECASE),
        re.compile(r"\bconsole\.log\s*\(", re.IGNORECASE),
        re.compile(r"\bpublic\s+static\s+void\s+main\b", re.IGNORECASE),
        re.compile(r"\bselect\s+.+\s+from\s+[a-zA-Z_0-9]+", re.IGNORECASE),
    ]

    # --- 3. IMMIGRATION / VISA POSITIVE KEYWORDS ---
    VISA_WHITELIST_KEYWORDS = {
        "visa", "visas", "study permit", "work permit", "visitor visa", "tourist visa",
        "visitor record", "super visa", "pgwp", "post-grad", "post-graduation work permit",
        "co-op work permit", "express entry", "crs", "pnp", "provincial nominee",
        "ircc", "cic", "pr", "permanent residence", "permanent resident", "citizenship",
        "passport", "biometrics", "medical exam", "police clearance", "police certificate",
        "proof of funds", "funds", "bank statement", "gic", "tuition", "cad",
        "dli", "designated learning institution", "loa", "letter of acceptance",
        "pal", "tal", "attestation letter", "caq", "quebec", "ontario", "bc", "alberta",
        "ielts", "celpip", "toefl", "pte", "clb", "language score", "language test",
        "noc", "noc code", "teer", "job offer", "lmia", "sop", "statement of purpose",
        "letter of explanation", "intent letter", "refusal", "rejection", "refused",
        "inadmissible", "misrepresentation", "section 40", "section 216", "gcms", "gcms notes",
        "processing time", "processing fee", "imm 5707", "imm 1294", "imm 5257",
        "gckey", "portal", "vfs", "travel", "flight", "destination", "itinerary",
        "hotel", "trip", "vacation", "toronto", "vancouver", "montreal", "ottawa",
        "calgary", "edmonton", "waterloo", "mcgill", "ubc",
        "canada", "canadian", "immigration", "immigrate", "immigrant", "student visa",
    }

    # Precompile word-boundary patterns for whitelist keywords to prevent substring misclassifications
    VISA_WHITELIST_REGEXES = [
        re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in VISA_WHITELIST_KEYWORDS
    ]

    # --- 4. EXPLICIT OUT-OF-SCOPE PATTERNS ---
    OUT_OF_SCOPE_PATTERNS = [
        re.compile(r"\b(write|compose|generate)\s+(a\s+)?(poem|song|rap|story|novel|joke|riddle|essay\s+about\s+love)\b", re.IGNORECASE),
        re.compile(r"\b(who\s+won|score\s+of|match\s+between)\s+(the\s+)?(cricket|football|nba|ipl|fifa|world\s+cup|match|game)\b", re.IGNORECASE),
        re.compile(r"\b(recipe\s+for|how\s+to\s+cook|ingredients\s+for|make\s+a\s+cake|bake)\b", re.IGNORECASE),
        re.compile(r"\b(weather\s+in|forecast\s+for|is\s+it\s+raining)\b", re.IGNORECASE),
        re.compile(r"\b(dating\s+advice|how\s+to\s+get\s+a\s+girlfriend|boyfriend|love\s+advice)\b", re.IGNORECASE),
        re.compile(r"\b(solve|calculate)\s+([0-9x\+\-\*\/\^\(\)\=\s]{5,})\b", re.IGNORECASE),
        re.compile(r"\b(how\s+to\s+hack|ddos|bypass\s+firewall|crack\s+password|exploit\s+vulnerability)\b", re.IGNORECASE),
        re.compile(r"\b(quantum\s+physics|theory\s+of\s+relativity|string\s+theory|astrophysics)\b", re.IGNORECASE),
        re.compile(r"\b(recommend\s+(a\s+)?movie|best\s+video\s+games|play\s+a\s+game)\b", re.IGNORECASE),
    ]

    def evaluate(self, query: str, chat_history: Optional[List[Dict[str, Any]]] = None) -> GuardrailResult:
        """
        Evaluate an incoming user query against all guardrails.
        Returns GuardrailResult indicating whether the query is permitted.
        """
        query_stripped = query.strip()
        if not query_stripped:
            return GuardrailResult(
                allowed=False,
                violation=ViolationType.OUT_OF_SCOPE,
                refusal_message=REFUSAL_MESSAGES[ViolationType.OUT_OF_SCOPE],
                reason="Empty query",
            )

        # 1. Prompt Injection & Jailbreak Check (Highest priority)
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(query_stripped):
                return GuardrailResult(
                    allowed=False,
                    violation=ViolationType.PROMPT_INJECTION,
                    refusal_message=REFUSAL_MESSAGES[ViolationType.PROMPT_INJECTION],
                    reason=f"Matched prompt injection pattern: {pattern.pattern}",
                )

        # 2. Code Request Check
        for pattern in self.CODE_DIRECTIVE_PATTERNS:
            if pattern.search(query_stripped):
                # Ensure it's not a legitimate immigration eligibility question with IT keywords
                if not self._is_it_professional_visa_inquiry(query_stripped):
                    return GuardrailResult(
                        allowed=False,
                        violation=ViolationType.CODE_REQUEST,
                        refusal_message=REFUSAL_MESSAGES[ViolationType.CODE_REQUEST],
                        reason="Programming or code generation request detected",
                    )

        # 3. Explicit Out-of-Scope Patterns Check
        for pattern in self.OUT_OF_SCOPE_PATTERNS:
            if pattern.search(query_stripped):
                return GuardrailResult(
                    allowed=False,
                    violation=ViolationType.OUT_OF_SCOPE,
                    refusal_message=REFUSAL_MESSAGES[ViolationType.OUT_OF_SCOPE],
                    reason=f"Matched out-of-scope pattern: {pattern.pattern}",
                )

        # 4. Scope Whitelist & Domain Relevance Check (Whole word matching)
        has_visa_keyword = any(p.search(query_stripped) for p in self.VISA_WHITELIST_REGEXES)

        # If no explicit visa keyword is present, evaluate whether it's a valid conversational follow-up
        if not has_visa_keyword:
            if not self._is_valid_contextual_follow_up(query_stripped, chat_history):
                return GuardrailResult(
                    allowed=False,
                    violation=ViolationType.OUT_OF_SCOPE,
                    refusal_message=REFUSAL_MESSAGES[ViolationType.OUT_OF_SCOPE],
                    reason="Query lacks immigration, visa, study, or travel relevance",
                )

        # Query passed all guardrail checks
        return GuardrailResult(
            allowed=True,
            violation=None,
            refusal_message=None,
            reason="Query validated as within immigration/visa domain",
        )

    def _is_it_professional_visa_inquiry(self, query: str) -> bool:
        """
        Distinguish immigration profile questions from actual coding requests.
        Example: "I am a Python developer with 3 years experience, am I eligible for Express Entry?"
        vs "Write a Python script to fetch visa data."
        """
        query_lower = query.lower()

        # Direct code syntax is NEVER an immigration profile question
        if re.search(r"(\bdef\s+[a-zA-Z_]\w*\s*\(|console\.log|public\s+static|select\s+.+\s+from)", query_lower):
            return False

        # Imperative coding commands
        coding_command_patterns = [
            r"\b(write|create|generate|provide|give\s+me|show\s+me|debug|fix|refactor|optimize)\b.*\b(code|script|dockerfile|api|function|snippet|app|program)\b",
            r"\b(dockerfile|pip\s+install|npm\s+install|yarn\s+add|docker\s+run)\b",
            r"\b(how\s+to\s+code)\b",
        ]
        if any(re.search(p, query_lower) for p in coding_command_patterns):
            return False

        # Legitimate immigration eligibility intent
        eligibility_patterns = [
            r"\b(eligible|eligibility|qualify)\b",
            r"\b(express entry|crs score|pnp|provincial nominee|work permit)\b",
            r"\bam i eligible\b",
        ]
        return any(re.search(p, query_lower) for p in eligibility_patterns)

    def _is_valid_contextual_follow_up(self, query: str, chat_history: Optional[List[Dict[str, Any]]]) -> bool:
        """
        Checks if a brief query is a valid follow-up to an existing visa conversation.
        Example: User asked about study permit, then asks "How much does it cost?" or "What about my spouse?"
        """
        query_lower = query.lower()
        follow_up_cues = [
            "how much", "how long", "what about", "where do i", "can i", "is it required",
            "tell me more", "what next", "cost", "fee", "when", "why", "who", "documents",
            "proof", "family", "spouse", "children", "dependents", "timeline",
        ]
        has_follow_up_cue = any(cue in query_lower for cue in follow_up_cues)

        if not has_follow_up_cue:
            return False

        # If there's recent chat history, confirm recent turns were within visa domain
        if chat_history and len(chat_history) > 0:
            recent_contents = " ".join([m.get("content", "") for m in chat_history[-3:]])
            return any(p.search(recent_contents) for p in self.VISA_WHITELIST_REGEXES)

        return False


# Global singleton instance
input_guardrail = InputGuardrail()
