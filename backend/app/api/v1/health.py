import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import redis.asyncio as redis

from app.core.database import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/db")
async def health_check_db(db: AsyncSession = Depends(get_db)):
    """Check database connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check DB failure: {e}", exc_info=True)
        return {"status": "unhealthy", "database": "disconnected"}


@router.get("/redis")
async def health_check_redis():
    """Check Redis connectivity."""
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        await redis_client.ping()
        await redis_client.close()
        return {"status": "healthy", "redis": "connected"}
    except Exception as e:
        logger.error(f"Health check Redis failure: {e}", exc_info=True)
        return {"status": "unhealthy", "redis": "disconnected"}
