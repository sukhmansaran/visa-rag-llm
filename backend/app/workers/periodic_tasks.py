"""
Periodic Celery tasks for scheduled operations.
"""

import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from app.workers.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.source import Source
from app.workers.tasks import ingest_source_task, detect_changes_task


@celery_app.task
def scrape_high_priority_sources_task():
    """Scrape high-priority sources (priority 1)."""
    
    async def run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Source)
                .where(Source.is_active == True)
                .where(Source.priority == 1)
            )
            sources = result.scalars().all()
            
            count = 0
            for source in sources:
                # Queue ingestion task
                ingest_source_task.delay(source.id)
                count += 1
            
            return {
                "status": "queued",
                "sources_queued": count,
                "priority": 1,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run())


@celery_app.task
def scrape_medium_priority_sources_task():
    """Scrape medium-priority sources (priority 2)."""
    
    async def run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Source)
                .where(Source.is_active == True)
                .where(Source.priority == 2)
            )
            sources = result.scalars().all()
            
            count = 0
            for source in sources:
                ingest_source_task.delay(source.id)
                count += 1
            
            return {
                "status": "queued",
                "sources_queued": count,
                "priority": 2,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run())


@celery_app.task
def scrape_low_priority_sources_task():
    """Scrape low-priority sources (priority 3+)."""
    
    async def run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Source)
                .where(Source.is_active == True)
                .where(Source.priority >= 3)
            )
            sources = result.scalars().all()
            
            count = 0
            for source in sources:
                ingest_source_task.delay(source.id)
                count += 1
            
            return {
                "status": "queued",
                "sources_queued": count,
                "priority": "3+",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run())


@celery_app.task
def detect_changes_all_sources_task():
    """Check all sources for changes."""
    
    async def run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Source)
                .where(Source.is_active == True)
            )
            sources = result.scalars().all()
            
            count = 0
            for source in sources:
                # Only check if last scraped
                if source.last_scraped_at:
                    detect_changes_task.delay(source.id)
                    count += 1
            
            return {
                "status": "queued",
                "sources_checked": count,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run())


@celery_app.task
def cleanup_old_logs_task():
    """Clean up old log files (older than 30 days)."""
    
    import os
    from pathlib import Path
    
    log_dir = Path("logs")
    if not log_dir.exists():
        return {"status": "skipped", "reason": "log directory not found"}
    
    cutoff_date = datetime.now() - timedelta(days=30)
    deleted_count = 0
    
    for log_file in log_dir.glob("*.log.*"):  # Rotated logs
        if log_file.stat().st_mtime < cutoff_date.timestamp():
            log_file.unlink()
            deleted_count += 1
    
    return {
        "status": "completed",
        "files_deleted": deleted_count,
        "timestamp": datetime.utcnow().isoformat()
    }


@celery_app.task
def send_weekly_digest_task():
    """Send weekly digest to users with watchlist updates."""
    
    async def run():
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select, distinct
            from app.models.watchlist import Watchlist
            from app.models.notification import Notification
            from app.models.user import User
            
            # Get users with watchlist items
            result = await db.execute(
                select(distinct(Watchlist.user_id))
            )
            user_ids = [row[0] for row in result.all()]
            
            digest_count = 0
            for user_id in user_ids:
                # Get unread notifications from last week
                week_ago = datetime.utcnow() - timedelta(days=7)
                result = await db.execute(
                    select(Notification)
                    .where(Notification.user_id == user_id)
                    .where(Notification.is_read == False)
                    .where(Notification.created_at >= week_ago)
                )
                notifications = result.scalars().all()
                
                if notifications:
                    # TODO: Send email digest
                    # For now, just create a summary notification
                    summary = Notification(
                        user_id=user_id,
                        title="Weekly Digest",
                        message=f"You have {len(notifications)} unread updates this week.",
                        notification_type="system"
                    )
                    db.add(summary)
                    digest_count += 1
            
            await db.commit()
            
            return {
                "status": "completed",
                "digests_sent": digest_count,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run())
