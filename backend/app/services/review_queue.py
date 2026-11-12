"""
Review queue for live-fetched pages (M5.5b, D2).

A page fetched live is used for the answer it was fetched for and nothing else. If its text differs from the stored
copy it is queued here; an admin approves or rejects it (admin API, scripts/review_queue.py). Nothing enters the
knowledge base without approval:

  queue    live_fetch.fetch -> queue_fetched: one pending item per page (a newer fetch replaces it); skipped when the
           text equals the stored copy or was already reviewed (approved or rejected) with the same content
  approve  an automatic backup, then the normal ingestion of exactly the reviewed text (no second fetch: what was
           read is what is stored); the item keeps its hash and outcome, its text is emptied (it now lives in the
           document)
  reject   the text is deleted and the cached copy dropped (D7); the hash stays so the same content isn't queued again

Queueing never fails an answer: any error is logged and the answer goes on.
"""

import asyncio
import difflib
import hashlib
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.fetched_page import FetchedPageReview
from app.models.source import Source
from app.models.vector_chunk import VectorChunk

logger = logging.getLogger(__name__)

MAX_QUEUED_CHARS = 500_000   # a page's whole main text; far above any registry page
MAX_DIFF_LINES = 800


class ReviewError(Exception):
    """The review action can't be carried out; `status` is the HTTP status the admin API answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _sessions():
    """The session factory queueing uses outside a request. Tests replace it (never the development database)."""
    from app.core.database import AsyncSessionLocal

    return AsyncSessionLocal


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()  # as the scraper hashes a page


async def stored_document(db: AsyncSession, source_id: int) -> Optional[Document]:
    """The version of the page that answers are retrieved from now."""
    has_chunks = select(VectorChunk.id).where(VectorChunk.document_id == Document.id).exists()
    return (await db.execute(
        select(Document).where(Document.source_id == source_id, has_chunks)
        .order_by(Document.scraped_at.desc(), Document.id.desc()).limit(1))).scalar_one_or_none()


# ---------------------------------------------------------------- queue

async def enqueue(db: AsyncSession, url: str, final_url: str, title: str, text: str,
                  fetched_at: Optional[datetime] = None) -> str:
    """Queue a fetched page. Returns what happened: queued | replaced | unchanged | seen | no_source | empty."""
    text = text[:MAX_QUEUED_CHARS]
    if not text.strip():
        return "empty"
    source = (await db.execute(select(Source).where(Source.url == url))).scalar_one_or_none()
    if source is None:
        return "no_source"  # a registry page not yet synced to the sources table: nothing to compare or ingest into
    digest = content_hash(text)
    stored = await stored_document(db, source.id)
    if stored is not None and stored.content_hash == digest:
        return "unchanged"
    same = (await db.execute(select(FetchedPageReview).where(
        FetchedPageReview.source_id == source.id, FetchedPageReview.content_hash == digest))).scalar_one_or_none()
    if same is not None and same.status != "approved":
        return "seen"  # waiting already, or rejected with this exact content
    pending = (await db.execute(select(FetchedPageReview).where(
        FetchedPageReview.source_id == source.id, FetchedPageReview.status == "pending"))).scalar_one_or_none()
    values = dict(url=url, final_url=final_url, title=title[:300], text=text, chars=len(text), content_hash=digest,
                  fetched_at=fetched_at or datetime.utcnow())
    if same is not None:
        # The page went back to a version approved earlier and replaced since: that item waits for review again
        if pending is not None:
            await db.delete(pending)
            await db.flush()
        for key, value in values.items():
            setattr(same, key, value)
        same.status, same.outcome, same.reviewed_at, same.reviewed_by = "pending", None, None, None
        outcome = "queued"
    elif pending is not None:
        for key, value in values.items():
            setattr(pending, key, value)
        outcome = "replaced"
    else:
        db.add(FetchedPageReview(source_id=source.id, **values))
        outcome = "queued"
    try:
        await db.commit()
    except IntegrityError:  # another worker queued the same content at the same moment
        await db.rollback()
        return "seen"
    return outcome


async def queue_fetched(page: Any, full_text: str) -> Optional[str]:
    """Called by live_fetch after a network fetch. Never raises."""
    try:
        factory = _sessions()
        if factory is None:
            return None
        async with factory() as db:
            fetched_at = datetime.fromisoformat(page.fetched_at) if page.fetched_at else None
            outcome = await enqueue(db, page.url, page.final_url, page.title, full_text, fetched_at)
        if outcome in ("queued", "replaced"):
            logger.info("[REVIEW QUEUE] %s: %s", outcome, page.url)
        return outcome
    except Exception:
        logger.warning("[REVIEW QUEUE] could not queue %s", getattr(page, "url", "?"), exc_info=True)
        return None


# ---------------------------------------------------------------- read

def summary(item: FetchedPageReview, source_name: Optional[str] = None) -> Dict[str, Any]:
    return {"id": item.id, "source_id": item.source_id, "source_name": source_name, "url": item.url,
            "final_url": item.final_url, "title": item.title, "chars": item.chars, "status": item.status,
            "outcome": item.outcome, "fetched_at": item.fetched_at.isoformat(),
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "reviewed_by": item.reviewed_by}


async def list_items(db: AsyncSession, status: Optional[str] = "pending", limit: int = 100) -> List[Dict[str, Any]]:
    query = (select(FetchedPageReview, Source.name).join(Source, Source.id == FetchedPageReview.source_id)
             .order_by(desc(FetchedPageReview.fetched_at), desc(FetchedPageReview.id)).limit(limit))
    if status:
        query = query.where(FetchedPageReview.status == status)
    return [summary(item, name) for item, name in (await db.execute(query)).all()]


async def _item(db: AsyncSession, item_id: int) -> FetchedPageReview:
    item = (await db.execute(select(FetchedPageReview).where(FetchedPageReview.id == item_id))).scalar_one_or_none()
    if item is None:
        raise ReviewError("Review item not found", 404)
    return item


def diff_lines(stored: str, fetched: str) -> List[str]:
    """A unified diff of the stored copy against the fetched page (no file headers), at most MAX_DIFF_LINES."""
    lines = list(difflib.unified_diff(stored.splitlines(), fetched.splitlines(), lineterm="", n=2))[2:]
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... {len(lines) - MAX_DIFF_LINES} more diff lines not shown"]
    return lines


async def detail(db: AsyncSession, item_id: int) -> Dict[str, Any]:
    """One item with both texts and their diff, for the reviewer."""
    item = await _item(db, item_id)
    source = (await db.execute(select(Source).where(Source.id == item.source_id))).scalar_one_or_none()
    stored = await stored_document(db, item.source_id)
    stored_text = stored.extracted_text if stored else ""
    return {**summary(item, source.name if source else None),
            "text": item.text,
            "stored_text": stored_text if item.status == "pending" else "",
            "stored_scraped_at": stored.scraped_at.isoformat() if stored else None,
            "diff": diff_lines(stored_text, item.text) if item.status == "pending" else []}


# ---------------------------------------------------------------- decide

def _backup(label: str) -> str:
    """Database + knowledge-base backup (scripts/backup_now.py); returns the dump's name. Raises on failure."""
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from backup_now import backup

    dump, _ = backup(label)
    return dump.name


