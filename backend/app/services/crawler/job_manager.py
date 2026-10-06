"""
Crawl Job Manager for the Crawler Pipeline.

Orchestrates crawl jobs from seed URLs through the full pipeline:
fetch → robots check → throttle → classify → extract → deduplicate → structure → store.
Manages job state, error rate monitoring, and portal failure detection.
"""

import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.crawl_job import CrawlJob
from app.models.crawled_page import CrawledPage
from app.models.document import Document
from app.models.program_record import ProgramRecord
from app.models.source import Source
from app.services.crawler.cache import ResponseCache
from app.services.crawler.classifier import PageClassifier
from app.services.crawler.dedup import Deduplicator
from app.services.crawler.extractor import ContentExtractor
from app.services.crawler.frontier import CrawlFrontier
from app.services.crawler.robots import RobotsChecker
from app.services.crawler.structurer import LLMStructurer
from app.services.crawler.throttle import ThrottleManager
from app.services.crawler.types import CrawlJobConfig, FrontierEntry
from app.services.crawler.worker import CrawlerWorker

logger = logging.getLogger(__name__)

_ERROR_RATE_THRESHOLD = 0.20
_PORTAL_FAILURE_THRESHOLD = 0.10
_PAUSE_EXPIRY_HOURS = 48


class CrawlJobManager:
    """Orchestrates crawl jobs from seed URLs through to storage."""

    def __init__(
        self,
        frontier: Optional[CrawlFrontier] = None,
        robots: Optional[RobotsChecker] = None,
        throttle: Optional[ThrottleManager] = None,
        worker: Optional[CrawlerWorker] = None,
        classifier: Optional[PageClassifier] = None,
        extractor: Optional[ContentExtractor] = None,
        dedup: Optional[Deduplicator] = None,
        structurer: Optional[LLMStructurer] = None,
        cache: Optional[ResponseCache] = None,
    ):
        self.frontier = frontier or CrawlFrontier()
        self.robots = robots or RobotsChecker()
        self.throttle = throttle or ThrottleManager()
        self.worker = worker or CrawlerWorker()
        self.classifier = classifier or PageClassifier()
        self.extractor = extractor or ContentExtractor()
        self.dedup = dedup or Deduplicator()
        self.structurer = structurer or LLMStructurer()
        self.cache = cache or ResponseCache()

    async def start_job(
        self,
        seed_urls: list[str],
        config: CrawlJobConfig,
        tier: int = 3,
        allowed_domains: Optional[list[str]] = None,
    ) -> str:
        """Start a new crawl job. Returns job_id."""
        job_id = str(uuid.uuid4())

        async with AsyncSessionLocal() as db:
            job = CrawlJob(
                job_id=job_id,
                status="running",
                seed_urls=seed_urls,
                config={
                    "max_pages": config.max_pages,
                    "max_depth": config.max_depth,
                    "tier_filter": config.tier_filter,
                    "category_filter": config.category_filter,
                    "enable_llm_structuring": config.enable_llm_structuring,
                    "enable_embedding": config.enable_embedding,
                },
                started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()

        # Enqueue seed URLs into frontier
        for url in seed_urls:
            domains = allowed_domains or [urlparse(url).netloc]
            await self.frontier.enqueue(
                url=url,
                depth=0,
                tier=tier,
                job_id=job_id,
                seed_url=url,
                allowed_domains=domains,
            )

        logger.info("Started crawl job %s with %d seeds", job_id, len(seed_urls))
        return job_id

    async def pause_job(self, job_id: str) -> None:
        """Pause an active crawl job."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CrawlJob).where(CrawlJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if job and job.status == "running":
                job.status = "paused"
                job.paused_at = datetime.utcnow()
                await db.commit()
                logger.info("Paused crawl job %s", job_id)

    async def resume_job(self, job_id: str) -> None:
        """Resume a paused crawl job."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CrawlJob).where(CrawlJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return

            # Check 48-hour expiry
            if (
                job.status == "paused"
                and job.paused_at
                and datetime.utcnow() - job.paused_at > timedelta(hours=_PAUSE_EXPIRY_HOURS)
            ):
                job.status = "expired"
                await db.commit()
                logger.warning("Crawl job %s expired (paused > 48h)", job_id)
                return

            if job.status == "paused":
                job.status = "running"
                job.paused_at = None
                await db.commit()
                logger.info("Resumed crawl job %s", job_id)

    async def get_job_status(self, job_id: str) -> Optional[dict]:
        """Get current state of a crawl job."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CrawlJob).where(CrawlJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return None

            frontier_size = await self.frontier.size(job_id)
            return {
                "job_id": job.job_id,
                "status": job.status,
                "pages_crawled": job.pages_crawled,
                "pages_relevant": job.pages_relevant,
                "pages_stored": job.pages_stored,
                "pages_failed": job.pages_failed,
                "pages_duplicate": job.pages_duplicate,
                "pages_robots_blocked": job.pages_robots_blocked,
                "frontier_pending": frontier_size,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }

    async def process_url(
        self,
        job_id: str,
        entry: FrontierEntry,
        portal_domain: Optional[str] = None,
        use_playwright: bool = False,
    ) -> None:
        """Full pipeline for a single URL: fetch → classify → extract → structure → store."""
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        page = CrawledPage(
            job_id=job_id,
            url=entry.url,
            depth=entry.depth,
            worker_id=worker_id,
        )

        try:
            # 1. Robots check
            if not await self.robots.is_allowed(entry.url):
                page.status = "robots_blocked"
                page.classification = "skipped"
                await self._save_page_and_update_job(page, job_id, "robots_blocked")
                return

            # 2. Throttle
            domain = urlparse(entry.url).netloc
            await self.throttle.wait_and_acquire(domain)

            # 3. Fetch
            fetch_result = await self.worker.fetch(entry.url, use_playwright=use_playwright)
            elapsed_ms = int((time.time() - start_time) * 1000)
            page.http_status = fetch_result.status_code
            page.fetch_duration_ms = elapsed_ms
            page.fetched_at = datetime.utcnow()

            if fetch_result.status_code == 403:
                await self.throttle.block_domain(domain)
                page.status = "failed"
                page.error_message = "HTTP 403 — domain blocked"
                await self._save_page_and_update_job(page, job_id, "failed")
                return

            if fetch_result.status_code == 429:
                from app.services.crawler.worker import _parse_retry_after
                pause_secs = _parse_retry_after(fetch_result.headers)
                await self.throttle.pause_domain(domain, pause_secs)
                page.status = "failed"
                page.error_message = f"HTTP 429 — paused {pause_secs}s"
                await self._save_page_and_update_job(page, job_id, "failed")
                return

            if not fetch_result.raw_html and not fetch_result.extracted_text:
                page.status = "failed"
                page.error_message = f"HTTP {fetch_result.status_code} — no content"
                await self._save_page_and_update_job(page, job_id, "failed")
                return

            # 4. Classify
            raw_text = fetch_result.extracted_text or ""
            title = ""
            if fetch_result.raw_html:
                extraction = self.extractor.extract(fetch_result.raw_html, entry.url)
                raw_text = extraction.text or raw_text
                title = extraction.title or ""
                content_hash = extraction.content_hash
            else:
                import hashlib
                content_hash = hashlib.sha256(raw_text.encode()).hexdigest()

            classification = self.classifier.classify(
                url=entry.url, title=title, body_text=raw_text, portal_domain=portal_domain
            )
            page.classification = "relevant" if classification.is_relevant else "irrelevant"
            page.matched_keywords = classification.matched_keywords

            if not classification.is_relevant:
                page.status = "processed"
                await self._save_page_and_update_job(page, job_id, "irrelevant")
                return

            # 5. Deduplicate
            if await self.dedup.is_duplicate(content_hash):
                page.content_hash = content_hash
                page.status = "duplicate"
                await self._save_page_and_update_job(page, job_id, "duplicate")
                return

            await self.dedup.register(content_hash, entry.url)
            page.content_hash = content_hash

            # 6. Store document
            async with AsyncSessionLocal() as db:
                # Find or create source
                result = await db.execute(
                    select(Source).where(Source.url == entry.seed_url)
                )
                source = result.scalar_one_or_none()
                if not source:
                    source = Source(
                        url=entry.seed_url,
                        name=f"Crawled: {urlparse(entry.seed_url).netloc}",
                        source_type="aggregator",
                        priority=entry.tier,
                    )
                    db.add(source)
                    await db.flush()

                # Check for existing document with same URL
                existing_doc = await db.execute(
                    select(Document)
                    .join(Source)
                    .where(Source.url == entry.url)
                    .where(Document.content_hash != content_hash)
                )
                old_doc = existing_doc.scalar_one_or_none()

                doc = Document(
                    source_id=source.id,
                    content_hash=content_hash,
                    raw_html=fetch_result.raw_html,
                    extracted_text=raw_text,
                )
                db.add(doc)
                await db.flush()
                page.document_id = doc.id

                # 7. LLM structuring (if enabled)
                job_result = await db.execute(
                    select(CrawlJob).where(CrawlJob.job_id == job_id)
                )
                job = job_result.scalar_one_or_none()
                config = job.config if job else {}

                if config.get("enable_llm_structuring", True):
                    try:
                        program_data = await self.structurer.extract_program_fields(
                            raw_text, portal_domain
                        )
                        if program_data and program_data.get("program_name"):
                            await self._upsert_program_record(
                                db, program_data, doc.id, source.portal_id, entry.url
                            )
                    except Exception as e:
                        logger.warning("LLM structuring failed: %s", e)

                await db.commit()

                # 8. Trigger change detection if content changed
                if old_doc:
                    try:
                        from app.services.change_detector import ChangeDetector
                        detector = ChangeDetector()
                        await detector.detect_changes(source.id)
                    except Exception as e:
                        logger.warning("Change detection failed: %s", e)

            page.status = "processed"
            await self._save_page_and_update_job(page, job_id, "stored")

        except Exception as e:
            logger.error("Error processing %s: %s", entry.url, e, exc_info=True)
            page.status = "failed"
            page.error_message = str(e)[:500]
            await self._save_page_and_update_job(page, job_id, "failed")

    async def _save_page_and_update_job(
        self, page: CrawledPage, job_id: str, outcome: str
    ) -> None:
        """Save CrawledPage and update CrawlJob statistics."""
        async with AsyncSessionLocal() as db:
            db.add(page)

            result = await db.execute(
                select(CrawlJob).where(CrawlJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if job:
                job.pages_crawled += 1
                if outcome == "stored":
                    job.pages_relevant += 1
                    job.pages_stored += 1
                elif outcome == "irrelevant":
                    pass
                elif outcome == "failed":
                    job.pages_failed += 1
                elif outcome == "duplicate":
                    job.pages_duplicate += 1
                elif outcome == "robots_blocked":
                    job.pages_robots_blocked += 1

                # Error rate auto-pause
                total = job.pages_crawled + job.pages_failed
                if total > 10 and job.pages_failed / total > _ERROR_RATE_THRESHOLD:
                    job.status = "paused"
                    job.paused_at = datetime.utcnow()
                    logger.warning(
                        "Auto-paused job %s: error rate %.1f%%",
                        job_id, (job.pages_failed / total) * 100,
                    )

            await db.commit()

    async def _upsert_program_record(
        self,
        db: AsyncSession,
        data: dict,
        document_id: int,
        portal_id: Optional[int],
        source_url: str,
    ) -> None:
        """Insert or update a ProgramRecord based on (program_name, university_name)."""
        program_name = data.get("program_name", "")
        university_name = data.get("university_name", "")

        result = await db.execute(
            select(ProgramRecord).where(
                ProgramRecord.program_name == program_name,
                ProgramRecord.university_name == university_name,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing record
            for key, value in data.items():
                if value is not None and hasattr(existing, key):
                    setattr(existing, key, value)
            existing.document_id = document_id
            existing.source_url = source_url
            existing.updated_at = datetime.utcnow()
            existing.needs_review = False
        else:
            record = ProgramRecord(
                portal_id=portal_id or 0,
                document_id=document_id,
                source_url=source_url,
                program_name=program_name,
                university_name=university_name,
                degree_level=data.get("degree_level", ""),
                tuition_fee=data.get("tuition_fee"),
                tuition_currency=data.get("tuition_currency"),
                duration=data.get("duration"),
                intake_dates=data.get("intake_dates"),
                location_city=data.get("location_city"),
                location_country=data.get("location_country"),
                entry_requirements=data.get("entry_requirements"),
                language_of_instruction=data.get("language_of_instruction"),
                application_deadline=data.get("application_deadline"),
                scholarship_availability=data.get("scholarship_availability"),
            )
            db.add(record)
