# Create or update the Task Scheduler task for the PC Activity Detector.
# Must run as admin (elevated PowerShell).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-detector-task.ps1

$TaskName = "Home Hub PC Activity Detector"
$ProjectRoot = "C:\Users\antho\Desktop\home-hub"
$PythonW = "$ProjectRoot\venv\Scripts\pythonw.exe"
$Arguments = "-m backend.services.pc_agent.activity_detector --server http://192.168.1.210:8000"

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: run pythonw.exe with activity_detector module
$action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument $Arguments `
    -WorkingDirectory $ProjectRoot

# Trigger: on logon with 30s delay
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT30S"

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -Hidden

# Principal: run as current user, interactive logon
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Reports active mode (gaming/working/watching/idle) to Home Hub backend on Latitude 192.168.1.210"

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Key settings:" -ForegroundColor Cyan
Write-Host "  - Trigger: At logon (30s delay)"
Write-Host "  - StopIfGoingOnBatteries: False"
Write-Host "  - Restart on failure: 3 times, 1 min apart"
Write-Host "  - Multiple instances: Ignore new"
Write-Host "  - PID lock: detector self-manages via logs\activity_detector.pid"
Write-Host ""
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
