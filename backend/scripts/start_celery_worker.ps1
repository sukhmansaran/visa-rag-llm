# Start a Celery worker on Windows (requires Redis/Memurai on localhost:6379 and Ollama running).
#
#   cd backend
#   .\scripts\start_celery_worker.ps1                                # one worker for every queue
#   .\scripts\start_celery_worker.ps1 -Role answers -Name answers1   # recommended: chat answers only...
#   .\scripts\start_celery_worker.ps1 -Role background -Name bg1     # ...plus one for everything else
#
# --pool=solo: Celery's default prefork pool does not run on Windows. Solo runs one task at a time
# per process, which is also what the per-task event loop / DB-pool cleanup in
# app/workers/async_runner.py assumes. For parallelism, start more processes with different names.
#
# Why two roles (2026-10-15 review, B7): with one solo worker, a long ingestion or crawl holds the only
# process and chat answers wait behind it (and give up after JOB_QUEUED_GIVE_UP_SECONDS). An answers-only
# worker keeps chat responsive. Model calls from both still share Ollama through the machine-wide slots.
param(
    [string]$Name = "worker1",
    [ValidateSet("all", "answers", "background")]
    [string]$Role = "all",
    [string]$LogLevel = "info"
)

# Not "Stop": in Windows PowerShell 5.1 that turns any stderr line from python.exe into a fatal error
$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend

$queues = switch ($Role) {
    "answers"    { "answers" }
    "background" { "default,ingestion,changes,crawler" }
    default      { "default,answers,ingestion,changes,crawler" }
}
Write-Host "Starting Celery worker '$Name' (role: $Role, queues: $queues)"

& "$backend\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app worker `
    --pool=solo `
    --queues=$queues `
    --hostname="$Name@%h" `
    --loglevel=$LogLevel
