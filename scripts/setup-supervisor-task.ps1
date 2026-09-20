# Create or update the Task Scheduler task for the unified PC Agent Supervisor.
# Replaces obsolete individual-agent tasks with one supervisor process that owns
# all seven Windows agents. Installs the windowless launcher pair under
# %LOCALAPPDATA%\home-hub so the scheduled task does not depend on stale
# machine-specific Python paths.
#
# Must run as admin (elevated PowerShell).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-supervisor-task.ps1

$TaskName = "Home Hub Agent Supervisor"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$RuntimeDir = Join-Path $env:LOCALAPPDATA "home-hub"
$RuntimePowerShell = Join-Path $RuntimeDir "start-supervisor.ps1"
$RuntimeVbs = Join-Path $RuntimeDir "start-supervisor-hidden.vbs"

if (-not (Test-Path -LiteralPath $PythonW)) {
    throw "Home Hub .venv pythonw.exe was not found at $PythonW"
}

# Install the two checked-in launchers into the stable machine-local runtime
# directory. start-supervisor.ps1 detects the repository from the Scheduled
# Task's WorkingDirectory when running from LocalAppData.
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
Copy-Item (Join-Path $PSScriptRoot "start-supervisor.ps1") $RuntimePowerShell -Force
Copy-Item (Join-Path $PSScriptRoot "start-supervisor-hidden.vbs") $RuntimeVbs -Force

# Action chain at fire time:
#   wscript.exe (windowless from process creation)
#     -> %LOCALAPPDATA%\home-hub\start-supervisor-hidden.vbs
#       -> %LOCALAPPDATA%\home-hub\start-supervisor.ps1
#         -> <repo>\.venv\Scripts\pythonw.exe
#         -> backend.services.pc_agent.supervisor
#
# The Python 3.13 venv launcher may appear as a launcher + interpreter process
# pair. That is expected; the Windows mutex and backend supervisor identity are
# the singleton/runtime-health authority.
$Executable = "$env:WINDIR\System32\wscript.exe"
$Arguments = "`"$RuntimeVbs`""

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
$AgentModules = @(
    "activity_detector",
    "ambient_monitor",
    "screen_sync_agent",
    "sleep_watcher",
    "emotion_capture",
    "monitor_brightness",
    "peripheral_rgb",
    "supervisor"
)
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
    -Description "Unified supervisor for seven Home Hub Windows agents: activity, ambient audio, screen sync, sleep watcher, emotion capture, monitor brightness, and peripheral RGB. Reports to Latitude 192.168.86.210."

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Key settings:" -ForegroundColor Cyan
Write-Host "  - Trigger 1: At logon (30s delay)"
Write-Host "  - Trigger 2: Watchdog - every 5 min, indefinitely"
Write-Host "  - Manages: activity_detector, ambient_monitor, screen_sync, sleep_watcher, emotion_capture, monitor_brightness, peripheral_rgb"
Write-Host "  - Classifier: YAMNet (active mode)"
Write-Host "  - Runtime launcher: $RuntimeVbs"
Write-Host "  - Python: $PythonW"
Write-Host "  - StopIfGoingOnBatteries: False"
Write-Host "  - Restart on failure: 999 times, 1 min apart"
Write-Host "  - Multiple instances: Ignore new (mutex also prevents duplicates)"
Write-Host ""
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "Logs: $ProjectRoot\logs\supervisor.log" -ForegroundColor Yellow
