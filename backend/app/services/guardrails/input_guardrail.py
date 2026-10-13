"""
Pre-LLM Input Guardrail.
Deterministic, multi-layered filter detecting:
1. Code generation & programming requests
2. Prompt injection & jailbreak attempts
3. Out-of-scope non-immigration inquiries
4. Multi-turn conversational drift
"""

import re
import unicodedata
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

    # Override verbs aimed at the assistant's own configuration. Strong targets ("instructions",
    # "guidelines", "system prompt") are injection-shaped with any filler; weak targets ("rules",
    # "restrictions") are common in real visa questions ("ignore the 20 hour rule?"), so they only
    # count when qualified as the assistant's own ("your rules", "the previous rules", "all rules").
    _OVERRIDE_VERBS = r"(?:ignore|disregard|forget|override|skip|drop|abandon|discard)"
    _STRONG_TARGETS = (
        r"(?:instructions?|prompts?|guidelines?|guardrails?|programming|system\s+prompt|"
        r"safety\s+(?:rules|filters?)|directives?)"
    )
    _WEAK_TARGETS = r"(?:rules?|directions?|restrictions?|policies|policy|constraints?|filters?)"
    _OWNERSHIP_QUALIFIERS = (
        r"(?:your|all|any|every|previous|prior|above|earlier|initial|original|preceding|"
        r"these|those|system|safety|built-in|default)"
    )

    # --- 1. PROMPT INJECTION & JAILBREAK PATTERNS ---
    INJECTION_PATTERNS = [
        # Override verb + up to 4 filler words ("the", "earlier", "all of your", ...) + strong target
        re.compile(rf"\b{_OVERRIDE_VERBS}\s+(?:[\w']+\s+){{0,4}}?{_STRONG_TARGETS}\b", re.IGNORECASE),
        # Override verb + qualifier marking it as the assistant's own + weak target
        re.compile(rf"\b{_OVERRIDE_VERBS}\s+(?:[\w']+\s+){{0,2}}?{_OWNERSHIP_QUALIFIERS}\s+(?:[\w']+\s+){{0,2}}?{_WEAK_TARGETS}\b", re.IGNORECASE),
        # Persona / role overrides
        re.compile(r"\byou\s+are\s+(?:now\s+)?(?:an?\s+|my\s+)?(?:pirate|unrestricted|unfiltered|uncensored|jailbroken|evil|different\s+(?:ai|assistant|bot)|dan)\b", re.IGNORECASE),
        re.compile(r"\byou\s+are\s+now\s+(?:an?|my)\s+\w+", re.IGNORECASE),
        re.compile(r"\b(?:respond|reply|answer|talk|speak|write)\s+(?:only\s+)?(?:as|like)\s+(?:an?\s+)?(?:pirate|unfiltered|unrestricted|evil|different)\b", re.IGNORECASE),
        re.compile(r"\b(?:pretend|imagine)\s+(?:that\s+)?(?:you\s+are|you're|to\s+be)\b", re.IGNORECASE),
        re.compile(r"\b(?:role-?play|roleplay)\s+as\b", re.IGNORECASE),
        re.compile(r"\bfrom\s+now\s+on,?\s+(?:you|answer|respond|reply|act|behave)\b", re.IGNORECASE),
        re.compile(r"\b(?:do\s+anything\s+now|developer\s+mode|jailbreak|jail-?broken)\b", re.IGNORECASE),
        # Prompt / configuration exfiltration
        re.compile(r"\b(?:tell|give|show|print|reveal|repeat|output|leak|share|display|dump|recite)\s+(?:me\s+)?(?:\w+\s+){0,3}?(?:system\s+prompt|hidden\s+(?:prompt|setup|instructions|text|context)|initial\s+(?:prompt|instructions)|setup\s+text|internal\s+(?:instructions|rules|configuration)|original\s+(?:prompt|instructions))\b", re.IGNORECASE),
        re.compile(r"\b(?:your|the)\s+(?:system\s+prompt|hidden\s+(?:prompt|setup|instructions)|instructions)\s+verbatim\b", re.IGNORECASE),
        re.compile(r"\bverbatim\b.{0,40}\b(?:prompt|instructions|setup)\b", re.IGNORECASE),
        # Common non-English override phrasings (es, fr, pt, de, it, hi-Latn, pa-Latn)
        re.compile(r"\bignora(?:r)?\s+(?:\w+\s+){0,3}?(?:instrucciones|reglas|indicaciones)\b", re.IGNORECASE),
        re.compile(r"\bignore[rz]?\s+(?:\w+\s+){0,3}?(?:consignes|instructions|règles)\b", re.IGNORECASE),
        re.compile(r"\bignor[ea]\s+(?:\w+\s+){0,3}?(?:instruções|instrucoes|regras|istruzioni|regole)\b", re.IGNORECASE),
        re.compile(r"\bignorier(?:e|en)?\s+(?:\w+\s+){0,3}?(?:anweisungen|regeln|vorgaben)\b", re.IGNORECASE),
        re.compile(r"\b(?:pichhle|pichle|purane|sabhi|saare)\s+(?:\w+\s+){0,2}?(?:nirdesh|niyam|instructions)\s+(?:ko\s+)?(?:bhool|ignore|nazarandaz)", re.IGNORECASE),
        re.compile(r"\byou\s+are\s+now\s+(an?\s+)?(unrestricted|different|dan|freed|unfiltered)", re.IGNORECASE),
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
        re.compile(r"\b(write|create|generate|provide|give|show)(\s+me)?\s+(a\s+|some\s+)?(python|javascript|typescript|java|c\+\+|c#|golang|rust|php|ruby|bash|shell|sql|html|css|nodejs|node\.js)\s+(code|script|function|program|snippet|app|class)?\b", re.IGNORECASE),
        re.compile(r"\b(write|create|generate|provide|give|show)(\s+me)?\s+(a\s+)?(script|function|algorithm|class|regex|dockerfile|makefile)\b", re.IGNORECASE),
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
        # Economic immigration programs & selection (previously missing: "How many points do I need on the
        # Federal Skilled Worker selection grid?" was refused as off-topic)
        "federal skilled worker", "federal skilled workers", "fsw", "fswp", "federal skilled trades", "fst",
        "skilled worker", "skilled workers", "skilled trades", "canadian experience class", "cec",
        "selection grid", "selection factors", "comprehensive ranking system", "crs score",
        "invitation to apply", "ita", "eca", "educational credential assessment", "settlement funds",
        "atlantic immigration program", "rural community immigration", "caregiver", "start-up visa",
        # Family, status & documents
        "sponsor", "sponsorship", "spousal sponsorship", "family sponsorship", "open work permit",
        "spousal open work permit", "sowp", "bowp", "eta", "trv", "copr", "pr card", "prtd",
        "biometric", "study visa", "temporary resident", "temporary residence", "refugee", "asylum",
        "ircc", "cic", "pr", "permanent residence", "permanent resident", "citizenship",
        "passport", "biometrics", "medical exam", "police clearance", "police certificate",
        "proof of funds", "funds", "bank statement", "gic", "tuition", "cad",
        "financial", "finances", "financial requirement", "financial requirements", "living expenses",
        "requirement", "requirements", "eligibility", "eligible", "qualify", "criteria",
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
        "off-campus", "on-campus", "work off-campus", "working hours", "master's", "masters",
    }

    # Precompile word-boundary patterns for whitelist keywords to prevent substring misclassifications
    VISA_WHITELIST_REGEXES = [
        re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in VISA_WHITELIST_KEYWORDS
    ]

    # --- 4a. HARMFUL / ILLEGAL REQUEST PATTERNS (deny regardless of visa keywords) ---
    # Patterns target *intent to do* the harmful thing, not the vocabulary: questions like
    # "is this a fake job offer?" or "what happens if I lie to an officer?" must stay answerable.
    _FRAUD_DOCS = (
        r"(?:bank\s+statements?|passports?|ielts|celpip|pte|toefl|(?:test\s+)?scores?|certificates?|"
        r"degrees?|diplomas?|transcripts?|marksheets?|documents?|loas?|letters?\s+of\s+acceptance|"
        r"job\s+offers?|lmias?|payslips?|pay\s+stubs?|employment\s+letters?|visas?|stamps?|"
        r"police\s+(?:certificates?|clearances?)|medical\s+(?:reports?|exams?)|proof\s+of\s+funds|"
        r"gic|sponsorship\s+letters?|invitation\s+letters?)"
    )
    _INTENT_LEAD = r"(?:how\s+(?:do|can|could|should)\s+i|how\s+to|help\s+me|can\s+you|i\s+(?:want|need)\s+to|best\s+way\s+to|teach\s+me\s+to)"

    HARMFUL_PATTERNS = [
        # Weapons, explosives, violence
        re.compile(r"\b(?:make|build|create|assemble|construct|manufacture)\s+(?:a\s+|an\s+|some\s+)?(?:bomb|explosives?|ied|grenade|molotov|detonator|pipe\s+bomb|nerve\s+agent|bioweapon|chemical\s+weapon|ghost\s+gun|silencer)\b", re.IGNORECASE),
        re.compile(r"\b(?:bomb|ied|grenade|molotov)s?\b.{0,40}\b(?:recipe|instructions|step[s-]?\s*by[s-]?\s*step)\b", re.IGNORECASE),
        re.compile(r"\b(?:how\s+(?:do|can)\s+i|how\s+to)\s+(?:kill|poison|hurt|kidnap|stab|shoot|strangle)\s+(?:a\s+|my\s+|some(?:one|body)|him|her|them|people|person|\w+'s)", re.IGNORECASE),
        # Drugs synthesis / trafficking
        re.compile(r"\b(?:synthesi[sz]e|cook|make|produce|smuggle|traffic)\s+(?:\w+\s+){0,2}?(?:meth|methamphetamine|cocaine|heroin|fentanyl|lsd|mdma)\b", re.IGNORECASE),
        # Self-harm methods
        re.compile(r"\b(?:how\s+to|ways\s+to|best\s+way\s+to)\s+(?:kill\s+myself|commit\s+suicide|end\s+my\s+life|self[-\s]?harm)\b", re.IGNORECASE),
        # Document fraud: fraud verbs used as actions on documents
        re.compile(rf"\b(?:forge|falsify|fabricate|photoshop|tamper\s+with|doctor\s+(?:my|the|a))\s+(?:\w+\s+){{0,3}}?{_FRAUD_DOCS}\b", re.IGNORECASE),
        # Document fraud: obtaining/creating fake documents
        re.compile(rf"\b(?:make|create|generate|produce|print|get|buy|purchase|order|need|want)\s+(?:me\s+)?(?:a\s+|an\s+|some\s+)?(?:fake|forged|false|fraudulent|counterfeit|bogus)\s+(?:\w+\s+){{0,2}}?{_FRAUD_DOCS}\b", re.IGNORECASE),
        re.compile(r"\b(?:where|how)\s+(?:can|do)\s+i\s+(?:buy|get|purchase|order)\s+(?:a\s+|an\s+)?(?:fake|forged|fraudulent|counterfeit)\b", re.IGNORECASE),
        # Marriage fraud: arranging it (not asking whether a genuine marriage looks suspicious)
        re.compile(r"\b(?:arrange|set\s+up|plan|organi[sz]e|enter\s+(?:into\s+)?|do|have|find\s+someone\s+for)\s+(?:a\s+)?(?:fake|sham|fraudulent|contract|paper)\s+marriage\b", re.IGNORECASE),
        # Deceiving officials / illegal entry: intent-led only
        re.compile(rf"\b{_INTENT_LEAD}\s+(?:\w+\s+){{0,2}}?(?:lie|lying|deceive|trick|fool|mislead|hide\s+\w+\s+from|conceal\s+\w+\s+from)\s+(?:\w+\s+){{0,3}}?(?:ircc|visa\s+officers?|officers?|immigration|cbsa|border)", re.IGNORECASE),
        re.compile(rf"\b{_INTENT_LEAD}\s+(?:\w+\s+){{0,2}}?(?:sneak|smuggle)\s+(?:\w+\s+){{0,3}}?(?:into|across|over)\b", re.IGNORECASE),
        re.compile(rf"\b{_INTENT_LEAD}\s+cross\s+(?:the\s+)?border\s+(?:illegally|without\s+(?:a\s+)?(?:visa|papers|documents|being\s+caught))", re.IGNORECASE),
        re.compile(r"\bwithout\s+getting\s+caught\b", re.IGNORECASE),
    ]

    # --- 4b. EXPLICIT OUT-OF-SCOPE PATTERNS ---
    OUT_OF_SCOPE_PATTERNS = [
        re.compile(r"\b(write|compose|generate|create|make)(\s+me)?\s+(a\s+|an\s+|some\s+)?(poem|poetry|song|lyrics|rap|story|short\s+story|novel|joke|riddle|haiku|limerick|essay\s+about\s+love)\b", re.IGNORECASE),
        re.compile(r"\btranslate\s+(?:this|the\s+following|my)\s+(?:poem|song|lyrics|story|joke)\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+is|what's)\s+the\s+capital\s+of\b", re.IGNORECASE),
        re.compile(r"\bwho\s+(?:is|was)\s+the\s+(?:president|prime\s+minister|king|queen|ceo)\s+of\s+(?!canada\b)", re.IGNORECASE),
        re.compile(r"\b(who\s+won|score\s+of|match\s+between)\s+(the\s+)?(cricket|football|nba|ipl|fifa|world\s+cup|match|game)\b", re.IGNORECASE),
        re.compile(r"\b(recipe\s+for|how\s+to\s+cook|ingredients\s+for|make\s+a\s+cake|bake)\b", re.IGNORECASE),
        re.compile(r"\b(weather\s+in|forecast\s+for|is\s+it\s+raining)\b", re.IGNORECASE),
        re.compile(r"\b(dating\s+advice|how\s+to\s+get\s+a\s+girlfriend|boyfriend|love\s+advice)\b", re.IGNORECASE),
        re.compile(r"\b(solve|calculate)\s+([0-9x\+\-\*\/\^\(\)\=\s]{5,})\b", re.IGNORECASE),
        re.compile(r"\b(how\s+to\s+hack|ddos|bypass\s+firewall|crack\s+password|exploit\s+vulnerability)\b", re.IGNORECASE),
        re.compile(r"\b(quantum\s+physics|theory\s+of\s+relativity|string\s+theory|astrophysics)\b", re.IGNORECASE),
        re.compile(r"\b(recommend\s+(a\s+)?movie|best\s+video\s+games|play\s+a\s+game)\b", re.IGNORECASE),
    ]

    @staticmethod
    def normalize_input(text: str) -> str:
        """
        Normalize input text via NFKC and strip zero-width and invisible control characters (R10).
        Defuses fullwidth evasions, homoglyphs, and zero-width delimiter breakouts.
        """
        if not text:
            return ""
        # 1. NFKC Unicode canonical decomposition & composition (e.g. fullwidth latin -> standard ascii)
        normalized = unicodedata.normalize("NFKC", text)
        # 2. Strip zero-width & invisible formatting characters:
        # \u200B (ZWSP), \u200C (ZWNJ), \u200D (ZWJ), \uFEFF (BOM), \u200E, \u200F (LTR/RTL marks), \u00AD (soft hyphen)
        normalized = re.sub(r"[\u200B-\u200D\u200E\u200F\uFEFF\u00AD]", "", normalized)
        # 3. Normalize whitespace
        return " ".join(normalized.split())

    def evaluate(self, query: str, chat_history: Optional[List[Dict[str, Any]]] = None) -> GuardrailResult:
        """
        Evaluate an incoming user query against all guardrails.
        Returns GuardrailResult indicating whether the query is permitted.
        """
        query_stripped = self.normalize_input(query)
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

        # 1b. Harmful / illegal request check (deny wins over any domain keyword)
        for pattern in self.HARMFUL_PATTERNS:
            if pattern.search(query_stripped):
                return GuardrailResult(
                    allowed=False,
                    violation=ViolationType.MALICIOUS_REQUEST,
                    refusal_message=REFUSAL_MESSAGES[ViolationType.MALICIOUS_REQUEST],
                    reason="Harmful or illegal request detected",
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
        Example: User asked about study permit, then asks "How much does it cost?", "What about my spouse?",
        or "What are the financial requirements for that?"
        """
        query_lower = query.lower()
        follow_up_cues = [
            "how much", "how long", "what about", "where do i", "can i", "is it required",
            "tell me more", "what next", "cost", "fee", "when", "why", "who", "documents",
            "proof", "family", "spouse", "children", "dependents", "timeline",
            "for that", "for this", "about that", "about this", "with that", "after that",
            "requirements", "requirement", "financial", "what are the", "what is the",
            "what do i need", "how do i apply", "is that possible", "can we do that",
            "explain that", "more details", "what else",
        ]
        has_follow_up_cue = any(cue in query_lower for cue in follow_up_cues)

        # Referential pronoun phrases (e.g. "for that", "for this", "about that", "after that")
        has_referential_pronoun = bool(re.search(r"\b(for that|for this|about that|about this|with that|after that|in that case|does that|is that)\b", query_lower))

        # If there's recent chat history, confirm recent turns were within visa domain
        if chat_history and len(chat_history) > 0:
            recent_contents = " ".join([m.get("content", "") for m in chat_history[-4:]])
            recent_is_visa = any(p.search(recent_contents) for p in self.VISA_WHITELIST_REGEXES)
            if recent_is_visa and (has_follow_up_cue or has_referential_pronoun):
                return True

        return has_follow_up_cue and bool(chat_history)


# Global singleton instance
input_guardrail = InputGuardrail()
