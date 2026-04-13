# Restart the PC Activity Detector on the dev machine.
# Run after code changes to game_list.py or activity_detector.py.
#
# Usage: powershell -File scripts\restart-detector.ps1

$ProjectRoot = "C:\Users\antho\Desktop\home-hub"
$PidFile = Join-Path $ProjectRoot "logs\activity_detector.pid"

Write-Host "Stopping old detector instances..."

# Try PID-file-based kill first (clean, targeted)
if (Test-Path $PidFile) {
    $pid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($pid) {
        try {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc) {
                # Kill process tree (parent + children)
                $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $pid }
                foreach ($child in $children) {
                    Write-Host "  Killing child PID $($child.ProcessId)"
                    Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
                }
                Write-Host "  Killing PID $pid"
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
        } catch {
            Write-Host "  PID $pid already gone"
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

# Fallback: kill any remaining pythonw activity_detector processes
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | ForEach-Object {
    if ($_.CommandLine -match "activity_detector") {
        Write-Host "  Killing orphaned detector PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 1

Write-Host "Starting activity detector..."
Start-Process "$ProjectRoot\venv\Scripts\pythonw.exe" `
    -ArgumentList "-m","backend.services.pc_agent.activity_detector","--server","http://192.168.1.210:8000" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

# Verify it's running and reporting
if (Test-Path $PidFile) {
    $newPid = Get-Content $PidFile
    $proc = Get-Process -Id $newPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "OK: detector running (PID $newPid)" -ForegroundColor Green
    } else {
        Write-Host "ERROR: PID file exists but process not running" -ForegroundColor Red
    }
} else {
    Write-Host "WARNING: PID file not created yet — check logs\activity_detector.log" -ForegroundColor Yellow
}
