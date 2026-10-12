# Start Celery Beat (the scheduler) on Windows. Run exactly ONE beat process.
#
#   cd backend
#   .\scripts\start_celery_beat.ps1
#
# Beat only enqueues scheduled jobs; a worker (scripts/start_celery_worker.ps1) must be running to execute them.
# The schedule state file lives in logs/ (git-ignored).
param(
    [string]$LogLevel = "info"
)

# Not "Stop": in Windows PowerShell 5.1 that turns any stderr line from python.exe into a fatal error
$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend
New-Item -ItemType Directory -Force -Path "$backend\logs" | Out-Null

& "$backend\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app beat `
    --schedule="$backend\logs\celerybeat-schedule" `
    --loglevel=$LogLevel
