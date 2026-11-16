"""Chunks that repeat each other are merged with the chunks before them (app/services/repeated_chunks.py)."""

import pytest

from app.services import repeated_chunks

TAIL = "uage level is based on your language test results. If you submitted your PGWP application before November 1"

# The PGWP eligibility page as stored: three sections, each followed by a chunk starting with the same sentence
PAGE = [
    (19, "v19", "Bachelor's, master's or doctoral degree. Language requirement: (CLB) 7 in all 4 areas. Find out what your lang"),
    (20, "v20", TAIL + ", 2024, you don't need to meet the language requirement. Degree field of study."),
    (21, "v21", "If you graduated from any other university program. Language requirement: (CLB) 7. Find out what your lang"),
    (22, "v22", TAIL + ", 2024, you don't need to meet it. Other university field of study."),
    (23, "v23", "If you graduated from any other college program. Language requirement: (CLB) 5. Find out what your lang"),
    (24, "v24", TAIL + ", 2024, you don't need to meet it. College field of study."),
    (25, "v25", "If you graduated from a flight school, you don't need to meet the language requirement."),
]


def hit(vector_id, text, doc=48, score=0.7):
    return {"id": vector_id, "text": text, "score": score, "metadata": {"document_id": doc, "url": "https://x/elig"}}


def by_id(vector_id):
    return next(t for i, v, t in PAGE if v == vector_id)


async def loader(document_id):
    assert document_id == 48
    return PAGE


@pytest.mark.asyncio
async def test_without_repeats_the_first_top_k_come_back_unchanged():
    results = [hit("a", "one", doc=1), hit("b", "two", doc=2), hit("c", "three", doc=3), hit("d", "four", doc=4),
               hit("e", "five", doc=5)]

    async def no_database(_):
        raise AssertionError("the page order is only read when chunks repeat")

    assert await repeated_chunks.collapse(results, 4, loader=no_database) == results[:4]


@pytest.mark.asyncio
async def test_repeated_section_endings_become_one_entry_with_every_sections_level():
    results = [hit("x", "Language tests we accept", doc=7), hit("v20", by_id("v20")), hit("v22", by_id("v22")),
               hit("v24", by_id("v24")), hit("y", "Apply online", doc=8)]
    taken = await repeated_chunks.collapse(results, 4, loader=loader)

    assert [t["id"] for t in taken] == ["x", "v20", "y"]          # one entry for the three, at the best one's place
    merged = taken[1]
    assert merged["merged_repeats"] == 3
    assert "(CLB) 7" in merged["text"] and "(CLB) 5" in merged["text"]   # the college level now reaches the model
    assert merged["text"].index("degree") < merged["text"].index("college")   # page order
    assert merged["text"].endswith(by_id("v20"))                  # the repeated chunk once, at the end
    assert merged["metadata"]["url"] == "https://x/elig"          # still cited as the same page


@pytest.mark.asyncio
async def test_a_merge_frees_places_for_the_next_results():
    results = [hit("v20", by_id("v20")), hit("v22", by_id("v22")), hit("v24", by_id("v24")),
               hit("p", "p", doc=2), hit("q", "q", doc=3), hit("r", "r", doc=4), hit("s", "s", doc=5)]
    taken = await repeated_chunks.collapse(results, 4, loader=loader)
    assert [t["id"] for t in taken] == ["v20", "p", "q", "r"]


@pytest.mark.asyncio
async def test_identical_text_is_kept_once():
    results = [hit("a", "Same paragraph on two pages.", doc=1), hit("b", "Same  paragraph on two pages.", doc=2),
               hit("c", "other", doc=3)]
    assert [t["id"] for t in await repeated_chunks.collapse(results, 4, loader=loader)] == ["a", "c"]


@pytest.mark.asyncio
async def test_same_start_on_different_pages_is_not_merged():
    results = [hit("a", TAIL + " one", doc=1), hit("b", TAIL + " two", doc=2)]

    async def no_database(_):
        raise AssertionError("not a repeat within one page")

    assert [t["id"] for t in await repeated_chunks.collapse(results, 4, loader=no_database)] == ["a", "b"]


@pytest.mark.asyncio
async def test_database_down_falls_back_to_the_results_as_they_are():
    results = [hit("v20", by_id("v20")), hit("v22", by_id("v22"))]

    async def down(_):
        raise ConnectionError("no database")

    assert [t["id"] for t in await repeated_chunks.collapse(results, 4, loader=down)] == ["v20", "v22"]


@pytest.mark.asyncio
async def test_merged_entry_stays_within_its_size_limit(monkeypatch):
    monkeypatch.setattr(repeated_chunks, "MAX_MERGED_CHARS", len(by_id("v20")) + len(by_id("v19")) + 10)
    taken = await repeated_chunks.collapse([hit("v20", by_id("v20")), hit("v22", by_id("v22"))], 4, loader=loader)
    assert "(CLB) 7" in taken[0]["text"] and "(CLB) 5" not in taken[0]["text"]
    assert len(taken[0]["text"]) <= repeated_chunks.MAX_MERGED_CHARS


@pytest.mark.asyncio
async def test_chunks_without_a_document_id_pass_through():
    results = [{"id": "a", "text": TAIL, "metadata": {}}, {"id": "b", "text": TAIL + " more", "metadata": {}}]
    assert [t["id"] for t in await repeated_chunks.collapse(results, 4, loader=loader)] == ["a", "b"]


@pytest.mark.asyncio
async def test_a_section_the_page_holds_twice_is_given_once():
    """The study permit page holds "Step 4: Know the fees" twice; the merged entry carries it once."""
    step = "Step 4: Know the fees you have to pay. Processing fees and biometrics. We'll ask you to pay your fees"
    tail = "u to pay your fees at the end of your application. Third-party fees: medical exams"
    page = [(1, "s1", step), (2, "s2", tail + ", police certificates."), (3, "s3", step), (4, "s4", tail + ", language tests.")]

    async def twice(_):
        return page

    taken = await repeated_chunks.collapse([hit("s2", page[1][2]), hit("s4", page[3][2])], 4, loader=twice)
    assert len(taken) == 1 and taken[0]["text"].count("Step 4") == 1
