"""
Pinned model builds (M0.11).

`ollama pull llama3.2:3b` can silently replace the model behind a tag, and every evaluation result was
measured on one specific build. `app/data/model_pins.yaml` records the accepted build (Ollama's manifest
digest) of every configured model; `check_pins()` compares it with what Ollama serves now.

- Startup logs a warning for any mismatch and /health reports it; the M1 verified path must refuse to run
  while `pin_report().ok` is False.
- scripts/eval_gate.py refuses to judge unpinned models: a baseline only holds for the builds it measured.
- Only `scripts/pin_models.py --accept` writes the pins file, after the full evaluation has been re-run.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)

PINS_PATH = Path(__file__).resolve().parent.parent / "data" / "model_pins.yaml"


def _full_name(model: str) -> str:
    return model if ":" in model else f"{model}:latest"


def configured_models() -> Dict[str, List[str]]:
    """Every model the settings name, with the uses it serves: {"llama3.2:3b": ["answer", "planner", ...]}."""
    uses = {
        "default": settings.OLLAMA_MODEL,
        "planner": settings.LLM_MODEL_PLANNER or settings.OLLAMA_MODEL,
        "answer": settings.LLM_MODEL_ANSWER or settings.OLLAMA_MODEL,
        "verifier": settings.LLM_MODEL_VERIFIER or settings.OLLAMA_MODEL,
        "monitor": (settings.LLM_MODEL_MONITOR or settings.OLLAMA_MODEL) if settings.MONITOR_ENABLED else None,
        "fallback": settings.LLM_FALLBACK_MODEL,
        "embeddings": settings.OLLAMA_EMBEDDING_MODEL,
    }
    models: Dict[str, List[str]] = {}
    for use, model in uses.items():
        if model:
            models.setdefault(_full_name(model), []).append(use)
    return models


def load_pins(path: Optional[Path] = None) -> Dict[str, dict]:
    """{"llama3.2:3b": {"digest": ..., "accepted_at": ..., "note": ...}}; {} if the file is missing."""
    path = Path(path or PINS_PATH)  # resolved per call, so tests (and tools) can redirect PINS_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {_full_name(name): pin for name, pin in (data.get("models") or {}).items()}


async def installed_digests(base_url: Optional[str] = None, timeout: float = 5.0) -> Dict[str, str]:
    """{model name: full digest} from Ollama's /api/tags. Raises httpx.HTTPError if Ollama is unreachable."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{(base_url or settings.OLLAMA_BASE_URL).rstrip('/')}/api/tags")
        response.raise_for_status()
        return {m["name"]: m["digest"] for m in response.json().get("models", []) if m.get("digest")}


@dataclass
class ModelStatus:
    model: str
    uses: List[str]
    status: str  # ok | changed | not_installed | unpinned
    pinned: Optional[str] = None
    installed: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class PinReport:
    models: List[ModelStatus] = field(default_factory=list)
    ollama_reachable: bool = True
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    @property
    def ok(self) -> bool:
        return self.ollama_reachable and all(m.ok for m in self.models)

    def problems(self) -> List[str]:
        if not self.ollama_reachable:
            return ["Ollama is not reachable, so model builds could not be checked"]
        text = {
            "changed": "{m} has changed since it was pinned (pinned {p}, installed {i})",
            "not_installed": "{m} is pinned but not installed in Ollama",
            "unpinned": "{m} has no pinned build",
        }
        return [text[s.status].format(m=s.model, p=(s.pinned or "")[:12], i=(s.installed or "")[:12])
                for s in self.models if not s.ok]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "checked_at": self.checked_at, "ollama_reachable": self.ollama_reachable,
            "models": [{"model": m.model, "uses": m.uses, "status": m.status,
                        "pinned": (m.pinned or "")[:12] or None, "installed": (m.installed or "")[:12] or None}
                       for m in self.models],
        }


def compare(pins: Dict[str, dict], installed: Dict[str, str], models: Dict[str, List[str]]) -> PinReport:
    """Pure comparison of pins, installed digests and configured models."""
    report = PinReport()
    for model, uses in models.items():
        pinned = (pins.get(model) or {}).get("digest")
        current = installed.get(model)
        if not pinned:
            status = "unpinned"
        elif not current:
            status = "not_installed"
        elif current != pinned:
            status = "changed"
        else:
            status = "ok"
        report.models.append(ModelStatus(model, uses, status, pinned, current))
    return report


async def check_pins(path: Optional[Path] = None) -> PinReport:
    """Compare the pins with what Ollama serves now. Never raises."""
    try:
        installed = await installed_digests()
    except Exception as err:
        logger.warning("Model pin check: Ollama unreachable (%s)", err)
        return PinReport(ollama_reachable=False)
    return compare(load_pins(path), installed, configured_models())


_last_report: Optional[PinReport] = None


async def refresh_pin_report() -> PinReport:
    """Check now, remember the result for pin_report(), and log every problem."""
    global _last_report
    _last_report = await check_pins()
    for problem in _last_report.problems():
        logger.warning("Model pins: %s. Answers may differ from the evaluated build; re-run the full "
                       "evaluation, then scripts/pin_models.py --accept.", problem)
    if _last_report.ok:
        logger.info("Model pins: all %d configured models match their pinned builds", len(_last_report.models))
    return _last_report


def pin_report() -> Optional[PinReport]:
    """The last startup/refresh result (None if never checked in this process)."""
    return _last_report


def write_pins(installed: Dict[str, str], models: Dict[str, List[str]], note: str,
               path: Optional[Path] = None) -> None:
    """Record the installed build of every configured model. Only scripts/pin_models.py --accept calls this."""
    path = Path(path or PINS_PATH)
    existing = load_pins(path)
    stamp = datetime.utcnow().isoformat(timespec="seconds")
    for model, uses in models.items():
        if model not in installed:
            raise ValueError(f"{model} is configured but not installed in Ollama; pull it before pinning")
        if (existing.get(model) or {}).get("digest") != installed[model]:
            existing[model] = {"digest": installed[model], "accepted_at": stamp, "uses": uses, "note": note}
        else:
            existing[model]["uses"] = uses
    header = ("# Accepted model builds (M0.11). Written only by scripts/pin_models.py --accept, after the full\n"
              "# evaluation (eval_gate.py --full) passed on these builds. See app/services/model_pins.py.\n")
    body = yaml.safe_dump({"version": 1, "models": existing}, sort_keys=True, allow_unicode=True)
    Path(path).write_text(header + body, encoding="utf-8")
