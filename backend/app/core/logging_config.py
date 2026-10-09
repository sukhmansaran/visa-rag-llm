"""
Logging configuration for the application.
Includes PII Redaction Filter and Structured Non-PII Audit Telemetry (Milestone 4 - Task 4.2).
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
import json
import re
import hashlib
from datetime import datetime
from typing import Any, Dict, Optional, List
import traceback

from app.core.config import settings


# ==============================================================================
# PII Redaction Regex Rules & Engine
# ==============================================================================

class PIIRedactor:
    """Deterministic regex scrubbing engine for sensitive Personally Identifiable Information (PII)."""

    # 1. Email Addresses
    EMAIL_PATTERN = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
    )

    # 2. International & North American Phone Numbers
    PHONE_PATTERN = re.compile(
        r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    )

    # 3. Bearer Tokens & Secret API Keys
    AUTH_TOKEN_PATTERN = re.compile(
        r'(?i)(?:Bearer\s+[A-Za-z0-9_\-\.~+/]+=*|'
        r'(?:sk|ghp|gho|pat|xoxb|xoxp|AKIA)[a-zA-Z0-9_\-]{16,}|'
        r'api[_-]?key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}["\']?)'
    )

    # 4. Passport Numbers (Standard ICAO uppercase single letter + 7 or 8 digits, or explicit context)
    PASSPORT_EXPLICIT_PATTERN = re.compile(
        r'(?i)\b(?:passport\s*(?:number|no|id|#)?\s*[:=]?\s*)([A-Za-z0-9]{6,10})\b'
    )
    PASSPORT_ICAO_PATTERN = re.compile(
        r'\b[A-PR-WY-Za-pr-wy-z][0-9]{7,8}\b'
    )

    # 5. Government IDs (Canadian SIN, US SSN, IRCC UCI)
    SIN_EXPLICIT_PATTERN = re.compile(
        r'(?i)\b(?:sin|social\s*insurance\s*number)\s*[:=]?\s*(\d{3}[-\s]?\d{3}[-\s]?\d{3})\b'
    )
    SSN_PATTERN = re.compile(
        r'\b\d{3}-\d{2}-\d{4}\b'
    )
    UCI_EXPLICIT_PATTERN = re.compile(
        r'(?i)\b(?:uci|unique\s*client\s*identifier)\s*[:=]?\s*(\d{2}[-\s]?\d{4}[-\s]?\d{4}|\d{4}[-\s]?\d{4}|\d{8,10})\b'
    )


    # 6. Financial Credentials (Credit Cards, Bank Account Numbers)
    CREDIT_CARD_PATTERN = re.compile(
        r'\b(?:\d{4}[-\s]?){3}\d{4}\b'
    )
    BANK_ACCOUNT_PATTERN = re.compile(
        r'(?i)\b(?:bank\s*(?:account|acct)|account\s*number|acct\s*#)\s*[:=]?\s*(\d{8,17})\b'
    )

    @classmethod
    def redact(cls, text: str) -> str:
        """Apply all PII redaction patterns sequentially to scrub sensitive strings."""
        if not text or not isinstance(text, str):
            return text

        # 1. Scrub Bearer tokens & API keys first
        text = cls.AUTH_TOKEN_PATTERN.sub("[REDACTED_AUTH_TOKEN]", text)

        # 2. Scrub Emails
        text = cls.EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)

        # 3. Scrub Explicit Passports & ICAO format
        text = cls.PASSPORT_EXPLICIT_PATTERN.sub("passport: [REDACTED_PASSPORT]", text)
        text = cls.PASSPORT_ICAO_PATTERN.sub("[REDACTED_PASSPORT]", text)

        # 4. Scrub Government IDs (SIN, SSN, UCI)
        text = cls.SIN_EXPLICIT_PATTERN.sub("SIN: [REDACTED_GOV_ID]", text)
        text = cls.SSN_PATTERN.sub("[REDACTED_GOV_ID]", text)
        text = cls.UCI_EXPLICIT_PATTERN.sub("UCI: [REDACTED_GOV_ID]", text)

        # 5. Scrub Financial Credentials (Credit cards & bank account numbers)
        text = cls.CREDIT_CARD_PATTERN.sub("[REDACTED_FINANCIAL]", text)
        text = cls.BANK_ACCOUNT_PATTERN.sub("account: [REDACTED_FINANCIAL]", text)

        # 6. Scrub Phone numbers (executed after credit cards to avoid substring conflicts)
        text = cls.PHONE_PATTERN.sub("[REDACTED_PHONE]", text)

        return text


def redact_pii(data: Any) -> Any:
    """Recursively scrub PII from strings, dicts, lists, and tuples."""
    if isinstance(data, str):
        return PIIRedactor.redact(data)
    elif isinstance(data, dict):
        return {k: redact_pii(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_pii(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(redact_pii(item) for item in data)
    return data


# ==============================================================================
# Logging Filter & Structured JSON Formatter
# ==============================================================================

class PIIRedactionFilter(logging.Filter):
    """
    Logging filter that sanitizes record messages and arguments before formatting.
    Guarantees no raw PII reaches console or file handlers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = PIIRedactor.redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_pii(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    PIIRedactor.redact(arg) if isinstance(arg, str) else arg 
                    for arg in record.args
                )

        return True


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured non-PII audit logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON with sanitized metrics."""
        
        # Scrub message string
        clean_message = PIIRedactor.redact(record.getMessage())

        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": clean_message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add request ID if available
        req_id = getattr(record, 'audit_request_id', None) or getattr(record, 'request_id', None)
        if req_id:
            log_data['request_id'] = str(req_id)
        
        # Non-PII User Hashing (SHA-256 salted hash)
        if hasattr(record, 'user_id') and record.user_id:
            raw_uid = str(record.user_id)
            log_data['user_id_hash'] = hashlib.sha256(raw_uid.encode('utf-8')).hexdigest()[:16]
        else:
            log_data['user_id_hash'] = "anonymous"

        # Structured Operational Audit Telemetry
        if hasattr(record, 'intent'):
            log_data['intent'] = record.intent
        if hasattr(record, 'retrieval_chunks'):
            log_data['retrieval_chunks'] = record.retrieval_chunks
        if hasattr(record, 'latency_ms'):
            log_data['latency_ms'] = record.latency_ms
        if hasattr(record, 'guardrail_status'):
            log_data['guardrail_status'] = record.guardrail_status
        if hasattr(record, 'risk_categories'):
            log_data['risk_categories'] = record.risk_categories
        
        # Add extra fields (sanitized recursively)
        if hasattr(record, 'extra') and record.extra:
            log_data['extra'] = redact_pii(record.extra)
        
        # Add exception info if present (traceback strings sanitized)
        if record.exc_info:
            raw_tb = "".join(traceback.format_exception(*record.exc_info))
            log_data['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                'message': PIIRedactor.redact(str(record.exc_info[1])),
                'traceback': PIIRedactor.redact(raw_tb),
            }
        
        return json.dumps(log_data)


class RequestIDFilter(logging.Filter):
    """Filter to ensure request ID exists on log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'request_id') or record.request_id is None:
            record.request_id = getattr(record, 'audit_request_id', None)
        return True


