"""
Crawler Pipeline API endpoints.

Provides admin endpoints for managing crawl jobs, aggregator portals, and seed URLs.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.v1.crawler_schemas import (
    CrawlJobCreate,
    CrawlJobResponse,
    CrawlJobStatusResponse,
    PortalCreate,
    PortalResponse,
    SeedURLCreate,
    SeedURLResponse,
    SeedURLUpdate,
)
from app.core.database import AsyncSessionLocal
from app.models.aggregator_portal import AggregatorPortal
from app.models.crawl_job import CrawlJob
from app.models.seed_url import SeedURL

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crawler", tags=["crawler"])


# --- Crawl Jobs ---

@router.post("/jobs", response_model=CrawlJobResponse)
async def start_crawl_job(body: CrawlJobCreate):
    """Start a new crawl job."""
    from app.workers.crawler_tasks import start_crawl_job_task

    config = {
        "max_pages": body.max_pages,
        "max_depth": body.max_depth,
        "enable_llm_structuring": body.enable_llm_structuring,
        "enable_embedding": body.enable_embedding,
    }
    result = start_crawl_job_task.delay(
        seed_urls=body.seed_urls,
        config=config,
        tier=body.tier,
        allowed_domains=body.allowed_domains,
        portal_domain=body.portal_domain,
        use_playwright=body.use_playwright,
    )
    return CrawlJobResponse(job_id=result.id or "pending", status="queued")


@router.get("/jobs", response_model=list[CrawlJobStatusResponse])
async def list_crawl_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """List crawl jobs with optional status filter."""
    async with AsyncSessionLocal() as db:
        query = select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(limit)
        if status:
            query = query.where(CrawlJob.status == status)
        result = await db.execute(query)
        jobs = result.scalars().all()
        return [
            CrawlJobStatusResponse(
                job_id=j.job_id,
                status=j.status,
                seed_urls=j.seed_urls or [],
                pages_crawled=j.pages_crawled,
                pages_relevant=j.pages_relevant,
                pages_stored=j.pages_stored,
                pages_failed=j.pages_failed,
                started_at=j.started_at.isoformat() if j.started_at else None,
                completed_at=j.completed_at.isoformat() if j.completed_at else None,
                paused_at=j.paused_at.isoformat() if j.paused_at else None,
            )
            for j in jobs
        ]


@router.get("/jobs/{job_id}", response_model=CrawlJobStatusResponse)
async def get_crawl_job(job_id: str):
    """Get crawl job status and statistics."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CrawlJob).where(CrawlJob.job_id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Crawl job not found")
        return CrawlJobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            seed_urls=job.seed_urls or [],
            pages_crawled=job.pages_crawled,
            pages_relevant=job.pages_relevant,
            pages_stored=job.pages_stored,
            pages_failed=job.pages_failed,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            paused_at=job.paused_at.isoformat() if job.paused_at else None,
        )


@router.post("/jobs/{job_id}/pause")
async def pause_crawl_job(job_id: str):
    """Pause a crawl job."""
    from app.services.crawler.job_manager import CrawlJobManager
    manager = CrawlJobManager()
    await manager.pause_job(job_id)
    return {"status": "paused", "job_id": job_id}


@router.post("/jobs/{job_id}/resume")
async def resume_crawl_job(job_id: str):
    """Resume a paused crawl job."""
    from app.services.crawler.job_manager import CrawlJobManager
    manager = CrawlJobManager()
    await manager.resume_job(job_id)
    return {"status": "resumed", "job_id": job_id}


# --- Portals ---

