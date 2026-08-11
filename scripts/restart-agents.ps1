# Verified manual recovery for the Home Hub desktop supervisor.
# Stops the task-launch race, retires only snapshotted process identities, and
# accepts success only after a newer supervisor has reported its own identity.

[CmdletBinding()]
param([switch]$FunctionsOnly)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $ProjectRoot "logs\supervisor.log"
$TaskName = "Home Hub Agent Supervisor"
$AgentModules = @(
    "backend.services.pc_agent.activity_detector",
    "backend.services.pc_agent.ambient_monitor",
    "backend.services.pc_agent.screen_sync_agent",
    "backend.services.pc_agent.sleep_watcher",
    "backend.services.pc_agent.emotion_capture",
    "backend.services.pc_agent.monitor_brightness",
    "backend.services.pc_agent.peripheral_rgb",
    "backend.services.pc_agent.supervisor"
)
$StalePidLocks = @("logs\peripheral_rgb.pid")
$RecoveryTimeoutSeconds = 10

if (-not ("HomeHubProcessNativeMethods" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class HomeHubProcessNativeMethods
{
    private const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;

    [StructLayout(LayoutKind.Sequential)]
    private struct FILETIME
    {
        public uint LowDateTime;
        public uint HighDateTime;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(
        uint desiredAccess,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandle,
        int processId
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetProcessTimes(
        IntPtr processHandle,
        out FILETIME creationTime,
        out FILETIME exitTime,
        out FILETIME kernelTime,
        out FILETIME userTime
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    public static bool TryGetCreationFileTime(int processId, out ulong creationFileTime)
    {
        creationFileTime = 0;
        if (processId <= 0)
        {
            return false;
        }

        IntPtr handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, processId);
        if (handle == IntPtr.Zero)
        {
            return false;
        }

        try
        {
            FILETIME creation;
            FILETIME exit;
            FILETIME kernel;
            FILETIME user;
            if (!GetProcessTimes(handle, out creation, out exit, out kernel, out user))
            {
                return false;
            }

            creationFileTime = ((ulong)creation.HighDateTime << 32) | creation.LowDateTime;
            return true;
        }
        finally
        {
            CloseHandle(handle);
        }
    }
}
'@
}

function Get-NativeProcessCreationFileTime([int]$ProcessId) {
    [UInt64]$creationFileTime = 0
    if (-not [HomeHubProcessNativeMethods]::TryGetCreationFileTime(
        $ProcessId, [ref]$creationFileTime
    )) {
        return $null
    }
    return $creationFileTime
}

function Get-NativeProcessIdentity([int]$ProcessId) {
    $creationFileTime = Get-NativeProcessCreationFileTime $ProcessId
    if ($null -eq $creationFileTime) { return $null }
    return [pscustomobject]@{
        ProcessId = $ProcessId
        CreationFileTime = $creationFileTime
        Identity = "${ProcessId}:$creationFileTime"
    }
}

function Get-IdentityKey($Process) {
    $nativeIdentity = Get-NativeProcessIdentity ([int]$Process.ProcessId)
    if ($null -eq $nativeIdentity) { return $null }
    return $nativeIdentity.Identity
}

function Test-HomeHubCommandLine([string]$CommandLine) {
    if (-not $CommandLine) { return $false }
    foreach ($module in $AgentModules) {
        $modulePattern = "(?:^|\s)-m\s+" + [regex]::Escape($module) + "(?=\s|$)"
        if ($CommandLine -match $modulePattern) { return $true }

        $scriptName = ($module.Split('.')[-1] + '.py')
        $scriptPath = Join-Path $ProjectRoot "backend\services\pc_agent\$scriptName"
        if ($CommandLine -match [regex]::Escape($scriptPath)) { return $true }
    }
    return $false
}

function Get-HomeHubProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object {
        Test-HomeHubCommandLine $_.CommandLine
    } | ForEach-Object {
        $nativeIdentity = Get-NativeProcessIdentity ([int]$_.ProcessId)
        [pscustomobject]@{
            ProcessId = $_.ProcessId
            CommandLine = $_.CommandLine
            CreationFileTime = if ($nativeIdentity) { $nativeIdentity.CreationFileTime } else { $null }
            Identity = if ($nativeIdentity) { $nativeIdentity.Identity } else { $null }
        }
    }
}

function Get-IdentityInspection($Identity) {
    if (-not $Identity -or -not $Identity.Identity) {
        return [pscustomobject]@{ Status = 'Indeterminate'; Process = $null }
    }
    try {
        $current = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($Identity.ProcessId)" -ErrorAction Stop
    } catch {
        return [pscustomobject]@{ Status = 'Indeterminate'; Process = $null }
    }
    if (-not $current) {
        return [pscustomobject]@{ Status = 'AbsentOrDifferent'; Process = $current }
    }
    $currentIdentity = Get-IdentityKey $current
    if ($null -eq $currentIdentity) {
        return [pscustomobject]@{ Status = 'Indeterminate'; Process = $current }
    }
    if ($currentIdentity -ne $Identity.Identity) {
        return [pscustomobject]@{ Status = 'AbsentOrDifferent'; Process = $current }
    }
    if (-not (Test-HomeHubCommandLine $current.CommandLine)) {
        return [pscustomobject]@{ Status = 'Indeterminate'; Process = $current }
    }
    return [pscustomobject]@{ Status = 'Exact'; Process = $current }
}

function Test-ReplacementHealthIdentity($Health, $Replacement) {
    if (-not $Health -or -not $Replacement -or -not $Replacement.Identity) { return $false }
    return (
        $Health.supervisor_pid -eq $Replacement.ProcessId -and
        $Health.supervisor_instance -eq $Replacement.Identity
    )
}

function Wait-IdentityGone($Identity, [int]$TimeoutSeconds = $RecoveryTimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $inspection = Get-IdentityInspection $Identity
        if ($inspection.Status -eq 'AbsentOrDifferent') { return $true }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    return (Get-IdentityInspection $Identity).Status -eq 'AbsentOrDifferent'
}

function Stop-ExactIdentity($Identity) {
    Write-Host "  Terminating $($Identity.Identity)"
    $inspection = Get-IdentityInspection $Identity
    if ($inspection.Status -eq 'AbsentOrDifferent') { return $true }
    if ($inspection.Status -eq 'Indeterminate') { return $false }

    # Invoke the method only on the just-revalidated exact CIM instance. A PID
    # that has already been reused is never passed to a PID-only kill command.
    try {
        $null = $inspection.Process | Invoke-CimMethod -MethodName Terminate -ErrorAction Stop
    } catch {}
    return Wait-IdentityGone $Identity
}

if ($FunctionsOnly) { return }

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskWasEnabled = $task -and $task.State -ne 'Disabled'
$failureMessage = $null
$successMessage = $null
try {
    if (-not $task) { throw "Scheduled Task '$TaskName' was not found." }
    if ($taskWasEnabled) {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
    }
    if ($task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    }

    Write-Host "Snapshotting Home Hub agent owners after task suppression..."
    $owners = @(Get-HomeHubProcesses)
    $indeterminateOwners = @($owners | Where-Object { -not $_.Identity })
    if ($indeterminateOwners) {
        $indeterminatePids = ($indeterminateOwners.ProcessId -join ', ')
        throw "Initial owner identity inspection was indeterminate for PID(s): $indeterminatePids"
    }
    $owners | ForEach-Object { Write-Host "  $($_.Identity) $($_.CommandLine)" }
    foreach ($owner in $owners) {
        if (-not (Stop-ExactIdentity $owner)) { throw "Old owner survived bounded recovery: $($owner.Identity)" }
    }
    foreach ($owner in $owners) {
        if (-not (Wait-IdentityGone $owner 0)) {
            throw "Old owner absence could not be proven: $($owner.Identity)"
        }
    }

    foreach ($relative in $StalePidLocks) {
        $pidFile = Join-Path $ProjectRoot $relative
        if (Test-Path -LiteralPath $pidFile) {
            Write-Host "  Removing proven-stale PID lock $relative"
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction Stop
        }
    }

    # Lower-bound marker only; process identities never derive from DateTime.
    $restartAttemptFileTime = [DateTime]::UtcNow.ToFileTimeUtc()
    $oldKeys = @($owners | ForEach-Object Identity)
    $launcher = Join-Path $ProjectRoot "scripts\start-supervisor-hidden.vbs"
    Write-Host "Launching canonical supervisor path..."
    Start-Process wscript.exe -ArgumentList "`"$launcher`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden

    $replacement = $null
    $deadline = (Get-Date).AddSeconds(20)
    do {
        $replacement = Get-HomeHubProcesses | Where-Object {
            $_.CommandLine -match 'backend\.services\.pc_agent\.supervisor' -and
            $_.Identity -and $_.CreationFileTime -gt $restartAttemptFileTime -and
            $_.Identity -notin $oldKeys
        } | Select-Object -First 1
        if ($replacement) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if (-not $replacement) { throw 'No replacement supervisor newer than this restart attempt was found.' }

    # Existing API payload is advisory but can bind a fresh health report to the
    # new Windows identity; never accept a pre-existing process as replacement.
    $server = if ($env:HOME_HUB_URL) { $env:HOME_HUB_URL } else { 'http://192.168.86.210:8000' }
    $healthOk = $false
    $deadline = (Get-Date).AddSeconds(15)
    do {
        try {
            $health = Invoke-RestMethod -Uri "$server/api/automation/agent-health" -TimeoutSec 3
            $healthOk = Test-ReplacementHealthIdentity $health $replacement
        } catch { $healthOk = $false }
        if ($healthOk) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if (-not $healthOk) { throw "Replacement $($replacement.Identity) did not publish matching supervisor health." }

    $successMessage = "OK: replacement supervisor $($replacement.Identity) is live and healthy."
} catch {
    $failureMessage = $_.Exception.Message
} finally {
    if ($task) {
        try {
            Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
            $restoredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
            if (-not $restoredTask -or $restoredTask.State -eq 'Disabled') {
                throw "Scheduled Task '$TaskName' is still disabled after restoration."
            }
        } catch {
            $restoreFailure = "Scheduled Task restoration failed: $($_.Exception.Message)"
            $failureMessage = if ($failureMessage) {
                "$failureMessage $restoreFailure"
            } else {
                $restoreFailure
            }
        }
    }
}

if ($failureMessage) {
    Write-Error $failureMessage
    exit 1
}

Write-Host $successMessage -ForegroundColor Green
Write-Host "Logs: $LogFile" -ForegroundColor Cyan
