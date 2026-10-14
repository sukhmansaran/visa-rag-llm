# Start a Celery worker on Windows (requires Redis/Memurai on localhost:6379 and Ollama running).
#
#   cd backend
#   .\scripts\start_celery_worker.ps1            # one worker
#   .\scripts\start_celery_worker.ps1 -Name w2   # start a second process for more parallelism
#
# --pool=solo: Celery's default prefork pool does not run on Windows. Solo runs one task at a time
# per process, which is also what the per-task event loop / DB-pool cleanup in
# app/workers/async_runner.py assumes. For parallelism, start more processes with different names.
param(
    [string]$Name = "worker1",
    [string]$LogLevel = "info"
)

# Not "Stop": in Windows PowerShell 5.1 that turns any stderr line from python.exe into a fatal error
$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend

& "$backend\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app worker `
    --pool=solo `
    --queues=default,answers,ingestion,changes,crawler `
    --hostname="$Name@%h" `
    --loglevel=$LogLevel
