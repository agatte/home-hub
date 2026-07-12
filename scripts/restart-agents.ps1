# Restart the PC Agent Supervisor on the dev machine.
# Kills any existing supervisor/agent processes and starts fresh.
#
# Usage: powershell -File scripts\restart-agents.ps1

$ProjectRoot = "C:\Users\antho\Desktop\home-hub"
$LogFile = Join-Path $ProjectRoot "logs\supervisor.log"
$TaskName = "Home Hub Agent Supervisor"

function Stop-AgentProcess {
    param(
        [Parameter(Mandatory=$true)] $Process,
        [Parameter(Mandatory=$true)] [string] $Module
    )

    Write-Host "  Killing PID $($Process.ProcessId) ($Module)"
    try {
        Stop-Process -Id $Process.ProcessId -Force -ErrorAction Stop
    } catch {
        # Some wedged pythonw.exe instances can remain visible to WMI while
        # Stop-Process/taskkill cannot resolve them. WMI termination has cleaned
        # up that limbo state in practice.
        try {
            $result = $Process | Invoke-CimMethod -MethodName Terminate -ErrorAction Stop
            if ($null -ne $result -and $result.ReturnValue -ne 0) {
                Write-Host "    WMI terminate returned $($result.ReturnValue)"
            }
        } catch {
            Write-Host "    Could not terminate PID $($Process.ProcessId): $($_.Exception.Message)"
        }
    }
}

Write-Host "Stopping existing agent processes..."

# Kill any pythonw processes running our agents or supervisor.
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
$killed = 0
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | ForEach-Object {
    foreach ($mod in $AgentModules) {
        if ($_.CommandLine -match $mod) {
            Stop-AgentProcess -Process $_ -Module $mod
            $killed++
            break
        }
    }
}

if ($killed -eq 0) {
    Write-Host "  No agent processes found"
}

# Also try stopping the scheduled task cleanly.
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq "Running") {
    Write-Host "  Stopping scheduled task..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2

# Supervisor-managed agents share the supervisor process PID. If a supervisor
# dies hard, per-agent PID locks can outlive the actual owner and block the next
# clean supervisor from starting that agent. These locks are safe to clear here
# because this script has just stopped every known Home Hub pythonw agent.
$StalePidLocks = @(
    "logs\peripheral_rgb.pid"
)
foreach ($relative in $StalePidLocks) {
    $pidFile = Join-Path $ProjectRoot $relative
    if (Test-Path -LiteralPath $pidFile) {
        Write-Host "  Removing stale PID lock $relative"
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Starting agent supervisor..."
# Route through the same VBS -> start-supervisor.ps1 chain that the
# "Home Hub Agent Supervisor" Scheduled Task uses. Single source of truth
# for the launch path -- start-supervisor.ps1 owns the system-Python +
# venv-PYTHONPATH composition (see its header comment for the rationale).
# Launching venv\Scripts\pythonw.exe directly here was a mistake: the venv
# launcher resolves packages only from venv\Lib\site-packages, while the
# Scheduled Task picks up packages installed in either system OR venv via
# the PYTHONPATH setup in start-supervisor.ps1. The mismatch silently
# disabled emotion_capture (mediapipe was system-only) on 2026-05-28.
$VbsLauncher = Join-Path $ProjectRoot "scripts\start-supervisor-hidden.vbs"
Start-Process "wscript.exe" `
    -ArgumentList "`"$VbsLauncher`"" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

Start-Sleep -Seconds 4

# Verify through Get-Process instead of WMI so stale WMI rows do not look like
# duplicate live supervisors.
$running = Get-Process -Name pythonw -ErrorAction SilentlyContinue | Where-Object {
    try {
        (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)").CommandLine -match "supervisor"
    } catch {
        $false
    }
}

if ($running) {
    $ids = ($running | Select-Object -ExpandProperty Id) -join ", "
    Write-Host "OK: supervisor running (PID $ids)" -ForegroundColor Green
    Write-Host "Logs: $LogFile" -ForegroundColor Cyan
} else {
    Write-Host "ERROR: supervisor not found - check $LogFile" -ForegroundColor Red
}
