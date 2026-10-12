from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "visa_chatbot",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # Task modules must be listed so a worker started with `-A app.workers.celery_app` registers them;
    # without this the worker rejected every job as "unregistered task".
    include=[
        "app.workers.tasks",
        "app.workers.periodic_tasks",
        "app.workers.crawler_tasks",
    ],
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
    # Unrouted tasks go to "default" (a worker consumes: default, ingestion, changes, crawler)
    task_default_queue="default",
    # Redeliver a task if the worker dies mid-run instead of silently losing it
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# Import beat schedule from config
from app.workers.celery_config import beat_schedule, task_routes

# Celery Beat schedule for periodic tasks
celery_app.conf.beat_schedule = beat_schedule
celery_app.conf.task_routes = task_routes

# Windows: the default prefork pool is unsupported. Run workers with `--pool=solo`
# (one task at a time per process; start more processes for parallelism). See scripts/start_celery_worker.ps1.
