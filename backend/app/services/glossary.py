"""
Immigration acronym glossary (M0.10b), loaded from app/data/glossary.yaml.

For the validators: recognise terms in a question or answer, expand them, and know which programs are
discontinued (e.g. SDS ended 2024-11-08). Acronyms match case-sensitively ("pal" the word is not PAL);
expansions and aliases match case-insensitively.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "data" / "glossary.yaml"


class GlossaryError(ValueError):
    """The glossary file is malformed."""


@dataclass(frozen=True)
class Term:
    acronym: str
    expansion: str
    definition: str
    source: str
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    status: str = "current"
    ended: Optional[date] = None

    @property
    def discontinued(self) -> bool:
        return self.status == "discontinued"


def load_glossary(path: Path = GLOSSARY_PATH, registry_ids: Optional[set] = None) -> Dict[str, Term]:
    """Terms by acronym. Validates fields; with registry_ids, also that every source exists in the registry."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    terms: Dict[str, Term] = {}
    problems: List[str] = []
    for i, raw in enumerate(data.get("terms") or []):
        where = f"terms[{i}] ({raw.get('acronym', '?')})"
        missing = [k for k in ("acronym", "expansion", "definition", "source") if not raw.get(k)]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
            continue
        unknown = sorted(set(raw) - set(Term.__dataclass_fields__))
        if unknown:
            problems.append(f"{where}: unknown fields {unknown}")
        status = raw.get("status", "current")
        if status not in ("current", "discontinued"):
            problems.append(f"{where}: status must be current or discontinued")
        ended = raw.get("ended")
        if status == "discontinued" and not isinstance(ended, date):
            problems.append(f"{where}: a discontinued term needs ended: YYYY-MM-DD")
        if raw["acronym"] in terms:
            problems.append(f"{where}: duplicate acronym")
        if registry_ids is not None and raw["source"] not in registry_ids:
            problems.append(f"{where}: source '{raw['source']}' is not in the source registry")
        terms[raw["acronym"]] = Term(
            acronym=raw["acronym"], expansion=" ".join(raw["expansion"].split()),
            definition=" ".join(raw["definition"].split()), source=raw["source"],
            aliases=tuple(raw.get("aliases") or ()), status=status, ended=ended,
        )
    if problems:
        raise GlossaryError("Glossary problems:\n  " + "\n  ".join(problems))
    return terms


@lru_cache(maxsize=1)
def glossary() -> Dict[str, Term]:
    """The glossary, validated against the source registry, loaded once per process."""
    from app.services.source_registry import load_registry
    return load_glossary(registry_ids={e.id for e in load_registry().entries})


@lru_cache(maxsize=1)
def _matchers() -> List[Tuple[re.Pattern, Term]]:
    matchers = []
    for term in glossary().values():
        # plural "DLIs" / "ITAs" counts; "PALS" or "itinerary" do not
        matchers.append((re.compile(rf"(?<![\w-]){re.escape(term.acronym)}s?(?![\w-])"), term))
        for phrase in (term.expansion, *term.aliases):
            flags = 0 if phrase.isupper() else re.IGNORECASE  # an all-caps alias (FSWP, CIC) is an acronym too
            matchers.append((re.compile(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", flags), term))
    return matchers


def lookup(name: str) -> Optional[Term]:
    """A term by acronym, expansion or alias (acronym exact; the rest case-insensitive)."""
    name = " ".join(name.split())
    terms = glossary()
    if name in terms:
        return terms[name]
    lowered = name.lower()
    for term in terms.values():
        if lowered == term.expansion.lower() or lowered in (a.lower() for a in term.aliases if not a.isupper()):
            return term
        if name in (a for a in term.aliases if a.isupper()):
            return term
    return None


def find_terms(text: str) -> List[Term]:
    """Terms mentioned in text, in order of first mention, each once."""
    hits: Dict[str, int] = {}
    for pattern, term in _matchers():
        match = pattern.search(text or "")
        if match and (term.acronym not in hits or match.start() < hits[term.acronym]):
            hits[term.acronym] = match.start()
    return [glossary()[acronym] for acronym, _ in sorted(hits.items(), key=lambda kv: kv[1])]
