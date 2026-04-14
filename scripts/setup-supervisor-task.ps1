# Create or update the Task Scheduler task for the unified PC Agent Supervisor.
# Replaces the three individual tasks (activity detector, ambient monitor,
# screen sync) with a single supervisor process.
#
# Must run as admin (elevated PowerShell).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-supervisor-task.ps1

$TaskName = "Home Hub Agent Supervisor"
$ProjectRoot = "C:\Users\antho\Desktop\home-hub"
$PythonW = "$ProjectRoot\venv\Scripts\pythonw.exe"
$Arguments = "-m backend.services.pc_agent.supervisor --server http://192.168.1.210:8000 --classifier --shadow"

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
    -Execute $PythonW `
    -Argument $Arguments `
    -WorkingDirectory $ProjectRoot

# Trigger: on logon with 30s delay (let network settle)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT30S"

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
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Unified supervisor for Home Hub PC agents (activity detector, ambient monitor, screen sync). Reports to Latitude 192.168.1.210."

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Key settings:" -ForegroundColor Cyan
Write-Host "  - Trigger: At logon (30s delay)"
Write-Host "  - Manages: activity_detector, ambient_monitor, screen_sync"
Write-Host "  - Classifier: YAMNet (shadow mode)"
Write-Host "  - StopIfGoingOnBatteries: False"
Write-Host "  - Restart on failure: 999 times, 1 min apart"
Write-Host "  - Multiple instances: Ignore new (mutex also prevents duplicates)"
Write-Host ""
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "Logs: $ProjectRoot\logs\supervisor.log" -ForegroundColor Yellow