@router.get("/portals", response_model=list[PortalResponse])
async def list_portals():
    """List aggregator portals."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AggregatorPortal).order_by(AggregatorPortal.tier)
        )
        portals = result.scalars().all()
        return [
            PortalResponse(
                id=p.id,
                name=p.name,
                tier=p.tier,
                base_domains=p.base_domains or [],
                category=p.category,
                throttle_rps=p.throttle_rps,
                requires_js=p.requires_js,
                is_active=p.is_active,
                created_at=p.created_at.isoformat() if p.created_at else None,
            )
            for p in portals
        ]


@router.post("/portals", response_model=PortalResponse)
async def create_or_update_portal(body: PortalCreate):
    """Add or update an aggregator portal."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AggregatorPortal).where(AggregatorPortal.name == body.name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.tier = body.tier
            existing.base_domains = body.base_domains
            existing.category = body.category
            existing.throttle_rps = body.throttle_rps
            existing.requires_js = body.requires_js
            existing.extraction_config = body.extraction_config
            portal = existing
        else:
            portal = AggregatorPortal(
                name=body.name,
                tier=body.tier,
                base_domains=body.base_domains,
                category=body.category,
                throttle_rps=body.throttle_rps,
                requires_js=body.requires_js,
                extraction_config=body.extraction_config,
            )
            db.add(portal)
        await db.commit()
        await db.refresh(portal)
        return PortalResponse(
            id=portal.id,
            name=portal.name,
            tier=portal.tier,
            base_domains=portal.base_domains or [],
            category=portal.category,
            throttle_rps=portal.throttle_rps,
            requires_js=portal.requires_js,
            is_active=portal.is_active,
            created_at=portal.created_at.isoformat() if portal.created_at else None,
        )


# --- Seed URLs ---

@router.get("/seeds", response_model=list[SeedURLResponse])
async def list_seeds(portal_id: Optional[int] = Query(None)):
    """List seed URLs, optionally filtered by portal."""
    async with AsyncSessionLocal() as db:
        query = select(SeedURL)
        if portal_id is not None:
            query = query.where(SeedURL.portal_id == portal_id)
        result = await db.execute(query)
        seeds = result.scalars().all()
        return [
            SeedURLResponse(
                id=s.id,
                portal_id=s.portal_id,
                url=s.url,
                max_depth=s.max_depth,
                allowed_domains=s.allowed_domains or [],
                crawl_schedule=s.crawl_schedule,
                is_active=s.is_active,
                last_crawled_at=s.last_crawled_at.isoformat() if s.last_crawled_at else None,
            )
            for s in seeds
        ]


@router.post("/seeds", response_model=SeedURLResponse)
async def create_seed(body: SeedURLCreate):
    """Add a seed URL (validates portal exists)."""
    async with AsyncSessionLocal() as db:
        portal_result = await db.execute(
            select(AggregatorPortal).where(AggregatorPortal.id == body.portal_id)
        )
        if not portal_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Portal not found")

        seed = SeedURL(
            portal_id=body.portal_id,
            url=body.url,
            max_depth=body.max_depth,
            allowed_domains=body.allowed_domains,
            crawl_schedule=body.crawl_schedule,
        )
        db.add(seed)
        await db.commit()
        await db.refresh(seed)
        return SeedURLResponse(
            id=seed.id,
            portal_id=seed.portal_id,
            url=seed.url,
            max_depth=seed.max_depth,
            allowed_domains=seed.allowed_domains or [],
            crawl_schedule=seed.crawl_schedule,
            is_active=seed.is_active,
            last_crawled_at=None,
        )


@router.patch("/seeds/{seed_id}", response_model=SeedURLResponse)
async def update_seed(seed_id: int, body: SeedURLUpdate):
    """Update or deactivate a seed URL."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SeedURL).where(SeedURL.id == seed_id))
        seed = result.scalar_one_or_none()
        if not seed:
            raise HTTPException(status_code=404, detail="Seed URL not found")

        if body.max_depth is not None:
            seed.max_depth = body.max_depth
        if body.allowed_domains is not None:
            seed.allowed_domains = body.allowed_domains
        if body.crawl_schedule is not None:
            seed.crawl_schedule = body.crawl_schedule
        if body.is_active is not None:
            seed.is_active = body.is_active

        await db.commit()
        await db.refresh(seed)
        return SeedURLResponse(
            id=seed.id,
            portal_id=seed.portal_id,
            url=seed.url,
            max_depth=seed.max_depth,
            allowed_domains=seed.allowed_domains or [],
            crawl_schedule=seed.crawl_schedule,
            is_active=seed.is_active,
            last_crawled_at=seed.last_crawled_at.isoformat() if seed.last_crawled_at else None,
        )
