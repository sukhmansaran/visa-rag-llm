"""Exact-word signal for retrieval (app/services/lexical.py)."""

import pytest

from app.services import lexical


def test_words_are_compared_after_light_stemming():
    assert lexical.terms("refused") == lexical.terms("refuse") == {"refus"}
    assert lexical.terms("an off-campus job") == {"campu", "job"}  # "off" and "an" are stop words
    assert lexical.terms("What is it?") == set()


def test_possessives_match_whatever_the_apostrophe():
    assert lexical.terms("my master's program") == lexical.terms("a master’s program") == {"master", "program"}


def test_only_rare_words_count():
    texts = ["You must stop working if we refuse your application.", "Work off campus with a permit.",
             "A permit lets you work off campus."]
    corpus = (1000, {"refus": 20, "campu": 300, "permit": 600, "work": 700, "applic": 500})
    scores = lexical.score("Can I work off campus if my permit is refused?", texts, corpus)
    assert scores[0] == 1.0 and scores[1] == 0.0 and scores[2] == 0.0


def test_a_common_word_does_not_lift_a_chunk():
    """'new' is in 51 of 667 chunks: it lifted "the new requirements" for "a second PGWP after a new program"."""
    corpus = (667, {"new": 51, "pgwp": 54, "program": 137, "second": 16})
    scores = lexical.score("Can I get a second PGWP after doing a new program?",
                           ["The new requirements for a PGWP program.", "You can't get a PGWP if you already had one."],
                           corpus)
    assert scores == [0.0, 0.0]


def test_without_word_counts_rarity_is_measured_in_the_pool():
    scores = lexical.score("refused permit", ["refused permit", "permit", "permit", "permit"], None)
    assert scores[0] == 1.0 and scores[1] < 0.1  # "permit" is in every chunk: it barely counts


def test_nothing_to_compare():
    assert lexical.score("", ["a", "b"]) == [0.0, 0.0]
    assert lexical.score("refused", []) == []


@pytest.mark.asyncio
async def test_word_counts_unavailable_falls_back(monkeypatch):
    import app.core.database as database

    class Broken:
        def __call__(self):
            raise ConnectionError("down")

    monkeypatch.setattr(database, "AsyncSessionLocal", Broken())
    lexical._CORPUS.clear()
    assert await lexical.corpus_frequencies() is None
