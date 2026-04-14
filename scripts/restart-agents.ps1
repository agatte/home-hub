# Restart the PC Agent Supervisor on the dev machine.
# Kills any existing supervisor/agent processes and starts fresh.
#
# Usage: powershell -File scripts\restart-agents.ps1

$ProjectRoot = "C:\Users\antho\Desktop\home-hub"
$LogFile = Join-Path $ProjectRoot "logs\supervisor.log"

Write-Host "Stopping existing agent processes..."

# Kill any pythonw processes running our agents or supervisor
$AgentModules = @("activity_detector", "ambient_monitor", "screen_sync_agent", "supervisor")
$killed = 0
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | ForEach-Object {
    foreach ($mod in $AgentModules) {
        if ($_.CommandLine -match $mod) {
            Write-Host "  Killing PID $($_.ProcessId) ($mod)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $killed++
            break
        }
    }
}

if ($killed -eq 0) {
    Write-Host "  No agent processes found"
}

# Also try stopping the scheduled task cleanly
$TaskName = "Home Hub Agent Supervisor"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq "Running") {
    Write-Host "  Stopping scheduled task..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2

Write-Host "Starting agent supervisor..."
Start-Process "$ProjectRoot\venv\Scripts\pythonw.exe" `
    -ArgumentList "-m","backend.services.pc_agent.supervisor","--server","http://192.168.1.210:8000","--classifier","--shadow" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

Start-Sleep -Seconds 4

# Verify — check for any pythonw process running the supervisor
$running = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object {
    $_.CommandLine -match "supervisor"
}

if ($running) {
    Write-Host "OK: supervisor running (PID $($running.ProcessId))" -ForegroundColor Green
    Write-Host "Logs: $LogFile" -ForegroundColor Cyan
} else {
    Write-Host "ERROR: supervisor not found — check $LogFile" -ForegroundColor Red
}
