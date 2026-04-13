# Restart the PC Activity Detector on the dev machine.
# Run after code changes to game_list.py or activity_detector.py.
#
# Usage: powershell -File scripts\restart-detector.ps1

Write-Host "Stopping old detector instances..."
Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

Write-Host "Starting activity detector..."
Start-Process pythonw `
    -ArgumentList "-m","backend.services.pc_agent.activity_detector","--server","http://192.168.1.210:8000" `
    -WorkingDirectory "C:\Users\antho\Desktop\home-hub" `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

# Verify it's running and reporting
$proc = Get-Process pythonw -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "OK: detector running (PID $($proc.Id))" -ForegroundColor Green
} else {
    Write-Host "ERROR: detector not running" -ForegroundColor Red
}
