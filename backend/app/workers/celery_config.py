"""
Celery Beat schedule configuration.
"""

from celery.schedules import crontab


# Celery Beat Schedule
beat_schedule = {
    # Scrape high-priority sources every 6 hours
    'scrape-high-priority-sources': {
        'task': 'app.workers.tasks.scrape_high_priority_sources_task',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    
    # Scrape medium-priority sources daily
    'scrape-medium-priority-sources': {
        'task': 'app.workers.tasks.scrape_medium_priority_sources_task',
        'schedule': crontab(minute=0, hour=2),  # Daily at 2 AM
    },
    
    # Scrape low-priority sources weekly
    'scrape-low-priority-sources': {
        'task': 'app.workers.tasks.scrape_low_priority_sources_task',
        'schedule': crontab(minute=0, hour=3, day_of_week=0),  # Sunday at 3 AM
    },
    
    # Check for changes in all sources daily
    'detect-changes-all-sources': {
        'task': 'app.workers.tasks.detect_changes_all_sources_task',
        'schedule': crontab(minute=0, hour=4),  # Daily at 4 AM
    },
    
    # Clean up old logs weekly
    'cleanup-old-logs': {
        'task': 'app.workers.tasks.cleanup_old_logs_task',
        'schedule': crontab(minute=0, hour=5, day_of_week=0),  # Sunday at 5 AM
    },
    
    # Generate weekly digest for users
    'send-weekly-digest': {
        'task': 'app.workers.tasks.send_weekly_digest_task',
        'schedule': crontab(minute=0, hour=9, day_of_week=1),  # Monday at 9 AM
    },

    # Crawler Pipeline schedules
    # Government visa sites every 7 days (Sunday at 1 AM)
    'crawl-government-visa-sites': {
        'task': 'app.workers.crawler_tasks.start_crawl_job_task',
        'schedule': crontab(minute=0, hour=1, day_of_week=0),
        'kwargs': {'seed_urls': [], 'config': {'category_filter': ['government_portal']}, 'tier': 3},
    },
    # University deadline pages every 30 days (1st of month at 2 AM)
    'crawl-university-deadlines': {
        'task': 'app.workers.crawler_tasks.start_crawl_job_task',
        'schedule': crontab(minute=0, hour=2, day_of_month=1),
        'kwargs': {'seed_urls': [], 'config': {'category_filter': ['admissions_system']}, 'tier': 2},
    },
    # Immigration news every 24 hours (daily at 6 AM)
    'crawl-immigration-news': {
        'task': 'app.workers.crawler_tasks.start_crawl_job_task',
        'schedule': crontab(minute=0, hour=6),
        'kwargs': {'seed_urls': [], 'config': {'category_filter': ['news']}, 'tier': 5},
    },
}


# Task routing
task_routes = {
    'app.workers.tasks.ingest_source_task': {'queue': 'ingestion'},
    'app.workers.tasks.detect_changes_task': {'queue': 'changes'},
    'app.workers.crawler_tasks.*': {'queue': 'crawler'},
    'app.workers.tasks.*': {'queue': 'default'},
}


# Task time limits
task_time_limit = 3600  # 1 hour
task_soft_time_limit = 3000  # 50 minutes
