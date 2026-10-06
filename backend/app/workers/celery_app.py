from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "visa_chatbot",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    task_soft_time_limit=3000,  # 50 minutes
)

# Import beat schedule from config
from app.workers.celery_config import beat_schedule, task_routes

# Celery Beat schedule for periodic tasks
celery_app.conf.beat_schedule = beat_schedule
celery_app.conf.task_routes = task_routes

# Note: Tasks are imported lazily to avoid circular imports
# They will be auto-discovered when celery worker starts
