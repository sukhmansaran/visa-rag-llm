# Local gate before every commit (M0.8). Runs what CI cannot (live Ollama tests, the answer-quality
# regression gate) plus the same checks CI runs, and prints one PASS/FAIL summary. Exit code 0 = PASS.
#
# Usage (from backend/):
#   .\scripts\check_before_commit.ps1               # quick eval gate; frontend checks only if frontend files changed
#   .\scripts\check_before_commit.ps1 -FullEval     # full eval gate (all cases x 3 runs; ~1 hour on CPU) - before merging a milestone
#   .\scripts\check_before_commit.ps1 -Frontend     # force the frontend checks
#   .\scripts\check_before_commit.ps1 -SkipEval     # only when the change cannot affect answers (say so in the PR)
# Needs: PostgreSQL, Redis and Ollama running.

param(
    [switch]$FullEval,
    [switch]$Frontend,
    [switch]$SkipEval
)

$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $backend
$frontendDir = Join-Path $repo "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$results = [System.Collections.ArrayList]::new()
$started = Get-Date

function Run-Step([string]$name, [scriptblock]$action) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    $t0 = Get-Date
    & $action
    $code = $LASTEXITCODE
    $seconds = [int]((Get-Date) - $t0).TotalSeconds
    $status = if ($code -eq 0) { "PASS" } else { "FAIL" }
    [void]$results.Add([pscustomobject]@{ Step = $name; Result = $status; Seconds = $seconds })
}

function Skip-Step([string]$name, [string]$reason) {
    [void]$results.Add([pscustomobject]@{ Step = $name; Result = "SKIP ($reason)"; Seconds = 0 })
}

Set-Location $backend

# Ollama must be up: otherwise the live tests skip silently and the eval gate cannot run
$ollamaUp = $true
try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:11434/api/version" | Out-Null } catch { $ollamaUp = $false }

Run-Step "flake8 syntax gate (as CI)" {
    & $py -m flake8 app alembic tests --count --select=E9,F63,F7,F82 --show-source --statistics
}

if ($ollamaUp) {
    Run-Step "backend tests incl. live Ollama" { & $py -m pytest -q -p no:cacheprovider }
} else {
    [void]$results.Add([pscustomobject]@{ Step = "backend tests incl. live Ollama"; Result = "FAIL (Ollama not running)"; Seconds = 0 })
}

Run-Step "pip-audit (as CI)" {
    & $py -m pip_audit -r requirements.txt --progress-spinner off `
        --ignore-vuln PYSEC-2026-3813 --ignore-vuln PYSEC-2026-3814 --ignore-vuln PYSEC-2026-3815
}

if ($SkipEval) {
    Skip-Step "answer-quality gate" "-SkipEval"
} elseif (-not $ollamaUp) {
    [void]$results.Add([pscustomobject]@{ Step = "answer-quality gate"; Result = "FAIL (Ollama not running)"; Seconds = 0 })
} elseif ($FullEval) {
    Run-Step "answer-quality gate (full)" { & $py scripts\eval_gate.py --full }
} else {
    Run-Step "answer-quality gate (quick)" { & $py scripts\eval_gate.py }
}

# Frontend checks when frontend files changed (vs origin/main, including uncommitted work) or when forced
Set-Location $repo
$changed = @(git diff --name-only origin/main 2>$null) + @(git ls-files --others --exclude-standard 2>$null)
$frontendChanged = $Frontend -or ($changed | Where-Object { $_ -like "frontend/*" })
if ($frontendChanged) {
    Set-Location $frontendDir
    Run-Step "frontend lint" { pnpm run lint }
    Run-Step "frontend type-check" { pnpm exec tsc --noEmit }
    Run-Step "frontend build" { pnpm run build }
    Run-Step "frontend audit (as CI)" { pnpm audit --prod --audit-level high }
} else {
    Skip-Step "frontend checks" "no frontend changes"
}
Set-Location $backend

Write-Host ""
Write-Host ("=" * 72)
$results | Format-Table -AutoSize | Out-String | Write-Host
$failed = @($results | Where-Object { $_.Result -like "FAIL*" })
$minutes = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
if ($failed.Count -eq 0) {
    Write-Host "OVERALL: PASS ($minutes min)" -ForegroundColor Green
    exit 0
}
Write-Host "OVERALL: FAIL - $($failed.Count) step(s) failed ($minutes min)" -ForegroundColor Red
exit 1