async def approve(db: AsyncSession, item_id: int, reviewer_id: Optional[int] = None,
                  backup: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Back up, then ingest exactly the reviewed text as the page's new version."""
    from app.services.ingestion import ingestion_service

    item = await _item(db, item_id)
    if item.status != "pending":
        raise ReviewError(f"This item is already {item.status}")
    source = (await db.execute(select(Source).where(Source.id == item.source_id))).scalar_one_or_none()
    if source is None or not source.is_active:
        raise ReviewError("The page's source is missing or inactive; reject the item instead")

    try:
        dump = await asyncio.to_thread(backup or _backup, f"pre_review_approve_{item.id}")
    except Exception as e:
        logger.error("[REVIEW QUEUE] backup failed; item %s not approved", item.id, exc_info=True)
        raise ReviewError(f"The backup failed, so nothing was changed ({type(e).__name__})", 500) from e

    result = await ingestion_service.ingest_scraped(source, {
        "url": item.url, "title": item.title, "raw_html": None, "extracted_text": item.text,
        "content_hash": item.content_hash, "scraped_at": item.fetched_at.isoformat()}, db)
    if result.get("status") == "error":  # refused before anything was written
        raise ReviewError(f"Ingestion refused the page: {result.get('reason')}", 422)

    item = await _item(db, item_id)
    chunks = result.get("chunks_created")
    item.outcome = (f"{chunks} chunks stored" if chunks is not None else "already the stored version") + f"; backup {dump}"
    item.status, item.text = "approved", ""
    item.reviewed_at, item.reviewed_by = datetime.utcnow(), reviewer_id
    await db.commit()
    logger.info("[REVIEW QUEUE] approved item %s (%s): %s", item.id, item.url, item.outcome)
    return {**summary(item, source.name), "ingestion": {k: result.get(k) for k in (
        "status", "reason", "document_id", "chunks_created", "superseded_chunks_removed")}}


async def reject(db: AsyncSession, item_id: int, reviewer_id: Optional[int] = None) -> Dict[str, Any]:
    """Delete the fetched text; keep the hash so the same content is not queued again."""
    item = await _item(db, item_id)
    if item.status != "pending":
        raise ReviewError(f"This item is already {item.status}")
    item.status, item.text, item.outcome = "rejected", "", "text deleted"
    item.reviewed_at, item.reviewed_by = datetime.utcnow(), reviewer_id
    await db.commit()
    try:  # answers stop using the rejected copy too
        from app.services import live_fetch
        from app.services.answer_jobs import _redis

        await _redis().delete(live_fetch._cache_key(item.url))
    except Exception:
        logger.debug("[REVIEW QUEUE] cached copy not dropped", exc_info=True)
    return summary(item)
