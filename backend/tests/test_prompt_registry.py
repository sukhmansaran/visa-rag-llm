"""
Versioned prompts (M0.12): prompts load from app/prompts, render strictly, can't change text under an old
version number, and no prompt text is left inline in service code.
"""

import ast
import re
from pathlib import Path

import pytest

from app.services import prompt_registry
from app.services.prompt_registry import (PROMPTS_DIR, Prompt, PromptError, all_prompts, get_prompt, load_lock,
                                          lock_problems)

SERVICES = Path(__file__).resolve().parent.parent / "app" / "services"
LIVE_PROMPTS = {"grounded_answer", "sop_draft", "itinerary", "change_summary", "visa_extraction",
                "program_extraction", "fact_summary", "decomposition", "follow_up", "evidence_answer", "entailment",
                "monitor", "agent_decide"}


@pytest.fixture(autouse=True)
def no_overrides():
    prompt_registry.clear_overrides()
    yield
    prompt_registry.clear_overrides()


def test_every_live_prompt_loads_from_a_file():
    assert set(all_prompts()) == LIVE_PROMPTS
    for prompt in all_prompts().values():
        assert (PROMPTS_DIR / f"{prompt.id}.yaml").exists() and prompt.version >= 1 and prompt.description


def test_the_lock_matches_every_prompt():
    assert lock_problems(all_prompts(), load_lock()) == []


def test_tags_name_id_version_and_text():
    tag = get_prompt("grounded_answer").tag
    assert re.fullmatch(r"grounded_answer@\d+:[0-9a-f]{12}", tag) and len(tag) <= 32  # fits request_traces


def test_render_fills_values_literally():
    system, user = get_prompt("grounded_answer").render(query="Is it CAN$150? {{query}} {not a field}")
    assert user == "User Question: Is it CAN$150? {{query}} {not a field}"  # values are never re-templated
    assert "{{" not in system


def test_render_rejects_missing_and_unknown_variables():
    with pytest.raises(PromptError, match="missing variables \\['query'\\]"):
        get_prompt("grounded_answer").render()
    with pytest.raises(PromptError, match="unknown variables \\['extra'\\]"):
        get_prompt("grounded_answer").render(query="q", extra="x")


def test_json_examples_survive_in_extraction_prompts():
    system, _ = get_prompt("visa_extraction").render()
    assert '"visa_type": "string"' in system and system.rstrip().endswith("no markdown or explanation.")


# ---------------------------------------------------------------- the version lock

def _prompt(version=1, system="Be brief.", user=""):
    return Prompt(id="demo", version=version, description="d", variables=(), system=system, user=user)


def test_changed_text_under_the_same_version_is_caught():
    lock = {"demo": {"1": _prompt().fingerprint}}
    [problem] = lock_problems({"demo": _prompt(system="Be very brief.")}, lock)
    assert "text changed but version is still 1" in problem


def test_a_new_version_must_be_locked():
    lock = {"demo": {"1": _prompt().fingerprint}}
    [problem] = lock_problems({"demo": _prompt(version=2, system="Be very brief.")}, lock)
    assert "demo@2 is not in the lock" in problem


def test_old_versions_stay_valid_in_the_lock():
    lock = {"demo": {"1": _prompt().fingerprint, "2": _prompt(version=2, system="New").fingerprint}}
    assert lock_problems({"demo": _prompt(version=2, system="New")}, lock) == []


# ---------------------------------------------------------------- file validation

@pytest.mark.parametrize("body,message", [
    ("id: demo\nversion: 1\ndescription: d\nsystem: Hi {{name}}\n", "the text uses \\['name'\\]"),
    ("id: demo\nversion: 1\ndescription: d\nvariables: [name]\nsystem: Hi\n", "the text uses \\[\\]"),
    ("id: other\nversion: 1\ndescription: d\nsystem: Hi\n", "must match the file name"),
    ("id: demo\nversion: 0\ndescription: d\nsystem: Hi\n", "positive integer"),
    ("id: demo\nversion: 1\ndescription: d\nsystem: Hi\ncolour: red\n", "unknown fields"),
    ("id: demo\nversion: 1\nsystem: Hi\n", "missing description"),
])
def test_bad_prompt_files_are_rejected(tmp_path, body, message):
    path = tmp_path / "demo.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(PromptError, match=message):
        prompt_registry._load(path)


# ---------------------------------------------------------------- variants under evaluation

def test_an_override_is_tagged_as_an_unsaved_variant():
    saved = get_prompt("grounded_answer")
    variant = prompt_registry.set_override("grounded_answer", "You are a test prompt.")
    assert get_prompt("grounded_answer") is variant and variant.tag.startswith("grounded_answer@0:")
    assert variant.render(query="q")[1] == saved.render(query="q")[1]  # same user template
    prompt_registry.clear_overrides()
    assert get_prompt("grounded_answer") is saved


def test_traces_record_the_prompt_tag():
    from app.services.tracing import _prompt_version
    assert _prompt_version() == get_prompt("grounded_answer").tag
    prompt_registry.set_override("grounded_answer", "variant")
    assert _prompt_version().startswith("grounded_answer@0:")


# ---------------------------------------------------------------- nothing inline

_PROMPT_SIGNS = re.compile(r"\bYou (are (an?|Pendu)|summarize)\b|Return ONLY valid JSON|STRICT RULES:|GROUNDING RULES"
                           r"|Compare these two versions|Write a Statement of Purpose")


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_no_prompt_text_is_inline_in_service_code():
    """Prompt text lives in app/prompts/*.yaml. Guardrails may name prompt phrases (to detect leaks)."""
    offenders = []
    for path in SERVICES.rglob("*.py"):
        if "guardrails" in path.parts:
            continue
        for line, text in _string_literals(path):
            if _PROMPT_SIGNS.search(text):
                offenders.append(f"{path.relative_to(SERVICES)}:{line}")
    assert offenders == []


def test_the_old_prompts_module_is_gone():
    assert not (SERVICES / "prompts.py").exists()
