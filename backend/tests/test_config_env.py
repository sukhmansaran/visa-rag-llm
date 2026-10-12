"""
Tests for application configuration and environment validation.
Verifies R13 (.env.example parity) and R12 (SECRET_KEY enforcement).
"""

import os
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_env_example_loads_cleanly():
    """Verify that .env.example can be loaded into Settings with zero validation errors."""
    example_path = Path(__file__).resolve().parent.parent / ".env.example"
    assert example_path.exists(), ".env.example file must exist in backend directory"
    
    # Load settings from .env.example (SECRET_KEY is intentionally blank there; supply a real one)
    settings = Settings(_env_file=str(example_path), SECRET_KEY="k" * 48)
    assert settings.APP_NAME == "Overseas Visa Chatbot API"
    assert settings.ENVIRONMENT == "development"
    assert settings.ALGORITHM == "HS256"
    assert settings.OLLAMA_MODEL == "llama3.2:3b"
    assert settings.SQL_ECHO is False


def test_secret_key_required_in_production(monkeypatch):
    """Verify that empty SECRET_KEY raises a ValidationError in production/development."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, SECRET_KEY="")
    
    assert "SECRET_KEY must be explicitly set" in str(exc_info.value)


@pytest.mark.parametrize("bad_key", [
    "your-secret-key-here-change-in-production-min-32-chars",
    "too-short-key",
    "x" * 20,
])
def test_secret_key_rejects_placeholders_and_short_keys(monkeypatch, bad_key):
    """N2: placeholder or short SECRET_KEY values must be rejected outside test environments."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY=bad_key)


def test_secret_key_accepts_strong_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY="a" * 48)
    assert s.SECRET_KEY == "a" * 48


def test_debug_and_cors_regex_default_off():
    """A16/A17: DEBUG and the localhost CORS regex default to off."""
    s = Settings(_env_file=None, SECRET_KEY="a" * 48)
    assert s.DEBUG is False
    assert s.CORS_ALLOW_LOCALHOST_REGEX is False


def test_secret_key_has_default_in_test_env(monkeypatch):
    """Verify that testing environments receive a safe default SECRET_KEY if unset."""
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    
    settings = Settings(_env_file=None, SECRET_KEY="")
    assert settings.SECRET_KEY == "test-secret-key-32-chars-minimum-length-for-testing"
