"""
Ingestion API endpoints for triggering scraping and monitoring jobs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, HttpUrl

from app.core.database import get_db
from app.core.security import get_current_admin_user
from app.models.user import User
from app.models.source import Source
from app.workers.tasks import ingest_source_task


router = APIRouter(prefix="/ingest", tags=["Ingestion"])


class AddSourceRequest(BaseModel):
    """Request to add a new source."""
    url: HttpUrl
    name: str
    country: str | None = None
    source_type: str = "official"  # embassy, university, news, official
    priority: int = 3  # 1-5, 1 is highest
    scrape_frequency: int = 168  # hours (default weekly)


class IngestResponse(BaseModel):
    """Response for ingestion trigger."""
    task_id: str
    source_id: int
    status: str


@router.post("/source", status_code=status.HTTP_201_CREATED)
async def add_source(
    request: AddSourceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Add a new source to scrape (admin only).
    
    Requires admin permissions.
    """
    source = Source(
        url=str(request.url),
        name=request.name,
        country=request.country,
        source_type=request.source_type,
        priority=request.priority,
        scrape_frequency=request.scrape_frequency,
    )
    
    db.add(source)
    await db.commit()
    await db.refresh(source)
    
    return {
        "id": source.id,
        "url": source.url,
        "name": source.name,
        "status": "created",
    }


@router.post("/trigger/{source_id}", response_model=IngestResponse)
async def trigger_ingestion(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Manually trigger ingestion for a specific source (admin only).
    
    This queues a Celery task to scrape, chunk, embed, and store the source.
    """
    # Verify source exists
    from sqlalchemy import select
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found",
        )
    
    # Queue Celery task
    task = ingest_source_task.delay(source_id)
    
    return IngestResponse(
        task_id=task.id,
        source_id=source_id,
        status="queued",
    )


@router.post("/trigger-all", response_model=dict)
async def trigger_all_ingestion(
    current_user: User = Depends(get_current_admin_user),
):
    """
    Trigger ingestion for all active sources (admin only).
    
    Use this sparingly - it can be resource-intensive.
    """
    from app.workers.tasks import reingest_all_sources_task
    
    task = reingest_all_sources_task.delay()
    
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Reingestion of all sources queued",
    }


@router.get("/status/{task_id}")
async def get_ingestion_status(
    task_id: str,
    current_user: User = Depends(get_current_admin_user),
):
    """
    Check the status of an ingestion task.
    """
    from celery.result import AsyncResult
    
    result = AsyncResult(task_id)
    
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
