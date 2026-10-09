"""
Unit and integration test suite for PII Redaction and Logging Safety (Milestone 4 - Task 4.2).
Validates redaction of passports, emails, phones, tokens, government IDs, and financial data,
as well as non-PII structured audit telemetry.
"""

import logging
import json
import io
import pytest
from app.core.logging_config import (
    PIIRedactor,
    PIIRedactionFilter,
    JSONFormatter,
    redact_pii,
    log_audit_event,
)


class TestPIIRedactorUnit:
    """Verifies regex pattern scrubbing across all PII categories."""

    def test_redacts_email_addresses(self):
        """Standard, personal, and plus-addressed emails are scrubbed."""
        text = "Contact applicant at sukhman.saran@gmail.com or support+ircc@company.co.uk."
        clean = PIIRedactor.redact(text)
        assert "sukhman.saran@gmail.com" not in clean
        assert "support+ircc@company.co.uk" not in clean
        assert "[REDACTED_EMAIL]" in clean

    def test_redacts_phone_numbers(self):
        """North American and international telephone formats are scrubbed."""
        samples = [
            "Call me at +1 (555) 234-5678 regarding the visa.",
            "My direct line is 416-555-0199.",
            "Contact number: (604) 555-7890.",
        ]
        for s in samples:
            clean = PIIRedactor.redact(s)
            assert "[REDACTED_PHONE]" in clean
            assert "555" not in clean

    def test_redacts_bearer_tokens_and_api_keys(self):
        """Bearer tokens, OpenAI keys, and GitHub tokens are scrubbed."""
        samples = [
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
            "Client used API key: sk-ant-api03-abcdef1234567890abcdef",
            "GitHub token leaked: ghp_1234567890abcdefghijklmnopqrstuv",
        ]
        for s in samples:
            clean = PIIRedactor.redact(s)
            assert "[REDACTED_AUTH_TOKEN]" in clean
            assert "eyJhbGciOi" not in clean
            assert "sk-ant-" not in clean
            assert "ghp_" not in clean

    def test_redacts_passports(self):
        """ICAO standard passport format and explicit passport prefixes are scrubbed."""
        samples = [
            "Applicant passport: K12345678 issued in 2022.",
            "Passport number A9876543 verified.",
            "Check document Z1234567 for clearance.",
        ]
        for s in samples:
            clean = PIIRedactor.redact(s)
            assert "[REDACTED_PASSPORT]" in clean

    def test_redacts_canadian_sin_and_us_ssn(self):
        """Social Insurance Numbers and SSNs are scrubbed."""
        sin_sample = "Client SIN: 123-456-789 provided for work permit."
        ssn_sample = "Applicant SSN is 123-45-6789."
        assert "[REDACTED_GOV_ID]" in PIIRedactor.redact(sin_sample)
        assert "[REDACTED_GOV_ID]" in PIIRedactor.redact(ssn_sample)

    def test_redacts_ircc_uci_number(self):
        """IRCC Unique Client Identifier (UCI) is scrubbed."""
        uci_sample = "Application linked to UCI: 11-2233-4455 successfully."
        assert "[REDACTED_GOV_ID]" in PIIRedactor.redact(uci_sample)
        assert "11-2233-4455" not in PIIRedactor.redact(uci_sample)

    def test_redacts_credit_cards_and_bank_accounts(self):
        """16-digit card numbers and bank accounts are scrubbed."""
        cc = "Paid fee with Visa 4532-1234-5678-9012."
        bank = "Tuition wired from bank account: 987654321012."
        assert "[REDACTED_FINANCIAL]" in PIIRedactor.redact(cc)
        assert "[REDACTED_FINANCIAL]" in PIIRedactor.redact(bank)

    def test_preserves_legitimate_immigration_terms(self):
        """Standard IRCC codes and financial statutory thresholds must NOT be altered."""
        safe_text = (
            "Under NOC 21231 (TEER 1), the software engineer must demonstrate "
            "minimum proof of funds of CAD $20,635.00 pursuant to IRPR Section 186(v) "
            "and CELPIP level 7 or IELTS band 6.5."
        )
        clean = PIIRedactor.redact(safe_text)
        assert "NOC 21231" in clean
        assert "TEER 1" in clean
        assert "CAD $20,635.00" in clean
        assert "IRPR Section 186(v)" in clean
        assert "CELPIP level 7" in clean
        assert "IELTS band 6.5" in clean


