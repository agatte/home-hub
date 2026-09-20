' Windowless launcher for the Home Hub PC Agent Supervisor.
'
' Why this exists: the 5-minute watchdog trigger on the "Home Hub Agent
' Supervisor" Task Scheduler entry was briefly flashing a console window
' on every fire when the Task action was powershell.exe directly. Even
' with -WindowStyle Hidden, PowerShell creates a visible window first
' and hides it after -- the flash is unavoidable that way.
'
' wscript.exe is windowless from process creation. Its
' Wscript.Shell.Run("...", 0, True) passes WindowStyle=0 (hidden) and waits
' for the supervisor launcher to exit. Keeping wscript alive makes the Scheduled
' Task remain Running, so MultipleInstances=IgnoreNew suppresses watchdog
' duplicates while the supervisor is healthy. No console flash is created.
'
' Chain at task fire time:
'   wscript.exe (windowless)
'     -> powershell.exe (hidden via Run state 0)
'       -> start-supervisor.ps1 (resolves repo + .venv and sets workdir)
'         -> pythonw.exe (windowless) -m backend.services.pc_agent.supervisor
'           -> supervisor.py
'
' Task Scheduler's MultipleInstances=IgnoreNew is the first duplicate guard.
' supervisor.py's Windows mutex remains defense-in-depth if a launcher is
' invoked outside the task or two starts race.
Set objShell = WScript.CreateObject("Wscript.Shell")
Set objFSO = WScript.CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
supervisorScript = objFSO.BuildPath(scriptDir, "start-supervisor.ps1")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & supervisorScript & """", 0, True
