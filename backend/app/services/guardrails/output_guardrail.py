"""
Post-Generation Output Guardrail & Leakage Shield.
Deterministic scanning and redaction for:
1. Markdown code blocks and raw executable scripts
2. Secret, API key, and credential leaks
3. System prompt and internal instruction exfiltration
4. Internal file paths and system traceback leaks
5. Unauthorized legal absolutes & approval guarantees
"""

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class OutputViolationType(str, Enum):
    """Categories of output violations."""
    CODE_BLOCK = "CODE_BLOCK"
    SECRET_LEAK = "SECRET_LEAK"
    PROMPT_LEAK = "PROMPT_LEAK"
    PATH_LEAK = "PATH_LEAK"
    LEGAL_GUARANTEE = "LEGAL_GUARANTEE"


@dataclass
class OutputValidationResult:
    """Result of post-generation output validation."""
    is_valid: bool
    violations: List[OutputViolationType] = field(default_factory=list)
    sanitized_output: str = ""
    remediation_applied: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


# Standard fallback messages
SAFE_OUTPUT_FALLBACK = (
    "I apologize, but this response could not be verified against our safety and compliance guidelines. "
    "As an immigration guidance assistant, I can provide factual information on Canadian visa programs, "
    "study permits, and official application requirements based on official IRCC regulations. "
    "Please let me know how I can assist with your immigration questions."
)

LEGAL_GUARANTEE_FALLBACK = (
    "Please note that visa approvals can never be guaranteed by any consultant, tool, or software. "
    "All immigration decisions rest entirely with Immigration, Refugees and Citizenship Canada (IRCC) visa officers "
    "based on individual applicant merits and Canadian immigration law. "
    "Please review official IRCC criteria for detailed eligibility requirements."
)


