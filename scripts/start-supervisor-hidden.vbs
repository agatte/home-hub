' Windowless launcher for the Home Hub PC Agent Supervisor.
'
' Why this exists: the 5-minute watchdog trigger on the "Home Hub Agent
' Supervisor" Task Scheduler entry was briefly flashing a console window
' on every fire when the Task action was powershell.exe directly. Even
' with -WindowStyle Hidden, PowerShell creates a visible window first
' and hides it after -- the flash is unavoidable that way.
'
' wscript.exe is windowless from process creation. Its
' Wscript.Shell.Run("...", 0, False) call passes WindowStyle=0 (hidden)
' to CreateProcess, so the launched powershell.exe never becomes visible
' to begin with. No flash possible.
'
' Chain at task fire time:
'   wscript.exe (windowless)
'     -> powershell.exe (hidden via Run state 0)
'       -> start-supervisor.ps1 (sets PYTHONPATH + workdir)
'         -> pythonw.exe (windowless) -m backend.services.pc_agent.supervisor
'           -> supervisor.py
'
' supervisor.py's Windows-mutex check makes 5-minute watchdog fires a
' fast no-op when an instance is already running -- it just exits and
' the whole chain unwinds in ~100ms with zero visible artifacts.
Set objShell = WScript.CreateObject("Wscript.Shell")
Set objFSO = WScript.CreateObject("Scripting.FileSystemObject")
scriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
supervisorScript = objFSO.BuildPath(scriptDir, "start-supervisor.ps1")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & supervisorScript & """", 0, False
