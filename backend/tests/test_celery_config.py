"""
Celery wiring regression tests (problem #3).

Previously: the worker registered 0 tasks (no `include=`), and 6 of 9 Beat entries pointed at
`app.workers.tasks.*` while the tasks live in `app.workers.periodic_tasks.*`, so scheduled
scrapes, change detection, cleanup and the weekly digest never ran.
"""

from app.workers.celery_app import celery_app

def _role_queues() -> dict:
    """The queues each worker role consumes, read from its start script (the source of truth)."""
    import re
    from pathlib import Path

    script = (Path(__file__).resolve().parent.parent / "scripts" / "start_celery_worker.ps1").read_text(encoding="utf-8")
    roles = dict(re.findall(r'"(answers|background)"\s*\{\s*"([\w,]+)"\s*\}', script))
    default = re.search(r'default\s*\{\s*"([\w,]+)"\s*\}', script)
    assert len(roles) == 2 and default, "start_celery_worker.ps1 must map -Role answers/background/all to --queues"
    roles["all"] = default.group(1)
    return {role: set(queues.split(",")) for role, queues in roles.items()}


ROLE_QUEUES = _role_queues()


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
    """Both setups (one `-Role all` worker, or `answers` + `background`) must run every task."""
    for setup, queues in {"all": ROLE_QUEUES["all"],
                          "answers+background": ROLE_QUEUES["answers"] | ROLE_QUEUES["background"]}.items():
        unrouted = {name: _queue_for(name) for name in _registered_tasks() if _queue_for(name) not in queues}
        assert not unrouted, f"{setup}: tasks routed to queues no worker consumes: {unrouted}"


def test_answers_worker_serves_only_answers():
    """Long background tasks never hold the answers worker (2026-10-15 review, B7)."""
    assert ROLE_QUEUES["answers"] == {"answers"}
    assert "answers" not in ROLE_QUEUES["background"]


def test_scheduled_crawls_use_database_seeds():
    crawl_entries = [e for e in celery_app.conf.beat_schedule.values() if "crawler_tasks" in e["task"]]
    assert crawl_entries
    for entry in crawl_entries:
        assert entry["task"] == "app.workers.crawler_tasks.crawl_category_task"
        assert entry["kwargs"]["categories"], "scheduled crawl must name portal categories"
