"""
Celery tasks for background processing.
"""

from celery.schedules import crontab
from app.workers.celery_app import celery_app
from app.services.ingestion import ingestion_service
from app.services.change_detector import change_detector
from app.services.notification_service import notification_service
from app.services.push_notification_service import push_notification_service
from app.core.database import AsyncSessionLocal


@celery_app.task(bind=True, max_retries=3)
def ingest_source_task(self, source_id: int):
    """
    Background task to ingest a source.
    
    Args:
        source_id: ID of the source to ingest
        
    Returns:
        Dict with ingestion results
    """
    import asyncio
    
    async def run_ingestion():
        async with AsyncSessionLocal() as db:
            try:
                result = await ingestion_service.ingest_source(source_id, db)
                return result
            except Exception as e:
                # Retry on failure
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    
    # Run async function in event loop
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run_ingestion())


@celery_app.task(bind=True)
def reingest_all_sources_task(self):
    """
    Background task to reingest all active sources.
    
    Returns:
        List of ingestion results
    """
    import asyncio
    
    async def run_reingest():
        async with AsyncSessionLocal() as db:
            results = await ingestion_service.reingest_all_sources(db)
            return results
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run_reingest())


@celery_app.task(bind=True)
def detect_changes_task(self, source_id: int):
    """
    Background task to detect changes in a source.
    
    Args:
        source_id: ID of source to check
        
    Returns:
        Change details or None
    """
    import asyncio
    
    async def run_detection():
        async with AsyncSessionLocal() as db:
            # Detect change
            change = await change_detector.detect_change(source_id, db)
            
            if not change:
                return {"status": "no_change", "source_id": source_id}
            
            # Identify affected users
            affected_users = await change_detector.identify_affected_users(change, db)
            
            if affected_users:
                # Get source for notification
                from sqlalchemy import select
                from app.models.source import Source
                
                result = await db.execute(select(Source).where(Source.id == source_id))
                source = result.scalar_one_or_none()
                
                # Notify users
                await notification_service.notify_users_of_change(
                    user_ids=affected_users,
                    source_name=source.name,
                    diff_summary=change.diff_summary,
                    source_url=source.url,
                    severity=change.severity,
                    db=db,
                )
                
                # Update notified users
                change.notified_users = {"user_ids": affected_users}
                await db.commit()
            
            return {
                "status": "change_detected",
                "source_id": source_id,
                "change_id": change.id,
                "severity": change.severity,
                "affected_users": len(affected_users),
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run_detection())


@celery_app.task
def periodic_change_detection_task():
    """
    Periodic task to check all sources for changes.
    
    This should be run by Celery Beat on a schedule.
    """
    import asyncio
    
    async def run_periodic_check():
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from app.models.source import Source
            from datetime import datetime, timedelta
            
            # Get sources that need checking based on scrape_frequency
            result = await db.execute(
                select(Source)
                .where(Source.is_active == True)
            )
            sources = result.scalars().all()
            
            checked = 0
            changes_found = 0
            
            for source in sources:
                # Check if it's time to scrape based on frequency
                if source.last_scraped_at:
                    hours_since_last = (datetime.utcnow() - source.last_scraped_at).total_seconds() / 3600
                    if hours_since_last < source.scrape_frequency:
                        continue  # Not yet time to check
                
                # Queue change detection task
                detect_changes_task.delay(source.id)
                checked += 1
            
            return {
                "sources_checked": checked,
                "timestamp": datetime.utcnow().isoformat(),
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run_periodic_check())
