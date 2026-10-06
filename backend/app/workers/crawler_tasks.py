"""
Celery tasks for the Crawler Pipeline.

All tasks use queue='crawler' for dedicated worker routing.
"""

import asyncio
import logging
from typing import Optional

from app.workers.celery_app import celery_app
from app.services.crawler.types import CrawlJobConfig, FrontierEntry

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(bind=True, max_retries=3, queue="crawler")
def crawl_url_task(self, job_id: str, url: str, depth: int, tier: int,
                   seed_url: str = "", allowed_domains: Optional[list] = None,
                   portal_domain: Optional[str] = None,
                   use_playwright: bool = False):
    """Fetch and process a single URL within a crawl job."""
    from app.services.crawler.job_manager import CrawlJobManager

    async def run():
        manager = CrawlJobManager()
        entry = FrontierEntry(
            url=url, depth=depth, tier=tier, job_id=job_id,
            seed_url=seed_url or url, allowed_domains=allowed_domains or [],
        )
        await manager.process_url(
            job_id=job_id, entry=entry,
            portal_domain=portal_domain, use_playwright=use_playwright,
        )
        # Dequeue next URL and fan out
        next_entry = await manager.frontier.dequeue(job_id)
        if next_entry:
            crawl_url_task.delay(
                job_id=job_id, url=next_entry.url, depth=next_entry.depth,
                tier=next_entry.tier, seed_url=next_entry.seed_url,
                allowed_domains=next_entry.allowed_domains,
                portal_domain=portal_domain, use_playwright=use_playwright,
            )
        return {"status": "processed", "url": url}

    try:
        return _run_async(run())
    except Exception as exc:
        logger.error("crawl_url_task failed for %s: %s", url, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(queue="crawler")
def start_crawl_job_task(seed_urls: list, config: Optional[dict] = None,
                         tier: int = 3, allowed_domains: Optional[list] = None,
                         portal_domain: Optional[str] = None,
                         use_playwright: bool = False) -> dict:
    """Initialize and start a crawl job, fanning out URL tasks."""
    from app.services.crawler.job_manager import CrawlJobManager

    async def run():
        job_config = CrawlJobConfig(**(config or {}))
        manager = CrawlJobManager()
        job_id = await manager.start_job(
            seed_urls=seed_urls, config=job_config,
            tier=tier, allowed_domains=allowed_domains,
        )
        # Fan out initial URL tasks
        for url in seed_urls:
            crawl_url_task.delay(
                job_id=job_id, url=url, depth=0, tier=tier,
                seed_url=url, allowed_domains=allowed_domains or [],
                portal_domain=portal_domain, use_playwright=use_playwright,
            )
        return {"job_id": job_id, "seeds": len(seed_urls)}

    return _run_async(run())


@celery_app.task(queue="crawler")
def llm_structure_batch_task(job_id: str, document_ids: list) -> dict:
    """Batch LLM structuring for accumulated documents."""
    from app.services.crawler.structurer import LLMStructurer
    from app.core.database import AsyncSessionLocal
    from app.models.document import Document
    from sqlalchemy import select

    async def run():
        structurer = LLMStructurer()
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Document).where(Document.id.in_(document_ids))
            )
            docs = result.scalars().all()
            items = [
                {"text": doc.extracted_text, "type": "program", "doc_id": doc.id}
                for doc in docs
            ]
        results = await structurer.extract_batch(items)
        return {
            "job_id": job_id,
            "processed": len(results),
            "successful": sum(1 for r in results if r.get("success")),
        }

    return _run_async(run())


@celery_app.task(queue="crawler")
def crawl_portal_task(portal_id: int) -> dict:
    """Start a crawl job for all seeds under a specific portal."""
    from app.core.database import AsyncSessionLocal
    from app.models.aggregator_portal import AggregatorPortal
    from app.models.seed_url import SeedURL
    from sqlalchemy import select

    async def run():
        async with AsyncSessionLocal() as db:
            portal_result = await db.execute(
                select(AggregatorPortal).where(AggregatorPortal.id == portal_id)
            )
            portal = portal_result.scalar_one_or_none()
            if not portal or not portal.is_active:
                return {"status": "skipped", "reason": "portal inactive or not found"}

            seeds_result = await db.execute(
                select(SeedURL)
                .where(SeedURL.portal_id == portal_id)
                .where(SeedURL.is_active == True)
            )
            seeds = seeds_result.scalars().all()
            if not seeds:
                return {"status": "skipped", "reason": "no active seeds"}

            seed_urls = [s.url for s in seeds]
            allowed = portal.base_domains or []

        result = start_crawl_job_task.delay(
            seed_urls=seed_urls,
            tier=portal.tier,
            allowed_domains=allowed,
            portal_domain=allowed[0] if allowed else None,
            use_playwright=portal.requires_js,
        )
        return {"status": "started", "portal": portal.name, "seeds": len(seed_urls)}

    return _run_async(run())
