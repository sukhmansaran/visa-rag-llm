"""
Pinned model builds (M0.11): a re-pulled model is detected, reported at startup and in /health, and the
eval gate refuses to judge unpinned builds. No Ollama needed: installed digests are faked.
"""

import pytest
import yaml

from app.core.config import settings
from app.services import model_pins
from app.services.model_pins import compare, configured_models, load_pins, write_pins

LLAMA_A = "a" * 64
LLAMA_B = "b" * 64
NOMIC = "c" * 64


@pytest.fixture
def pins_file(tmp_path, monkeypatch):
    path = tmp_path / "model_pins.yaml"
    monkeypatch.setattr(model_pins, "PINS_PATH", path)
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3.2:3b")
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    for name in ("LLM_MODEL_PLANNER", "LLM_MODEL_ANSWER", "LLM_MODEL_VERIFIER", "LLM_FALLBACK_MODEL"):
        monkeypatch.setattr(settings, name, None)
    return path


def fake_ollama(monkeypatch, installed=None, down=False):
    async def installed_digests(*args, **kwargs):
        if down:
            import httpx
            raise httpx.ConnectError("refused")
        return installed

    monkeypatch.setattr(model_pins, "installed_digests", installed_digests)


def test_configured_models_cover_every_role_and_embeddings(pins_file, monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "phi4-mini")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "phi4-mini")
    models = configured_models()
    assert models == {"llama3.2:3b": ["default", "planner", "answer"], "phi4-mini:latest": ["verifier", "fallback"],
                      "nomic-embed-text:latest": ["embeddings"]}


@pytest.mark.parametrize("pins,installed,expected", [
    ({"llama3.2:3b": LLAMA_A}, {"llama3.2:3b": LLAMA_A}, "ok"),
    ({"llama3.2:3b": LLAMA_A}, {"llama3.2:3b": LLAMA_B}, "changed"),  # re-pulled tag
    ({"llama3.2:3b": LLAMA_A}, {}, "not_installed"),
    ({}, {"llama3.2:3b": LLAMA_A}, "unpinned"),
])
def test_compare(pins, installed, expected):
    report = compare({m: {"digest": d} for m, d in pins.items()}, installed, {"llama3.2:3b": ["answer"]})
    assert report.models[0].status == expected and report.ok == (expected == "ok")


def test_accept_then_detect_a_repulled_model(pins_file, monkeypatch):
    write_pins({"llama3.2:3b": LLAMA_A, "nomic-embed-text:latest": NOMIC}, configured_models(), "eval 52/63")
    stored = yaml.safe_load(pins_file.read_text(encoding="utf-8"))["models"]
    assert stored["llama3.2:3b"]["digest"] == LLAMA_A and stored["llama3.2:3b"]["note"] == "eval 52/63"

    report = compare(load_pins(), {"llama3.2:3b": LLAMA_B, "nomic-embed-text:latest": NOMIC}, configured_models())
    assert not report.ok
    assert report.problems() == [f"llama3.2:3b has changed since it was pinned (pinned {'a' * 12}, "
                                 f"installed {'b' * 12})"]


def test_re_accepting_unchanged_builds_keeps_their_history(pins_file):
    write_pins({"llama3.2:3b": LLAMA_A, "nomic-embed-text:latest": NOMIC}, configured_models(), "first")
    write_pins({"llama3.2:3b": LLAMA_A, "nomic-embed-text:latest": NOMIC}, configured_models(), "second")
    assert load_pins()["llama3.2:3b"]["note"] == "first"  # same build: original acceptance kept


def test_cannot_pin_a_model_that_is_not_installed(pins_file):
    with pytest.raises(ValueError, match="not installed"):
        write_pins({"llama3.2:3b": LLAMA_A}, configured_models(), "eval")


@pytest.mark.asyncio
async def test_startup_check_logs_problems_and_remembers_the_report(pins_file, monkeypatch):
    write_pins({"llama3.2:3b": LLAMA_A, "nomic-embed-text:latest": NOMIC}, configured_models(), "eval")
    fake_ollama(monkeypatch, {"llama3.2:3b": LLAMA_B, "nomic-embed-text:latest": NOMIC})
    monkeypatch.setattr(model_pins, "check_pins", _check_with(pins_file))
    # Spy on the module's logger directly: the app's logging setup (run by other tests) can stop caplog seeing it
    warnings = []
    monkeypatch.setattr(model_pins.logger, "warning", lambda msg, *args: warnings.append(msg % args))

    report = await model_pins.refresh_pin_report()
    assert not report.ok and model_pins.pin_report() is report
    assert any("llama3.2:3b has changed" in w for w in warnings)


@pytest.mark.asyncio
async def test_unreachable_ollama_is_reported_not_raised(pins_file, monkeypatch):
    fake_ollama(monkeypatch, down=True)
    report = await model_pins.check_pins(pins_file)
    assert not report.ollama_reachable and not report.ok
    assert "not reachable" in report.problems()[0]


def _check_with(path):
    real = model_pins.check_pins

    async def check(*_):
        return await real(path)
    return check


@pytest.mark.asyncio
async def test_health_reports_model_pins(client, pins_file, monkeypatch):
    write_pins({"llama3.2:3b": LLAMA_A, "nomic-embed-text:latest": NOMIC}, configured_models(), "eval")
    fake_ollama(monkeypatch, {"llama3.2:3b": LLAMA_B, "nomic-embed-text:latest": NOMIC})
    monkeypatch.setattr(model_pins, "check_pins", _check_with(pins_file))
    await model_pins.refresh_pin_report()

    body = (await client.get("/health")).json()
    assert body["status"] == "healthy"  # the API still serves; the model warning is separate
    assert body["models"]["ok"] is False
    assert {m["model"]: m["status"] for m in body["models"]["models"]} == {
        "llama3.2:3b": "changed", "nomic-embed-text:latest": "ok"}


def test_the_committed_pins_cover_the_default_configuration():
    pins = load_pins()
    for model in ("llama3.2:3b", "nomic-embed-text:latest"):
        assert len(pins[model]["digest"]) == 64 and pins[model]["note"]
