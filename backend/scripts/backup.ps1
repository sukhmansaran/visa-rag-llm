# Back up the Pendu database + knowledge base and prove the backup restores (M0.16).
#
#   cd backend
#   .\scripts\backup.ps1                    # label "scheduled"
#   .\scripts\backup.ps1 -Label pre_demo
#
# Backups go outside the repo (PENDU_BACKUP_DIR, default ..\..\..\db_backups); the newest 20 sets are kept
# (PENDU_BACKUP_KEEP). Each backup is restored into a throwaway database and its row counts compared; exit code 1
# if anything fails, so Task Scheduler shows it.
#
# Daily at 02:00 with Windows Task Scheduler (run once, in PowerShell; adjust the path):
#   $backend = "D:\projects\llm chatbot\llm chatbot\pendu\backend"
#   $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
#                -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backend\scripts\backup.ps1`"" -WorkingDirectory $backend
#   Register-ScheduledTask -TaskName "Pendu backup" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 2am)
# PostgreSQL must be running at that time; the task is skipped (not failed) if the PC is off.
param(
    [string]$Label = "scheduled"
)

# Not "Stop": in Windows PowerShell 5.1 that turns any stderr line from python.exe into a fatal error
$ErrorActionPreference = "Continue"
$backend = Split-Path -Parent $PSScriptRoot
Set-Location $backend
$py = "$backend\.venv\Scripts\python.exe"

& $py scripts\backup_now.py --label $Label
if ($LASTEXITCODE -ne 0) { Write-Host "BACKUP FAILED"; exit 1 }

& $py scripts\backup_now.py --verify latest
if ($LASTEXITCODE -ne 0) { Write-Host "BACKUP DID NOT RESTORE CLEANLY"; exit 1 }

Write-Host "Backup done and verified."
exit 0
