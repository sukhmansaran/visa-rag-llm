"""
Celery Beat schedule configuration.
"""

from celery.schedules import crontab


# Celery Beat Schedule
beat_schedule = {
    # Scrape high-priority sources every 6 hours
    'scrape-high-priority-sources': {
        'task': 'app.workers.periodic_tasks.scrape_high_priority_sources_task',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    
    # Scrape medium-priority sources daily
    'scrape-medium-priority-sources': {
        'task': 'app.workers.periodic_tasks.scrape_medium_priority_sources_task',
        'schedule': crontab(minute=0, hour=2),  # Daily at 2 AM
    },
    
    # Scrape low-priority sources weekly
    'scrape-low-priority-sources': {
        'task': 'app.workers.periodic_tasks.scrape_low_priority_sources_task',
        'schedule': crontab(minute=0, hour=3, day_of_week=0),  # Sunday at 3 AM
    },
    
    # Check for changes in all sources daily
    'detect-changes-all-sources': {
        'task': 'app.workers.periodic_tasks.detect_changes_all_sources_task',
        'schedule': crontab(minute=0, hour=4),  # Daily at 4 AM
    },
    
    # Clean up old logs weekly
    'cleanup-old-logs': {
        'task': 'app.workers.periodic_tasks.cleanup_old_logs_task',
        'schedule': crontab(minute=0, hour=5, day_of_week=0),  # Sunday at 5 AM
    },
    
    # Generate weekly digest for users
    'send-weekly-digest': {
        'task': 'app.workers.periodic_tasks.send_weekly_digest_task',
        'schedule': crontab(minute=0, hour=9, day_of_week=1),  # Monday at 9 AM
    },

    # Crawler Pipeline schedules
    # Government visa sites every 7 days (Sunday at 1 AM)
    'crawl-government-visa-sites': {
        'task': 'app.workers.crawler_tasks.crawl_category_task',
        'schedule': crontab(minute=0, hour=1, day_of_week=0),
        'kwargs': {'categories': ['government_portal']},
    },
    # University deadline pages every 30 days (1st of month at 2 AM)
    'crawl-university-deadlines': {
        'task': 'app.workers.crawler_tasks.crawl_category_task',
        'schedule': crontab(minute=0, hour=2, day_of_month=1),
        'kwargs': {'categories': ['admissions_system']},
    },
    # Immigration news every 24 hours (daily at 6 AM)
    'crawl-immigration-news': {
        'task': 'app.workers.crawler_tasks.crawl_category_task',
        'schedule': crontab(minute=0, hour=6),
        'kwargs': {'categories': ['news']},
    },
}


# Task routing
task_routes = {
    'app.workers.tasks.ingest_source_task': {'queue': 'ingestion'},
    'app.workers.tasks.detect_changes_task': {'queue': 'changes'},
    'app.workers.crawler_tasks.*': {'queue': 'crawler'},
    'app.workers.tasks.*': {'queue': 'default'},
    'app.workers.periodic_tasks.*': {'queue': 'default'},
}


# Task time limits
task_time_limit = 3600  # 1 hour
task_soft_time_limit = 3000  # 50 minutes