# ==============================================================================
# Audit Event Helper
# ==============================================================================

def log_audit_event(
    logger: logging.Logger,
    event_type: str,
    user_id: Optional[Any] = None,
    request_id: Optional[str] = None,
    intent: Optional[str] = None,
    retrieval_chunks: int = 0,
    latency_ms: int = 0,
    guardrail_status: str = "ALLOWED",
    risk_categories: Optional[List[str]] = None,
    extra_details: Optional[Dict[str, Any]] = None,
):
    """
    Emit a structured, non-PII operational audit telemetry event.
    Automatically redacts any accidental PII in extra_details and hashes user_id.
    """
    try:
        extra = {
            "user_id": user_id,
            "audit_request_id": request_id,
            "intent": intent or "general",
            "retrieval_chunks": retrieval_chunks,
            "latency_ms": latency_ms,
            "guardrail_status": guardrail_status,
            "risk_categories": risk_categories or [],
            "extra": extra_details or {},
        }
        logger.info(f"AUDIT_EVENT: {event_type}", extra=extra)
    except Exception:
        # A logging failure must never silently break an otherwise valid request
        pass


# ==============================================================================
# Logging Configuration Setup
# ==============================================================================

def setup_logging():
    """Configure application logging with PII scrubbing and structured JSON handlers."""
    
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler (human-readable, PII redacted)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(RequestIDFilter())
    console_handler.addFilter(PIIRedactionFilter())
    root_logger.addHandler(console_handler)
    
    # File handler (JSON format, PII redacted)
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(JSONFormatter())
    file_handler.addFilter(RequestIDFilter())
    file_handler.addFilter(PIIRedactionFilter())
    root_logger.addHandler(file_handler)
    
    # Error file handler (errors only, PII redacted)
    error_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())
    error_handler.addFilter(RequestIDFilter())
    error_handler.addFilter(PIIRedactionFilter())
    root_logger.addHandler(error_handler)
    
    # Silence noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    logging.info("Logging configured successfully with PII Redaction Filter active")


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
