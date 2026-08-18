# Wrapper: launches the PC Agent Supervisor under system Python with the
# venv's site-packages on PYTHONPATH.
#
# Why not venv\Scripts\pythonw.exe? Python 3.13's venv on Windows uses a
# launcher-subprocess pattern: venv\pythonw.exe (1.5 MB stub) chain-loads
# C:\Python313\pythonw.exe (66 MB real interpreter), producing two
# pythonw.exe processes that look like a duplicate bug even though the
# mutex is working. Running system Python directly with PYTHONPATH avoids
# the launcher indirection — one pythonw.exe, with a small powershell.exe
# parent that's clearly a wrapper, not a confusable duplicate.
#
# --copies was tried (python -m venv --copies) and ignored by Python 3.13:
# produces the same launcher binary byte-for-byte.

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SystemPythonW = "C:\Python313\pythonw.exe"

$env:PYTHONPATH = "$ProjectRoot\venv\Lib\site-packages;$ProjectRoot"

Set-Location $ProjectRoot

# Server URL from the HOME_HUB_URL user env var (set during the 2026-06
# network re-IP to 192.168.86.x); falls back to the current Latitude LAN IP.
$Server = if ($env:HOME_HUB_URL) { $env:HOME_HUB_URL } else { "http://192.168.86.210:8000" }

& $SystemPythonW -m backend.services.pc_agent.supervisor `
    --server $Server `
    --classifier `
    --active
