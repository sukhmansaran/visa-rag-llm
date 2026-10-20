"""
Startup preflight (M0.17): a missing dependency gives a clear message and a fix, never a stack trace.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import preflight  # noqa: E402
from preflight import FAIL, OK, WARN, Check  # noqa: E402


def fixed(name, status, detail="", fix=""):
    async def check():
        return Check(name, status, detail, fix)
    check.__name__ = f"check_{name.lower()}"
    return check


@pytest.mark.asyncio
async def test_a_crashing_check_becomes_a_failure_not_a_traceback():
    async def check_redis():
        raise ConnectionRefusedError("boom")

    [result] = await preflight.run_checks([check_redis])
    assert result.status == FAIL and result.name == "Redis" and "ConnectionRefusedError" in result.detail


@pytest.mark.asyncio
async def test_nothing_else_runs_without_settings():
    results = await preflight.run_checks([fixed("Settings", FAIL), fixed("Redis", OK)])
    assert [r.name for r in results] == ["Settings"]


def test_exit_code_and_output(monkeypatch, capsys):
    async def checks():
        return [Check("PostgreSQL", FAIL, "can't connect (ConnectionRefusedError)", "Start PostgreSQL 16"),
                Check("Knowledge base", WARN, "empty", "run the ingestion"), Check("Redis", OK, "connected")]

    monkeypatch.setattr(preflight, "run_checks", checks)
    assert preflight.main() == 1
    out = capsys.readouterr().out
    assert "[FAIL] PostgreSQL" in out and "fix: Start PostgreSQL 16" in out
    assert "[WARN] Knowledge base" in out and "Not ready: 1 problem(s)" in out


def test_warnings_alone_do_not_block_startup(monkeypatch, capsys):
    async def checks():
        return [Check("Ports", WARN, "already in use: 8000"), Check("Redis", OK, "connected")]

    monkeypatch.setattr(preflight, "run_checks", checks)
    assert preflight.main() == 0 and "Ready to start." in capsys.readouterr().out


@pytest.mark.asyncio
async def test_unreachable_redis_is_a_clear_failure(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")  # nothing listens on port 1
    result = await preflight.check_redis()
    assert result.status == FAIL and "Memurai" in result.fix


@pytest.mark.asyncio
async def test_unreachable_ollama_is_a_clear_failure(monkeypatch):
    from app.services import model_pins

    async def unreachable():
        return model_pins.PinReport(ollama_reachable=False)

    monkeypatch.setattr(model_pins, "check_pins", unreachable)
    result = await preflight.check_ollama()
    assert result.status == FAIL and "ollama serve" in result.fix


@pytest.mark.asyncio
async def test_a_missing_model_tells_you_what_to_pull(monkeypatch):
    from app.services import model_pins

    async def missing():
        return model_pins.compare({"llama3.2:3b": {"digest": "a" * 64}}, {}, {"llama3.2:3b": ["answer"]})

    monkeypatch.setattr(model_pins, "check_pins", missing)
    result = await preflight.check_ollama()
    assert result.status == FAIL and result.fix == "ollama pull llama3.2:3b"


@pytest.mark.asyncio
async def test_a_changed_model_build_is_only_a_warning(monkeypatch):
    from app.services import model_pins

    async def changed():
        return model_pins.compare({"llama3.2:3b": {"digest": "a" * 64}}, {"llama3.2:3b": "b" * 64},
                                  {"llama3.2:3b": ["answer"]})

    monkeypatch.setattr(model_pins, "check_pins", changed)
    assert (await preflight.check_ollama()).status == WARN


@pytest.mark.asyncio
async def test_a_database_behind_on_migrations_is_a_failure(monkeypatch):
    """The test database is built without Alembic, so it has no revision: exactly the 'not migrated' case."""
    result = await preflight.check_database()
    assert result.status == FAIL and "alembic upgrade head" in result.fix
