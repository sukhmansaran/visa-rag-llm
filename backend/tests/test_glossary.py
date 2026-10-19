"""
Immigration acronym glossary (M0.10b): loads from data, every source is a registry page, and terms are
recognised without false hits on ordinary words.
"""

from datetime import date
from pathlib import Path

import pytest
import yaml

from app.services.glossary import GLOSSARY_PATH, GlossaryError, find_terms, glossary, load_glossary, lookup
from app.services.source_registry import load_registry

ROADMAP_ACRONYMS = {"PAL", "TAL", "SDS", "PGWP", "CLB", "NOC", "TEER", "LMIA", "GIC", "DLI", "ECA", "ITA", "CRS",
                    "FSW", "CEC", "FST"}


def test_loads_from_data_with_every_roadmap_acronym():
    assert GLOSSARY_PATH.suffix == ".yaml"
    assert ROADMAP_ACRONYMS <= set(glossary())


def test_every_source_is_a_registry_page():
    registry_ids = {e.id for e in load_registry().entries}
    for term in glossary().values():
        assert term.source in registry_ids, term.acronym


def test_sds_is_marked_discontinued():
    sds = glossary()["SDS"]
    assert sds.discontinued and sds.ended == date(2024, 11, 8)
    assert not glossary()["PGWP"].discontinued


@pytest.mark.parametrize("name,acronym", [
    ("PGWP", "PGWP"), ("post-graduation work permit", "PGWP"), ("Post graduation work permit", "PGWP"),
    ("Designated learning institution", "DLI"), ("FSWP", "FSW"), ("visitor visa", "TRV"), ("eTA", "eTA"),
])
def test_lookup(name, acronym):
    assert lookup(name).acronym == acronym


def test_lookup_misses_return_none():
    assert lookup("pal") is None  # the acronym is case-sensitive
    assert lookup("Express lane") is None


def test_find_terms_in_order_without_false_hits():
    text = ("My pal says the SDS is faster, but I need a PAL and a GIC? After my degree at a designated learning "
            "institution I want a post-graduation work permit, then a CRS score for Express Entry.")
    assert [t.acronym for t in find_terms(text)] == ["SDS", "PAL", "GIC", "DLI", "PGWP", "CRS"]


@pytest.mark.parametrize("text", [
    "My itinerary is ready",   # "ita" inside a word
    "a crisp crs-like idea",   # lowercase, joined by a hyphen
    "nocturnal flights",       # "noc" inside a word
    "PALS",                    # shouting, not a plural acronym
])
def test_no_hits_inside_other_words(text):
    found = {t.acronym for t in find_terms(text)}
    assert not found & {"ITA", "CRS", "NOC", "PAL", "DLI"}


def test_plural_acronyms_count():
    assert [t.acronym for t in find_terms("Compare two DLIs before your ITAs arrive")] == ["DLI", "ITA"]


def write(tmp_path, terms) -> Path:
    path = tmp_path / "glossary.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "terms": terms}), encoding="utf-8")
    return path


GOOD = {"acronym": "PAL", "expansion": "Provincial attestation letter", "definition": "A letter.",
        "source": "study-permit-pal-tal"}


@pytest.mark.parametrize("bad,message", [
    ({**GOOD, "definition": ""}, "missing definition"),
    ({**GOOD, "colour": "red"}, "unknown fields"),
    ({**GOOD, "status": "paused"}, "status must be"),
    ({**GOOD, "status": "discontinued"}, "needs ended"),
    ({**GOOD, "source": "not-a-page"}, "not in the source registry"),
])
def test_bad_terms_are_reported(tmp_path, bad, message):
    with pytest.raises(GlossaryError, match=message):
        load_glossary(write(tmp_path, [bad]), registry_ids={"study-permit-pal-tal"})


def test_duplicates_are_reported(tmp_path):
    with pytest.raises(GlossaryError, match="duplicate acronym"):
        load_glossary(write(tmp_path, [GOOD, GOOD]))