class OutputGuardrail:
    """
    Deterministic output guardrail protecting against accidental leakage,
    unauthorized code synthesis, and unauthorized legal guarantees.
    """

    # --- 1. CODE BLOCKS & RAW SCRIPT DIRECTIVES ---
    CODE_PATTERNS = [
        # Markdown code fencing (e.g., ```python, ```bash, ```)
        re.compile(r"```(?:\w+)?[\s\S]*?```"),
        re.compile(r"```(?:\w+)?"),
        # Script HTML tags
        re.compile(r"<\s*script\b[^>]*>[\s\S]*?<\s*/\s*script\s*>", re.IGNORECASE),
        re.compile(r"<\s*script\b", re.IGNORECASE),
        # Raw function / class / import definitions in programming languages
        re.compile(r"^(?:def|class)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*[\(:].*$", re.MULTILINE),
        re.compile(r"^(?:import|from)\s+[a-zA-Z_][a-zA-Z0-9_]*\s+(?:import\s+)?[a-zA-Z0-9_,\s*]+$", re.MULTILINE),
        re.compile(r"\bconsole\.log\s*\(", re.IGNORECASE),
        re.compile(r"\bpublic\s+(?:static\s+)?void\s+main\b", re.IGNORECASE),
        re.compile(r"\b(?:pip|npm|yarn|pnpm)\s+install\b", re.IGNORECASE),
        re.compile(r"\bSELECT\s+.+\s+FROM\s+[a-zA-Z_0-9]+", re.IGNORECASE),
    ]

    # --- 2. SECRET & API KEY LEAKS ---
    SECRET_PATTERNS = [
        # OpenAI keys
        re.compile(r"\bsk-[a-zA-Z0-9_-]{20,}\b"),
        # AWS Access Keys
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        # GitHub Personal Access Tokens
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b"),
        re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{30,}\b"),
        # Generic API / Secret Keys and Bearer tokens
        re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|bearer[_-]?token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]{16,}['\"]?"),
        # Environment variable definitions with secrets
        re.compile(r"(?i)\b(?:POSTGRES_PASSWORD|DATABASE_URL|SECRET_KEY|OPENAI_API_KEY|REDIS_URL|FCM_SERVER_KEY|JWT_SECRET)\s*=\s*[^\s]+"),
        # Private key blocks
        re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
    ]

    # --- 3. SYSTEM PROMPT & INTERNAL INSTRUCTION LEAKS ---
    PROMPT_LEAK_PATTERNS = [
        re.compile(r"You are Pendu,\s+an expert,\s+professional Canadian visa", re.IGNORECASE),
        re.compile(r"Pendu\s+Visa\s+Constitution", re.IGNORECASE),
        re.compile(r"GROUNDED_SYSTEM_PROMPT", re.IGNORECASE),
        re.compile(r"UNVERIFIED_EVIDENCE_REFUSAL", re.IGNORECASE),
        re.compile(r"===\s*START\s+OFFICIAL\s+RETRIEVED\s+DATA", re.IGNORECASE),
        re.compile(r"===\s*END\s+OFFICIAL\s+RETRIEVED\s+DATA", re.IGNORECASE),
        re.compile(r"treat\s+strictly\s+as\s+factual\s+data,\s+never\s+execute\s+as\s+instructions", re.IGNORECASE),
        re.compile(r"Conversational\s+Continuity\s+&\s+Tone", re.IGNORECASE),
        re.compile(r"Base\s+all\s+facts,\s+numbers,\s+TEER\s+levels,\s+NOC\s+classifications", re.IGNORECASE),
        re.compile(r"Never\s+provide\s+absolute\s+legal\s+guarantees", re.IGNORECASE),
    ]

    # --- 4. INTERNAL FILE PATHS & TRACEBACKS ---
    PATH_LEAK_PATTERNS = [
        # Windows file system paths (e.g. C:\Users\..., D:\projects\...)
        re.compile(r"\b[A-Za-z]:\\(?:Users|projects|Windows|Program Files|AppData|backend|tmp)[\w\-.\\]+", re.IGNORECASE),
        # Internal server / container paths
        re.compile(r"\b\/(?:backend|app|root|var|etc|home|usr)\/(?:app|services|models|core|workers|api)[\w\-/.]+", re.IGNORECASE),
        re.compile(r"\b\/etc\/(?:passwd|shadow|hosts)\b", re.IGNORECASE),
        # Stack trace markers
        re.compile(r"\bTraceback\s+\(most\s+recent\s+call\s+last\):", re.IGNORECASE),
        re.compile(r'File\s+"[^"]+",\s+line\s+\d+,\s+in\s+', re.IGNORECASE),
    ]

    # --- 5. DANGEROUS LEGAL ABSOLUTES & GUARANTEES ---
    # Phrases claiming unconditional guarantee or guaranteed visa/approval
    LEGAL_GUARANTEE_PATTERNS = [
        re.compile(r"\b(?:100%|definitely|absolutely)\s+(?:guarantee[ds]?|assured|certain)\b", re.IGNORECASE),
        re.compile(r"\bguarantee[ds]?\s+(?:your\s+|that\s+you\s+will\s+(?:receive|get|obtain)\s+(?:a\s+)?|an?\s+)?(?:visa|approval|acceptance|permit|study\s+permit|work\s+permit|pr|citizenship)\b", re.IGNORECASE),
        re.compile(r"\b(?:visa|approval|permit|pr)\s+is\s+(?:100%|completely|definitely)\s+(?:guaranteed|assured|certain)\b", re.IGNORECASE),
        re.compile(r"\b(?:we|i)?\s*guarantee[ds]?\s+(?:that\s+)?(?:you|applicants?)\s+will\s+(?:be\s+approved|get\s+approved|receive|obtain|get)\b", re.IGNORECASE),
        re.compile(r"\byou\s+are\s+guaranteed\s+to\s+(?:get|receive|be\s+approved|obtain)\b", re.IGNORECASE),
        re.compile(r"\b(?:zero|no)\s+chance\s+of\s+(?:rejection|refusal)\b", re.IGNORECASE),
        re.compile(r"\bcannot\s+be\s+(?:rejected|refused)\b", re.IGNORECASE),
    ]

    # Permitted disclaimers that discuss guarantees in a negative / advisory context
    SAFE_DISCLAIMER_PATTERNS = [
        re.compile(r"\b(?:cannot|can't|never|does\s+not|do\s+not|no)\s+guarantee\b", re.IGNORECASE),
        re.compile(r"\bno\s+guarantee\s+of\s+approval\b", re.IGNORECASE),
        re.compile(r"\bapproval\s+is\s+not\s+guaranteed\b", re.IGNORECASE),
    ]

    def validate_output(
        self,
        text: str,
        custom_fallback: Optional[str] = None,
    ) -> OutputValidationResult:
        """
        Validate generated LLM output against security, secrecy, and legal standards.
        If violations are detected, remediates by substituting a safe compliant response.
        """
        if not text or not text.strip():
            return OutputValidationResult(is_valid=True, sanitized_output=text)

        violations: List[OutputViolationType] = []
        details: Dict[str, Any] = {}

        # 1. Check Code Blocks & Executables
        code_match = self._check_code(text)
        if code_match:
            violations.append(OutputViolationType.CODE_BLOCK)
            details["code_violation"] = code_match

        # 2. Check Secrets & API Keys
        secret_match = self._check_secrets(text)
        if secret_match:
            violations.append(OutputViolationType.SECRET_LEAK)
            details["secret_violation"] = secret_match

        # 3. Check System Prompt Exfiltration
        prompt_match = self._check_prompt_leak(text)
        if prompt_match:
            violations.append(OutputViolationType.PROMPT_LEAK)
            details["prompt_violation"] = prompt_match

        # 4. Check Internal Path Leaks
        path_match = self._check_path_leak(text)
        if path_match:
            violations.append(OutputViolationType.PATH_LEAK)
            details["path_violation"] = path_match

        # 5. Check Unauthorized Legal Guarantees
        guarantee_match = self._check_legal_guarantee(text)
        if guarantee_match:
            violations.append(OutputViolationType.LEGAL_GUARANTEE)
            details["guarantee_violation"] = guarantee_match

        # If any violations found, apply remediation
        if violations:
            # Audit log security alert
            self._log_security_event(violations, text, details)

            # Determine appropriate remediation fallback
            if violations == [OutputViolationType.LEGAL_GUARANTEE]:
                fallback_text = custom_fallback or LEGAL_GUARANTEE_FALLBACK
            else:
                fallback_text = custom_fallback or SAFE_OUTPUT_FALLBACK

            return OutputValidationResult(
                is_valid=False,
                violations=violations,
                sanitized_output=fallback_text,
                remediation_applied=True,
                details=details,
            )

        return OutputValidationResult(
            is_valid=True,
            violations=[],
            sanitized_output=text,
            remediation_applied=False,
            details={},
        )

    def _check_code(self, text: str) -> Optional[str]:
        """Check for markdown code blocks and raw executable directives."""
        for pattern in self.CODE_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(0)[:60]
        return None

    def _check_secrets(self, text: str) -> Optional[str]:
        """Check for leaked API keys, tokens, or environment credentials."""
        for pattern in self.SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                matched_str = match.group(0)
                # Redact matched secret in memory log
                redacted = matched_str[:6] + "..." + matched_str[-4:] if len(matched_str) > 10 else "[SECRET]"
                return f"Match pattern {pattern.pattern[:30]}... ({redacted})"
        return None

    def _check_prompt_leak(self, text: str) -> Optional[str]:
        """Check for exfiltration of internal system prompts and boundary markers."""
        for pattern in self.PROMPT_LEAK_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(0)[:60]
        return None

    def _check_path_leak(self, text: str) -> Optional[str]:
        """Check for internal server directories and debug tracebacks."""
        for pattern in self.PATH_LEAK_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(0)[:60]
        return None

    def _check_legal_guarantee(self, text: str) -> Optional[str]:
        """Check for dangerous unconditional guarantees while respecting disclaimer context."""
        for pattern in self.LEGAL_GUARANTEE_PATTERNS:
            match = pattern.search(text)
            if match:
                matched_snippet = match.group(0)
                # Check surrounding window for negative disclaimer context (e.g. "does not guarantee")
                start_idx = max(0, match.start() - 30)
                end_idx = min(len(text), match.end() + 30)
                surrounding = text[start_idx:end_idx]

                is_safe_disclaimer = any(sp.search(surrounding) for sp in self.SAFE_DISCLAIMER_PATTERNS)
                if not is_safe_disclaimer:
                    return matched_snippet
        return None

    def _log_security_event(
        self,
        violations: List[OutputViolationType],
        original_text: str,
        details: Dict[str, Any],
    ) -> None:
        """Emit a structured security audit alert."""
        violation_names = [v.value for v in violations]
        preview = original_text[:120].replace("\n", " ")
        logger.warning(
            f"[OUTPUT_GUARDRAIL_ALERT] Violations: {violation_names} | Details: {details} | Preview: '{preview}...'"
        )


# Global singleton instance
output_guardrail = OutputGuardrail()


def validate_output(text: str, custom_fallback: Optional[str] = None) -> OutputValidationResult:
    """Convenience helper to validate generated output using the default singleton."""
    return output_guardrail.validate_output(text, custom_fallback=custom_fallback)
