# Build a one-file Windows .exe for the Home Hub desktop notifier.
#
# Usage (from project root):
#   .\scripts\build_desktop_notifier.ps1
#
# Output: dist\HomeHubNotifier.exe
#
# Prerequisites:
#   pip install -r requirements.txt -r requirements-desktop.txt pyinstaller
#
# After build, install by:
#   1. Copy dist\HomeHubNotifier.exe to a stable path (e.g. %LOCALAPPDATA%\HomeHub\)
#   2. Add a Task Scheduler entry: Trigger=At log on, Action=Start a program,
#      Program/script = full path to the .exe, Arguments = --server ws://192.168.1.210:8000/ws
#   3. First launch: tray icon appears bottom-right. Double-click for a test toast.

$ErrorActionPreference = "Stop"

Write-Host "Building HomeHubNotifier.exe..." -ForegroundColor Cyan

# --windowed: no console window
# --onefile: single self-contained exe (slower first launch, simpler distribution)
# --name: output filename
# --icon: skipped — tray icon is generated programmatically in code
& pyinstaller `
    --noconfirm `
    --windowed `
    --onefile `
    --name HomeHubNotifier `
    --hidden-import PyQt6.QtCore `
    --hidden-import PyQt6.QtGui `
    --hidden-import PyQt6.QtWidgets `
    backend\services\pc_agent\desktop_notifier.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "✓ Built dist\HomeHubNotifier.exe" -ForegroundColor Green
Write-Host "  Quick verify: .\dist\HomeHubNotifier.exe --server ws://192.168.1.210:8000/ws" -ForegroundColor Gray
