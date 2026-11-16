"""
Chunks that repeat each other (M8.3 follow-up).

A page whose sections end with the same sentence ("Find out what your language level is based on your language
test results.") is chunked so that the chunk after each section starts with that sentence (the chunker's overlap).
Those chunks look almost the same to the embedding, rank together and fill the top-k, while what tells the
sections apart (the heading and the figure, e.g. CLB 7 for degrees, CLB 5 for college programs) sits in the chunk
before each of them, which ranks lower and never reaches the model.

collapse() walks the search results in similarity order and:
  - drops a chunk whose text is identical to one already taken;
  - replaces chunks of one page that start with the same text by one entry: the chunk before each of them (in
    page order, read from vector_chunks), then the repeated text once.
It stops at top_k entries. When nothing repeats, the first top_k results come back unchanged. The knowledge base
is not modified; only what one answer is given changes.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PREFIX_CHARS = 60          # chunks of one page starting with the same 60 characters repeat each other
MAX_MERGED_CHARS = 2000    # one merged entry stays well inside the answer's context (RAG_CONTEXT_CHARS)
POOL_FACTOR = 3            # how many more results than top_k to search, so a collapse can be refilled


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _start(text: str) -> str:
    return _norm(text)[:PREFIX_CHARS]


def _document_id(chunk: Dict[str, Any]) -> Optional[int]:
    value = (chunk.get("metadata") or {}).get("document_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def load_document_chunks(document_id: int) -> List[Tuple[int, str, str]]:
    """(chunk_index, vector_id, text) of a document's active chunks, in page order."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.vector_chunk import VectorChunk

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(VectorChunk.chunk_index, VectorChunk.vector_id, VectorChunk.text)
            .where(VectorChunk.document_id == document_id, VectorChunk.status == "active")
            .order_by(VectorChunk.chunk_index))).all()
    return [(int(i), str(v), t) for i, v, t in rows]


def _merged_text(page: List[Tuple[int, str, str]], start: str, best_text: str) -> Tuple[Optional[str], int]:
    """The chunk before each chunk of `page` that starts with `start`, then the repeated chunk once."""
    starts = {index for index, _, text in page if _start(text) == start}
    before: List[str] = []
    seen = {_norm(best_text)}
    for index, _, text in page:  # a page can hold the same section twice: give the model each text once
        if index + 1 in starts and index not in starts and _norm(text) not in seen:
            before.append(text)
            seen.add(_norm(text))
    if not before:
        return None, 0
    parts: List[str] = []
    room = MAX_MERGED_CHARS - len(best_text)
    for text in before:
        if len(text) + 2 > room:
            break
        parts.append(text)
        room -= len(text) + 2
    if not parts:
        return None, 0
    return "\n\n".join(parts + [best_text]), len(starts)


async def collapse(results: List[Dict[str, Any]], top_k: int, loader=None) -> List[Dict[str, Any]]:
    """`results` in similarity order (best first); returns at most top_k entries, repeats merged."""
    loader = loader or load_document_chunks
    starts_seen: Dict[Tuple[int, str], int] = {}
    for chunk in results:
        doc = _document_id(chunk)
        if doc is not None:
            key = (doc, _start(chunk.get("text", "")))
            starts_seen[key] = starts_seen.get(key, 0) + 1
    repeated = {key for key, n in starts_seen.items() if n > 1}

    pages: Dict[int, List[Tuple[int, str, str]]] = {}
    for doc in {d for d, _ in repeated}:
        try:
            pages[doc] = await loader(doc)
        except Exception as err:  # the database is down: answer from the results as they are
            logger.warning("[RETRIEVAL] could not read the page order of document %s (%s)", doc, type(err).__name__)

    taken: List[Dict[str, Any]] = []
    texts_taken = set()
    merged_keys = set()
    for chunk in results:
        if len(taken) >= top_k:
            break
        text = chunk.get("text", "")
        if _norm(text) in texts_taken:
            continue
        doc = _document_id(chunk)
        key = (doc, _start(text)) if doc is not None else None
        if key in merged_keys:
            continue
        if key in repeated and doc in pages:
            merged, members = _merged_text(pages[doc], key[1], text)
            if merged:
                entry = dict(chunk)
                entry["text"] = merged
                entry["merged_repeats"] = members
                taken.append(entry)
                merged_keys.add(key)
                texts_taken.add(_norm(text))
                continue
        taken.append(chunk)
        texts_taken.add(_norm(text))
    return taken
