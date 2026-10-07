"""
Comprehensive Unit Tests for Post-Generation Output Guardrail (Milestone 3 - Task 3.1).
Verifies:
1. Markdown code block & script interception
2. Secret, API key, and environment variable leak interception
3. System prompt & delimiter exfiltration defense
4. Internal file path & traceback leakage defense
5. Unauthorized legal absolute & guarantee detection (with compliant disclaimer exemption)
6. Remediation fallback replacement
"""

import pytest
from app.services.guardrails.output_guardrail import (
    OutputGuardrail,
    OutputViolationType,
    OutputValidationResult,
    SAFE_OUTPUT_FALLBACK,
    LEGAL_GUARANTEE_FALLBACK,
    validate_output,
)


@pytest.fixture
def guardrail():
    return OutputGuardrail()


# ==============================================================================
# 1. CODE BLOCKS & RAW EXECUTABLES
# ==============================================================================

def test_blocks_markdown_python_code_block(guardrail):
    adversarial_output = (
        "Here is the eligibility criteria:\n"
        "```python\n"
        "def check_eligibility(points):\n"
        "    return points >= 67\n"
        "```"
    )
    result = guardrail.validate_output(adversarial_output)
    assert not result.is_valid
    assert OutputViolationType.CODE_BLOCK in result.violations
    assert result.remediation_applied
    assert result.sanitized_output == SAFE_OUTPUT_FALLBACK


def test_blocks_markdown_bash_code_block(guardrail):
    adversarial_output = (
        "Run this command to download your forms:\n"
        "```bash\n"
        "curl -O https://example.com/form.pdf\n"
        "```"
    )
    result = guardrail.validate_output(adversarial_output)
    assert not result.is_valid
    assert OutputViolationType.CODE_BLOCK in result.violations


def test_blocks_html_script_tags(guardrail):
    adversarial_output = (
        "Welcome to the portal <script>alert(document.cookie);</script> for processing."
    )
    result = guardrail.validate_output(adversarial_output)
    assert not result.is_valid
    assert OutputViolationType.CODE_BLOCK in result.violations


def test_blocks_raw_python_function_and_imports(guardrail):
    adversarial_output = (
        "import requests\n"
        "def download_ircc_form():\n"
        "    pass"
    )
    result = guardrail.validate_output(adversarial_output)
    assert not result.is_valid
    assert OutputViolationType.CODE_BLOCK in result.violations


def test_allows_markdown_bullet_points_with_noc_codes(guardrail):
    legitimate_output = (
        "To qualify for Express Entry:\n"
        "- **NOC 21232**: Software developers and programmers (TEER 1)\n"
        "- **Work Experience**: Minimum 1 continuous year of skilled work\n"
        "- **Language Benchmark**: CLB 7 in English or French"
    )
    result = guardrail.validate_output(legitimate_output)
    assert result.is_valid
    assert not result.violations
    assert not result.remediation_applied
    assert result.sanitized_output == legitimate_output


# ==============================================================================
# 2. SECRET & API KEY LEAKS
# ==============================================================================

