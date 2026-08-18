@echo off
setlocal
title Home Hub - ChatGPT Snapshot

echo Creating a lean Home Hub snapshot for ChatGPT...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create-chatgpt-snapshot.ps1"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo Snapshot creation FAILED with exit code %RC%.
    echo No project files were modified by the snapshot script.
    echo.
    pause
    exit /b %RC%
)

echo Opening the snapshots folder...
start "" "%~dp0..\snapshots"

echo.
echo Snapshot complete. The ZIP path is also on your clipboard.
pause
exit /b 0
