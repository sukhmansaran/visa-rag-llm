# Start all of Pendu with one command (M0.17).
#
#   cd backend
#   .\scripts\start_all.ps1                 # check everything, then start it
#   .\scripts\start_all.ps1 -NoFrontend     # backend only
#   .\scripts\start_all.ps1 -NoWorkers      # API (+ frontend) only: the web chat needs the answers worker
#
# 1. scripts/preflight.py checks PostgreSQL (and migrations), Redis, Ollama (and the pinned model builds), settings,
#    the knowledge base, frontend packages and ports. Anything that would stop Pendu working stops here, with the fix.
# 2. Opens one titled window each for: the API, the answers worker, the background worker, the scheduler (beat)
#    and the frontend. Close a window to stop that part; close them all to stop Pendu.
# 3. Waits for the API's /health and prints the URLs.
param(
    [switch]$NoFrontend,
    [switch]$NoWorkers,
    [switch]$Reload,          # API auto-reload on code changes (development)
    [int]$HealthTimeoutSeconds = 90
)

# Not "Stop": in Windows PowerShell 5.1 that turns any stderr line from python.exe into a fatal error
$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path (Split-Path -Parent $backend) "frontend"
$py = "$backend\.venv\Scripts\python.exe"
Set-Location $backend

if (-not (Test-Path $py)) {
    Write-Host "backend\.venv not found. Create it first (README, Quick start: python -m venv .venv; pip install -r requirements.txt)."
    exit 1
}

Write-Host "Checking what Pendu needs..." -ForegroundColor Cyan
& $py scripts\preflight.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not started: fix the problems above, then run this again." -ForegroundColor Red
    exit 1
}

function Start-PenduWindow([string]$Title, [string]$Directory, [string]$Command) {
    # A separate PowerShell window that stays open (so errors stay readable) and shows its role in the title
    $script = "`$Host.UI.RawUI.WindowTitle = 'Pendu - $Title'; Set-Location '$Directory'; $Command"
    Start-Process powershell.exe -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                                 "-Command", $script) | Out-Null
    Write-Host "  started: $Title"
}

Write-Host "`nStarting Pendu..." -ForegroundColor Cyan
$reloadFlag = if ($Reload) { "--reload" } else { "" }
Start-PenduWindow "API (port 8000)" $backend "& '$py' -m uvicorn app.main:app --port 8000 $reloadFlag"

if (-not $NoWorkers) {
    Start-PenduWindow "answers worker" $backend ".\scripts\start_celery_worker.ps1 -Role answers -Name answers1"
    Start-PenduWindow "background worker" $backend ".\scripts\start_celery_worker.ps1 -Role background -Name bg1"
    Start-PenduWindow "scheduler (beat)" $backend ".\scripts\start_celery_beat.ps1"
}

if (-not $NoFrontend) {
    # node runs Next.js directly: pnpm.exe can be blocked by Windows application control on this machine
    Start-PenduWindow "frontend (port 3000)" $frontend "node node_modules\next\dist\bin\next dev"
}

Write-Host "`nWaiting for the API..." -NoNewline
$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
$health = $null
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
        break
    } catch {
        Start-Sleep -Seconds 2
        Write-Host "." -NoNewline
    }
}
Write-Host ""

if ($null -eq $health) {
    Write-Host "The API did not answer within $HealthTimeoutSeconds s: look at the 'Pendu - API' window." -ForegroundColor Red
    exit 1
}
if ($health.models -and $health.models.ok -eq $false) {
    Write-Host "API is up, but the model builds differ from their pins (see the API window)." -ForegroundColor Yellow
} else {
    Write-Host "API is up." -ForegroundColor Green
}

Write-Host ""
Write-Host "  API:       http://localhost:8000      (docs: http://localhost:8000/docs)"
if (-not $NoFrontend) { Write-Host "  Web app:   http://localhost:3000      (the first page load compiles; give it a moment)" }
if ($NoWorkers) { Write-Host "  Note: no workers started, so the web chat will wait for the answer service." -ForegroundColor Yellow }
Write-Host ""
Write-Host "Close the 'Pendu - ...' windows to stop it."
exit 0