def test_blocks_openai_api_key_leak(guardrail):
    leaked_output = (
        "Your request was processed using key sk-abcdef1234567890abcdef1234567890 on the server."
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.SECRET_LEAK in result.violations
    assert result.sanitized_output == SAFE_OUTPUT_FALLBACK


def test_blocks_aws_access_key_leak(guardrail):
    leaked_output = (
        "Documents are saved in S3 bucket with access key AKIAIOSFODNN7EXAMPLE."
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.SECRET_LEAK in result.violations


def test_blocks_github_token_leak(guardrail):
    leaked_output = (
        "Repository token ghp_123456789012345678901234567890123456 was used for checkout."
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.SECRET_LEAK in result.violations


def test_blocks_postgres_password_env_leak(guardrail):
    leaked_output = (
        "Configuration dump: POSTGRES_PASSWORD=superSecretPostgresPass123 in backend .env."
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.SECRET_LEAK in result.violations


# ==============================================================================
# 3. SYSTEM PROMPT & DELIMITER EXFILTRATION
# ==============================================================================

def test_blocks_system_prompt_instruction_leak(guardrail):
    leaked_output = (
        "You are Pendu, an expert, professional Canadian visa and immigration assistant."
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.PROMPT_LEAK in result.violations


def test_blocks_internal_rag_delimiters(guardrail):
    leaked_output = (
        "=== START OFFICIAL RETRIEVED DATA ===\n"
        "Tuition requirement: $20,635 CAD\n"
        "=== END OFFICIAL RETRIEVED DATA ==="
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.PROMPT_LEAK in result.violations


def test_blocks_constitution_and_prompt_constant_names(guardrail):
    leaked_output = "According to GROUNDED_SYSTEM_PROMPT and Pendu Visa Constitution Article 3."
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.PROMPT_LEAK in result.violations


# ==============================================================================
# 4. INTERNAL PATHS & TRACEBACKS
# ==============================================================================

def test_blocks_windows_filesystem_path(guardrail):
    leaked_output = "Document stored at D:\\projects\\llm chatbot\\pendu\\backend\\data.json"
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.PATH_LEAK in result.violations


def test_blocks_server_internal_directory(guardrail):
    leaked_output = "Module located at /backend/app/services/retrieval.py line 45."
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.PATH_LEAK in result.violations


def test_blocks_python_traceback(guardrail):
    leaked_output = (
        "Traceback (most recent call last):\n"
        '  File "test.py", line 12, in <module>\n'
        "KeyError: 'visa_type'"
    )
    result = guardrail.validate_output(leaked_output)
    assert not result.is_valid
    assert OutputViolationType.PATH_LEAK in result.violations


def test_allows_public_https_urls(guardrail):
    legitimate_output = (
        "For official guidelines, please visit:\n"
        "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html"
    )
    result = guardrail.validate_output(legitimate_output)
    assert result.is_valid
    assert not result.violations


# ==============================================================================
# 5. LEGAL ABSOLUTES & GUARANTEES
# ==============================================================================

def test_blocks_100_percent_guarantee(guardrail):
    risky_output = (
        "If you provide a GIC of $20,635 CAD, your visa is 100% guaranteed to be approved."
    )
    result = guardrail.validate_output(risky_output)
    assert not result.is_valid
    assert OutputViolationType.LEGAL_GUARANTEE in result.violations
    assert result.remediation_applied
    assert result.sanitized_output == LEGAL_GUARANTEE_FALLBACK


def test_blocks_unauthorized_approval_guarantee(guardrail):
    risky_output = "We guarantee that you will receive a study permit with this admission letter."
    result = guardrail.validate_output(risky_output)
    assert not result.is_valid
    assert OutputViolationType.LEGAL_GUARANTEE in result.violations


def test_blocks_zero_chance_of_rejection(guardrail):
    risky_output = "With this profile, there is zero chance of refusal."
    result = guardrail.validate_output(risky_output)
    assert not result.is_valid
    assert OutputViolationType.LEGAL_GUARANTEE in result.violations


def test_allows_compliant_negative_guarantee_disclaimer(guardrail):
    compliant_output = (
        "Meeting the minimum financial requirements strengthens your application, "
        "but IRCC does not guarantee visa approval. The final decision rests entirely "
        "with the visa officer based on your overall ties to your home country."
    )
    result = guardrail.validate_output(compliant_output)
    assert result.is_valid
    assert not result.violations
    assert result.sanitized_output == compliant_output


def test_allows_approval_not_guaranteed_disclaimer(guardrail):
    compliant_output = (
        "Please note that visa approval is not guaranteed even if all eligibility criteria are met."
    )
    result = guardrail.validate_output(compliant_output)
    assert result.is_valid
    assert not result.violations


# ==============================================================================
# 6. MULTI-VIOLATION & CONVENIENCE VALIDATION
# ==============================================================================

def test_detects_multiple_violations_simultaneously(guardrail):
    multi_violation = (
        "Here is the internal code:\n"
        "```python\n"
        "API_KEY = 'sk-123456789012345678901234567890'\n"
        "```\n"
        "Also, your visa is 100% guaranteed!"
    )
    result = guardrail.validate_output(multi_violation)
    assert not result.is_valid
    assert OutputViolationType.CODE_BLOCK in result.violations
    assert OutputViolationType.SECRET_LEAK in result.violations
    assert OutputViolationType.LEGAL_GUARANTEE in result.violations
    assert result.remediation_applied
    assert result.sanitized_output == SAFE_OUTPUT_FALLBACK


def test_validate_output_convenience_helper():
    clean_text = "International students may work up to 20 hours per week off-campus during academic sessions."
    result = validate_output(clean_text)
    assert result.is_valid
    assert result.sanitized_output == clean_text