class TestRecursiveRedactHelper:
    """Verifies recursive sanitization of complex nested data structures."""

    def test_redacts_nested_dictionary(self):
        """Scrubs nested user profile dictionaries."""
        data = {
            "user": {
                "name": "Jane Doe",
                "email": "jane.doe@university.ca",
                "passport": "E7654321",
                "contact": {"phone": "647-555-1234"},
            },
            "scores": {"ielts": 7.5},
        }
        cleaned = redact_pii(data)
        assert cleaned["user"]["email"] == "[REDACTED_EMAIL]"
        assert cleaned["user"]["passport"] == "[REDACTED_PASSPORT]"
        assert cleaned["user"]["contact"]["phone"] == "[REDACTED_PHONE]"
        assert cleaned["scores"]["ielts"] == 7.5


class TestPIIRedactionLoggingIntegration:
    """Verifies Python logging filter and JSONFormatter output sanitization."""

    def test_logger_with_pii_filter_redacts_record_msg(self):
        """Logging messages with passport or email has record.msg sanitized."""
        logger = logging.getLogger("test_pii_logger")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        string_io = io.StringIO()
        handler = logging.StreamHandler(string_io)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.addFilter(PIIRedactionFilter())
        logger.addHandler(handler)

        logger.info("Applicant email is student@outlook.com with passport P9876543")
        output = string_io.getvalue()

        assert "student@outlook.com" not in output
        assert "P9876543" not in output
        assert "[REDACTED_EMAIL]" in output
        assert "[REDACTED_PASSPORT]" in output

    def test_json_formatter_hashes_user_id_and_redacts_message(self):
        """JSONFormatter outputs structured non-PII fields with user_id_hash."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test_audit",
            level=logging.INFO,
            pathname="test_file.py",
            lineno=42,
            msg="User with email test@gmail.com submitted application",
            args=(),
            exc_info=None,
        )
        record.user_id = 98765
        record.request_id = "req-123"
        record.intent = "study_permit"
        record.latency_ms = 450
        record.guardrail_status = "ALLOWED"

        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["user_id_hash"] != "98765"
        assert len(data["user_id_hash"]) == 16
        assert "test@gmail.com" not in data["message"]
        assert "[REDACTED_EMAIL]" in data["message"]
        assert data["request_id"] == "req-123"
        assert data["intent"] == "study_permit"
        assert data["latency_ms"] == 450
        assert data["guardrail_status"] == "ALLOWED"

    def test_log_audit_event_helper(self):
        """Audit event helper emits clean structured event."""
        logger = logging.getLogger("audit_test")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        string_io = io.StringIO()
        handler = logging.StreamHandler(string_io)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

        log_audit_event(
            logger=logger,
            event_type="CHAT_QUERY_PROCESSED",
            user_id="user_admin_123",
            request_id="req-abc",
            intent="financial",
            retrieval_chunks=3,
            latency_ms=310,
            guardrail_status="ALLOWED",
            extra_details={"contact": "secret@ircc.ca"},
        )

        output = string_io.getvalue()
        data = json.loads(output)

        assert data["message"] == "AUDIT_EVENT: CHAT_QUERY_PROCESSED"
        assert data["intent"] == "financial"
        assert data["retrieval_chunks"] == 3
        assert data["latency_ms"] == 310
        assert data["user_id_hash"] != "user_admin_123"
        assert "secret@ircc.ca" not in output
        assert "[REDACTED_EMAIL]" in json.dumps(data["extra"])
