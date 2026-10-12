"""
Celery wiring regression tests (problem #3).

Previously: the worker registered 0 tasks (no `include=`), and 6 of 9 Beat entries pointed at
`app.workers.tasks.*` while the tasks live in `app.workers.periodic_tasks.*`, so scheduled
scrapes, change detection, cleanup and the weekly digest never ran.
"""

from app.workers.celery_app import celery_app

WORKER_QUEUES = {"default", "ingestion", "changes", "crawler"}


def _registered_tasks():
    # What a worker does at startup: import every module listed in `include`
    celery_app.loader.import_default_modules()
    return {name for name in celery_app.tasks if not name.startswith("celery.")}


def _queue_for(task_name: str) -> str:
    route = celery_app.amqp.router.route({}, task_name)
    return route["queue"].name


def test_worker_registers_all_task_modules():
    registered = _registered_tasks()
    for module in ("app.workers.tasks.", "app.workers.periodic_tasks.", "app.workers.crawler_tasks."):
        assert any(name.startswith(module) for name in registered), f"No tasks registered from {module}"


def test_every_beat_entry_points_at_a_registered_task():
    registered = _registered_tasks()
    missing = {
        entry_name: entry["task"]
        for entry_name, entry in celery_app.conf.beat_schedule.items()
        if entry["task"] not in registered
    }
    assert not missing, f"Beat entries reference unregistered tasks: {missing}"


def test_every_task_is_routed_to_a_queue_the_worker_consumes():
    unrouted = {name: _queue_for(name) for name in _registered_tasks() if _queue_for(name) not in WORKER_QUEUES}
    assert not unrouted, f"Tasks routed to queues no worker consumes: {unrouted}"


def test_scheduled_crawls_use_database_seeds():
    crawl_entries = [e for e in celery_app.conf.beat_schedule.values() if "crawler_tasks" in e["task"]]
    assert crawl_entries
    for entry in crawl_entries:
        assert entry["task"] == "app.workers.crawler_tasks.crawl_category_task"
        assert entry["kwargs"]["categories"], "scheduled crawl must name portal categories"
