"""
Exact-word signal for retrieval (M8.5).

The embedding scores a chunk as a whole, so a chunk whose one decisive sentence sits at the end of a section about
something else ranks low: for "What happens to my off-campus job if my study permit application is refused?" the
sentence "If we refuse your work or study permit application, you must stop working and leave Canada" ranked 10th,
behind chunks that share "off campus" and "study permit" but say nothing about a refusal.

score() rates each chunk of the search pool by the question's words it contains, each word weighted by how rare it
is in that pool (a word every chunk has, "permit", tells them apart by nothing; "refused" does). Words are compared
after a light stemming (refused / refuse / refusal -> "refus"). The pool is the vector search's own results, so
nothing outside them is brought in; only their order changes: similarity + RAG_LEXICAL_WEIGHT x this score.
"""

import logging
import math
import re
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z][a-z'-]+")
_STOP = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers him his how i if in
into is it its itself just me more most my myself no nor not now of off on once only or other our ours out over own
same she should so some such than that the their theirs them then there these they this those through to too under
until up very was we were what when where which while who whom why will with would you your yours yourself canada
canadian ircc need needs get gets give
""".split())
_SUFFIXES = ("ations", "ation", "ings", "ing", "ies", "als", "al", "ed", "es", "e", "s")


def stem(word: str) -> str:
    word = word.strip("'-")
    for suffix in _SUFFIXES:
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> set:
    words = set()
    # canada.ca writes "master’s" (curly) and users type "master's": both must give "master", or the decisive word
    # of "my master's program was only 1 year" never matches
    for raw in _WORD.findall((text or "").lower().replace("’", "'")):
        if raw.endswith("'s"):
            raw = raw[:-2]
        for part in raw.split("-"):  # "off-campus" counts as "off" + "campus", as "off campus" does
            if len(part) >= 3 and part not in _STOP:
                words.add(stem(part))
    return words


_CORPUS: Dict[str, object] = {}   # {"at": loaded (monotonic s), "n": chunks, "df": {term: chunks with it}}
CORPUS_TTL_SECONDS = 600
RARE_SHARE = 0.05   # only words in at most 5% of the knowledge base's chunks count


async def corpus_frequencies() -> Optional[Tuple[int, Dict[str, int]]]:
    """(active chunks, chunks holding each word) over the whole knowledge base, cached; None if it can't be read."""
    now = time.monotonic()
    if _CORPUS and now - float(_CORPUS["at"]) < CORPUS_TTL_SECONDS:
        return int(_CORPUS["n"]), _CORPUS["df"]  # type: ignore[return-value]
    try:
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.vector_chunk import VectorChunk

        async with AsyncSessionLocal() as db:
            texts = (await db.execute(select(VectorChunk.text).where(VectorChunk.status == "active"))).scalars().all()
    except Exception as err:  # the database is down: rarity within the pool instead
        logger.warning("[RETRIEVAL] word frequencies unavailable (%s)", type(err).__name__)
        return None
    df: Counter = Counter()
    for text in texts:
        df.update(terms(text))
    _CORPUS.update(at=now, n=len(texts), df=dict(df))
    return len(texts), _CORPUS["df"]  # type: ignore[return-value]


def score(query: str, texts: List[str], corpus: Optional[Tuple[int, Dict[str, int]]] = None) -> List[float]:
    """0..1 per text: the share of the question's (rarity-weighted) words it contains. Rarity over the knowledge
    base when `corpus` is given, else over `texts`."""
    asked = terms(query)
    if not asked or not texts:
        return [0.0] * len(texts)
    seen = [terms(t) for t in texts]
    n, df_of = corpus if corpus and corpus[0] else (len(texts), None)
    rare_limit = RARE_SHARE * n if df_of is not None else n  # in a pool of 12 every word is "common" at 5%
    weights: Dict[str, float] = {}
    for term in asked:
        in_pool = any(term in s for s in seen)
        df = df_of.get(term, 0) if df_of is not None else sum(term in s for s in seen)
        # A word no chunk here has can't tell them apart; a common one ("new", "program", "permit") lifts chunks
        # for the wrong reason ("the new requirements" for "a second PGWP after a new program")
        if in_pool and df and df <= rare_limit:
            weights[term] = math.log((n + 1) / (df + 0.5))
    total = sum(weights.values())
    if total <= 0:
        return [0.0] * len(texts)
    return [round(sum(w for t, w in weights.items() if t in s) / total, 4) for s in seen]
