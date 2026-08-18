# Create or update the Task Scheduler task for the unified PC Agent Supervisor.
# Replaces the three individual tasks (activity detector, ambient monitor,
# screen sync) with a single supervisor process.
#
# Must run as admin (elevated PowerShell).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-supervisor-task.ps1

$TaskName = "Home Hub Agent Supervisor"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Action chain at fire time:
#   wscript.exe (windowless from process creation)
#     -> start-supervisor-hidden.vbs (Run "...", 0, False -> hidden powershell)
#       -> start-supervisor.ps1 (sets PYTHONPATH + workdir)
#         -> C:\Python313\pythonw.exe -m backend.services.pc_agent.supervisor
#
# Why wscript + VBS instead of plain powershell.exe -WindowStyle Hidden:
# the -WindowStyle flag only hides AFTER PowerShell creates its console
# window, so each 5-min watchdog fire flashed a window briefly. wscript
# never creates one, and its Run state 0 enforces hidden at CreateProcess
# time on the powershell child too. No flash possible. Switched
# 2026-05-16 after the watchdog landed.
#
# (System Python with PYTHONPATH set in the .ps1 still avoids Python 3.13's
# venv launcher-subprocess duplicate-pythonw issue noted previously.)
$Executable = "wscript.exe"
$Arguments = "`"$ProjectRoot\scripts\start-supervisor-hidden.vbs`""

# ── Remove old individual tasks ────────────────────────────────────────
$OldTasks = @(
    "Home Hub PC Activity Detector",
    "Home Hub Ambient Monitor",
    "Home Hub Screen Sync Agent"
)
foreach ($old in $OldTasks) {
    $existing = Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Removing old task '$old'..."
        Stop-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $old -Confirm:$false
    }
}

# ── Kill any orphaned pythonw agent processes ──────────────────────────
Write-Host "Killing orphaned agent processes..."
$AgentModules = @("activity_detector", "ambient_monitor", "screen_sync_agent", "supervisor")
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | ForEach-Object {
    foreach ($mod in $AgentModules) {
        if ($_.CommandLine -match $mod) {
            Write-Host "  Killing PID $($_.ProcessId) ($mod)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            break
        }
    }
}
Start-Sleep -Seconds 1

# ── Remove existing supervisor task if present ─────────────────────────
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ── Create the new supervisor task ─────────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute $Executable `
    -Argument $Arguments `
    -WorkingDirectory $ProjectRoot

# Trigger 1: on logon with 30s delay (let network settle).
$loginTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$loginTrigger.Delay = "PT30S"

# Trigger 2: 5-minute watchdog. Combined with MultipleInstances=IgnoreNew
# below, this is a safe self-heal - Task Scheduler tries to launch every
# 5 min; if the supervisor is already running it skips, if it died (or
# was killed externally) it starts a fresh one.
#
# Why this is needed in addition to RestartCount=999 on failure: the
# failure-restart only fires when Task Scheduler observed the task's
# launcher exit with non-zero. External kills (e.g. a bash background
# wrapper getting reaped with its Claude session - observed 2026-05-15
# -> 17h apartment stuck in idle) leave Task Scheduler unaware that
# anything should be running. The polling trigger catches that class.
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -Hidden

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($loginTrigger, $watchdogTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description "Unified supervisor for Home Hub PC agents (activity detector, ambient monitor, screen sync). Reports to Latitude 192.168.86.210."

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Key settings:" -ForegroundColor Cyan
Write-Host "  - Trigger 1: At logon (30s delay)"
Write-Host "  - Trigger 2: Watchdog - every 5 min, indefinitely"
Write-Host "  - Manages: activity_detector, ambient_monitor, screen_sync"
Write-Host "  - Classifier: YAMNet (shadow mode)"
Write-Host "  - StopIfGoingOnBatteries: False"
Write-Host "  - Restart on failure: 999 times, 1 min apart"
Write-Host "  - Multiple instances: Ignore new (mutex also prevents duplicates)"
Write-Host ""
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "Logs: $ProjectRoot\logs\supervisor.log" -ForegroundColor Yellow
