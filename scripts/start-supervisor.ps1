# Canonical Windows launcher for the unified Home Hub PC Agent Supervisor.
#
# This file serves two locations:
#   1. directly from the repository as a recovery fallback;
#   2. copied to %LOCALAPPDATA%\home-hub by setup-supervisor-task.ps1.
#
# When installed under LocalAppData, the Scheduled Task supplies the canonical
# repository as its WorkingDirectory. When run from the repository, the script
# can derive the root from its own path. Both paths intentionally use the
# repository's .venv instead of a machine-specific Python installation.

$ErrorActionPreference = "Stop"

$RepoCandidate = Resolve-Path (Join-Path $PSScriptRoot "..") -ErrorAction SilentlyContinue
if ($RepoCandidate -and (Test-Path (Join-Path $RepoCandidate.Path "pyproject.toml"))) {
    $ProjectRoot = $RepoCandidate.Path
} elseif (Test-Path (Join-Path (Get-Location).Path "pyproject.toml")) {
    $ProjectRoot = (Get-Location).Path
} else {
    throw "Unable to locate the Home Hub repository. Run setup-supervisor-task.ps1 from the canonical checkout."
}

$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $PythonW)) {
    throw "Home Hub .venv pythonw.exe was not found at $PythonW"
}

Set-Location $ProjectRoot

# Server URL from the HOME_HUB_URL user env var; falls back to the current
# Latitude LAN IP.
$Server = if ($env:HOME_HUB_URL) { $env:HOME_HUB_URL } else { "http://192.168.86.210:8000" }

& $PythonW -m backend.services.pc_agent.supervisor `
    --server $Server `
    --classifier `
    --active
exit $LASTEXITCODE
