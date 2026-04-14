# Create or update the Task Scheduler task for the Ambient Monitor + YAMNet.
# Must run as admin (elevated PowerShell).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-ambient-task.ps1

$TaskName = "Home Hub Ambient Monitor"
$ProjectRoot = "C:\Users\antho\Desktop\home-hub"
$PythonW = "$ProjectRoot\venv\Scripts\pythonw.exe"
$Arguments = "-m backend.services.pc_agent.ambient_monitor --server http://192.168.1.210:8000 --classifier --shadow"

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: run pythonw.exe with ambient_monitor module
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
    -Description "YAMNet audio scene classification via Blue Yeti - reports to Home Hub backend on Latitude 192.168.1.210"

Write-Host ""
Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Key settings:" -ForegroundColor Cyan
Write-Host "  - Trigger: At logon (30s delay)"
Write-Host "  - Classifier: YAMNet (shadow mode)"
Write-Host "  - StopIfGoingOnBatteries: False"
Write-Host "  - Restart on failure: 3 times, 1 min apart"
Write-Host "  - Multiple instances: Ignore new"
Write-Host ""
Write-Host "To start now: Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host "To switch to active mode later, edit the task arguments to replace --shadow with --active" -ForegroundColor Yellow
