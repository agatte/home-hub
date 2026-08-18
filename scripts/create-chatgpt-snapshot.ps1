[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$ProjectRoot = Split-Path -Parent $RepoRoot
$SnapshotsDir = Join-Path $ProjectRoot "snapshots"

function Invoke-Git {
    param([Parameter(Mandatory=$true)][string[]]$Args)
    $output = & git -C $RepoRoot @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed:`n$($output -join [Environment]::NewLine)"
    }
    return @($output)
}

function Should-ExcludeSnapshotPath {
    param([Parameter(Mandatory=$true)][string]$RelativePath)

    $p = $RelativePath.Replace("\", "/")

    # Long-standing unrelated machine-local file in Anthony's checkout.
    if ($p -eq "=") { return $true }

    # Secrets: keep .env.example, exclude actual/local env files and key material.
    $leaf = [IO.Path]::GetFileName($p)
    if ($leaf -ne ".env.example" -and $leaf -match "^\.env($|\.)") { return $true }
    if ($p -match "(^|/)(id_rsa|id_ed25519)(\.pub)?$") { return $true }
    if ($p -match "\.(pem|key|p12|pfx)$") { return $true }

    # Runtime, dependency, build, cache, log, database, and generated-output trees.
    if ($p -match "^(node_modules|venv|\.venv|logs|data|build|dist|htmlcov|playwright-report|test-results|coverage)(/|$)") { return $true }
    if ($p -match "^frontend-svelte/(node_modules|build|\.svelte-kit|playwright-report|test-results)(/|$)") { return $true }
    if ($p -match "(^|/)(\.pytest_cache|\.ruff_cache|\.mypy_cache|\.cache|__pycache__)(/|$)") { return $true }

    # Large tracked presentation/media assets are not useful in a source-context
    # snapshot. Keep the code that references them, but omit the binary payloads.
    if ($p -match "^backend/static/ambient/") { return $true }
    if ($p -match "^frontend-svelte/static/3d/") { return $true }

    # Generated/runtime file types and nested archives.
    if ($p -match "\.(pyc|pyo|log|db|sqlite|sqlite3|zip|rar|7z)$") { return $true }

    return $false
}

$inside = Invoke-Git @("rev-parse", "--is-inside-work-tree")
if (($inside | Select-Object -First 1).Trim() -ne "true") {
    throw "Expected a Git worktree at $RepoRoot"
}

New-Item -ItemType Directory -Force -Path $SnapshotsDir | Out-Null

$branch = ((Invoke-Git @("branch", "--show-current")) | Select-Object -First 1).Trim()
if (-not $branch) { $branch = "detached" }

$sha = ((Invoke-Git @("rev-parse", "--short=12", "HEAD")) | Select-Object -First 1).Trim()
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipName = "home-hub-chatgpt-$timestamp-$sha.zip"
$zipPath = Join-Path $SnapshotsDir $zipName

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "home-hub-chatgpt-$timestamp-$PID"
$stageRoot = Join-Path $tempRoot "home-hub"
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

function Is-SafeUntrackedSnapshotPath {
    param([Parameter(Mandatory=$true)][string]$RelativePath)

    $p = $RelativePath.Replace("\", "/")
    $safePrefixes = @(
        "backend/",
        "frontend-svelte/src/",
        "frontend-svelte/static/",
        "tests/",
        "docs/",
        "scripts/",
        "deployment/",
        "docker/",
        "alexa_skill/",
        "mcp_server/",
        "static/",
        ".github/"
    )
    foreach ($prefix in $safePrefixes) {
        if ($p.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    # Safe root-level source/docs/config additions. Secrets/runtime files are
    # still rejected by Should-ExcludeSnapshotPath.
    if ($p -notmatch "/" -and $p -match "\.(md|py|ps1|cmd|toml|ya?ml|json|js|ts|txt)$") {
        return $true
    }
    return $false
}

$included = New-Object System.Collections.Generic.List[string]
$skipped = New-Object System.Collections.Generic.List[string]
$maxFileBytes = 25MB

try {
    # Always include tracked files. Include untracked files only from
    # source/docs/config locations that are useful to ChatGPT, so arbitrary
    # machine-local debris does not get swept into an upload.
    $tracked = @(Invoke-Git @("ls-files", "--cached"))
    $untracked = @(Invoke-Git @("ls-files", "--others", "--exclude-standard"))

    $files = New-Object System.Collections.Generic.List[string]
    foreach ($relative in $tracked) {
        if (-not [string]::IsNullOrWhiteSpace($relative)) {
            $files.Add($relative) | Out-Null
        }
    }
    foreach ($relative in $untracked) {
        if ([string]::IsNullOrWhiteSpace($relative)) { continue }
        if (-not (Is-SafeUntrackedSnapshotPath $relative)) {
            $skipped.Add("$relative [untracked-not-allowlisted]") | Out-Null
            continue
        }
        $files.Add($relative) | Out-Null
    }

    foreach ($relative in ($files | Sort-Object -Unique)) {
        if (Should-ExcludeSnapshotPath $relative) {
            $skipped.Add("$relative [policy]") | Out-Null
            continue
        }

        $source = Join-Path $RepoRoot $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            $skipped.Add("$relative [missing/non-file]") | Out-Null
            continue
        }

        $length = (Get-Item -LiteralPath $source).Length
        if ($length -gt $maxFileBytes) {
            $skipped.Add("$relative [larger than 25 MB]") | Out-Null
            continue
        }

        $dest = Join-Path $stageRoot $relative
        $destDir = Split-Path -Parent $dest
        if ($destDir) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $dest -Force
        $included.Add($relative) | Out-Null
    }

    $status = (Invoke-Git @("status", "--short", "--branch")) -join [Environment]::NewLine
    $diffStat = (& git -C $RepoRoot diff --stat 2>&1) -join [Environment]::NewLine
    $cachedDiffStat = (& git -C $RepoRoot diff --cached --stat 2>&1) -join [Environment]::NewLine
    $remote = (& git -C $RepoRoot remote get-url origin 2>&1 | Select-Object -First 1)

    $manifest = @"
Home Hub - ChatGPT Snapshot Manifest
====================================

Created:       $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
Repository:    $RepoRoot
Origin:        $remote
Branch:        $branch
HEAD:          $sha
Files included: $($included.Count)
Files skipped:  $($skipped.Count)

Git status
----------
$status

Working-tree diff stat
----------------------
$diffStat

Staged diff stat
----------------
$cachedDiffStat

Snapshot policy
---------------
- Includes Git-tracked files plus allowlisted untracked source/docs/config.
- Excludes .env/local secret files, private keys, runtime databases, logs,
  caches, dependency/build trees, large tracked ambient/3D binary assets,
  nested archives, and files over 25 MB.
- Explicitly excludes the unrelated root file named "=".
- Does not include .git metadata.
- Does not modify repository files.

Skipped paths
-------------
$($skipped -join [Environment]::NewLine)
"@

    Set-Content -LiteralPath (Join-Path $stageRoot "SNAPSHOT_MANIFEST.txt") `
        -Value $manifest -Encoding UTF8

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stageRoot,
        $zipPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    $zipInfo = Get-Item -LiteralPath $zipPath
    $sizeMB = [math]::Round($zipInfo.Length / 1MB, 2)

    try {
        Set-Clipboard -Value $zipPath
        $clipboardNote = "ZIP path copied to clipboard."
    }
    catch {
        $clipboardNote = "Could not copy ZIP path to clipboard."
    }

    Write-Host ""
    Write-Host "Snapshot created successfully."
    Write-Host "Path:   $zipPath"
    Write-Host "Size:   $sizeMB MB"
    Write-Host "Files:  $($included.Count)"
    Write-Host "Branch: $branch"
    Write-Host "HEAD:   $sha"
    Write-Host $clipboardNote
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
