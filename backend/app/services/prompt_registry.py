"""
Versioned prompts (M0.12).

Every prompt the app sends to a model lives in `app/prompts/<id>.yaml`:

    id: grounded_answer
    version: 1
    description: ...
    variables: [query]
    system: |-
      ...
    user: |-
      User Question: {{query}}

- Placeholders are `{{name}}`: prompts contain JSON examples ({...}) and amounts like CAN$150, which break
  str.format and string.Template. `render()` fails on a missing, unknown or leftover placeholder.
- `version` is bumped by hand whenever the text changes. `app/prompts/versions.lock.json` remembers the
  fingerprint of every version ever used; tests fail if text changes under an existing version number.
- `Prompt.tag` ("grounded_answer@1:65a65a9948a6") goes into traces and evaluation reports, so any answer can
  be traced to the exact prompt text that produced it (principle 11).
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
LOCK_PATH = PROMPTS_DIR / "versions.lock.json"

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class PromptError(ValueError):
    """A prompt file is malformed, or render() got the wrong variables."""


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    description: str
    variables: Tuple[str, ...]
    system: str
    user: str

    @property
    def fingerprint(self) -> str:
        """12 hex chars of SHA-256 over the system text (+ user template when there is one)."""
        text = self.system if not self.user else f"{self.system}\n\x00\n{self.user}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    @property
    def tag(self) -> str:
        return f"{self.id}@{self.version}:{self.fingerprint}"

    def render(self, **values) -> Tuple[str, str]:
        """(system, user) with every {{name}} filled. Values are inserted as-is (no further templating)."""
        expected, given = set(self.variables), set(values)
        if given != expected:
            missing, unknown = sorted(expected - given), sorted(given - expected)
            raise PromptError(f"{self.id}: missing variables {missing}, unknown variables {unknown}")

        def fill(text: str) -> str:
            return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)

        return fill(self.system), fill(self.user)


def _load(path: Path) -> Prompt:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    where = path.name
    for key in ("id", "version", "description", "system"):
        if key not in data:
            raise PromptError(f"{where}: missing {key}")
    unknown = sorted(set(data) - {"id", "version", "description", "variables", "system", "user"})
    if unknown:
        raise PromptError(f"{where}: unknown fields {unknown}")
    if data["id"] != path.stem:
        raise PromptError(f"{where}: id '{data['id']}' must match the file name")
    if not isinstance(data["version"], int) or data["version"] < 1:
        raise PromptError(f"{where}: version must be a positive integer")
    prompt = Prompt(id=data["id"], version=data["version"], description=" ".join(str(data["description"]).split()),
                    variables=tuple(data.get("variables") or ()), system=data["system"], user=data.get("user") or "")
    used = set(_PLACEHOLDER.findall(prompt.system + prompt.user))
    if used != set(prompt.variables):
        raise PromptError(f"{where}: variables {sorted(prompt.variables)} but the text uses {sorted(used)}")
    return prompt


@lru_cache(maxsize=None)
def all_prompts() -> Dict[str, Prompt]:
    return {p.id: p for p in (_load(path) for path in sorted(PROMPTS_DIR.glob("*.yaml")))}


_overrides: Dict[str, Prompt] = {}


def get_prompt(prompt_id: str) -> Prompt:
    if prompt_id in _overrides:
        return _overrides[prompt_id]
    try:
        return all_prompts()[prompt_id]
    except KeyError:
        raise PromptError(f"No prompt '{prompt_id}' in {PROMPTS_DIR}") from None


def set_override(prompt_id: str, system: str) -> Prompt:
    """
    Use a different system text for `prompt_id` in this process (evaluating a prompt variant without editing
    the file). The variant gets version 0, so traces and reports read "<id>@0:<fingerprint>" and can never be
    mistaken for a saved version. The user template and variables stay those of the saved prompt.
    """
    base = all_prompts()[prompt_id]
    variant = Prompt(id=base.id, version=0, description=f"variant of {base.tag}", variables=base.variables,
                     system=system, user=base.user)
    _overrides[prompt_id] = variant
    return variant


def clear_overrides() -> None:
    _overrides.clear()


def load_lock(path: Path = None) -> Dict[str, Dict[str, str]]:
    """{prompt id: {version: fingerprint}} for every version ever locked."""
    path = Path(path or LOCK_PATH)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def lock_problems(prompts: Dict[str, Prompt], lock: Dict[str, Dict[str, str]]) -> list:
    """Prompts whose text changed under a locked version number, or new versions not locked yet."""
    problems = []
    for prompt in prompts.values():
        locked = lock.get(prompt.id, {}).get(str(prompt.version))
        if locked is None:
            problems.append(f"{prompt.id}@{prompt.version} is not in the lock: run scripts/lock_prompts.py")
        elif locked != prompt.fingerprint:
            problems.append(f"{prompt.id}: text changed but version is still {prompt.version} "
                            f"(locked {locked}, now {prompt.fingerprint}); bump the version, then run "
                            "scripts/lock_prompts.py")
    return problems
