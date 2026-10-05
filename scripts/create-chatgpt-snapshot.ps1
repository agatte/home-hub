[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$ProjectRoot = Split-Path -Parent $RepoRoot
$SnapshotsDir = Join-Path $ProjectRoot "snapshots"

function Invoke-Git {
    param([Parameter(Mandatory=$true)][string[]]$Args)

    # Windows PowerShell 5.1 promotes native stderr to NativeCommandError when
    # ErrorActionPreference=Stop, even if Git exits successfully. Git can emit
    # benign scan warnings (for example an unreadable ignored cache directory),
    # so capture stdout only and decide success from Git's exit code.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git -C $RepoRoot @Args 2>$null
        $gitExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($gitExitCode -ne 0) { throw "Git operation failed." }
    return @($output)
}

# This is the single eligibility gate used for both source candidates and ZIP
# members. Keep the allowlist deliberately limited to useful source/context.
function Test-SnapshotPath {
    param([Parameter(Mandatory=$true)][string]$RelativePath)
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { return $false }
    $p = $RelativePath.Replace("\", "/")
    if ($p.StartsWith("/") -or $p -match "^[A-Za-z]:" -or $p -match "(^|/)\.\.?(/|$)" -or $p.Contains(":") -or $p -match "//|/$|[. ](/|$)") { return $false }
    if ($p -eq "=" -or $p -match '(?i)(^|/)\.mcp\.json$' -or $p -match '(?i)(^|/)\.env($|\.)') {
        if ($p -match '(?i)(^|/)\.env\.example$') { } else { return $false }
    }
    $leaf = [IO.Path]::GetFileName($p)
    # Reject machine-local credential/configuration locations even when they sit
    # underneath an otherwise safe source/docs prefix.
    if ($p -match '(?i)(^|/)(secrets?|credentials?|\.ssh|\.aws|\.azure|\.kube|\.docker|\.vscode|\.idea|\.claude|\.codex)(/|$)') { return $false }
    if ($leaf -match '(?i)(^|[-_.])(credentials?|secrets?)([-_.]|$)' -or
        $leaf -match '(?i)^(id_rsa|id_ed25519|authorized_keys|known_hosts|\.npmrc|\.pypirc|\.netrc|\.ssh_config)(\.|$)' -or
        $leaf -match '(?i)\.(pem|key|p12|pfx|keystore|jks|sqlite|sqlite3|db|log|zip|rar|7z|pyc|pyo)$') { return $false }
    if ($leaf -match '(?i)(^|[-_.])(config|settings)([-_.])(local|machine|user)([-_.]|$)' -or
        $leaf -match '(?i)(^|[-_.])(local|machine|user)([-_.])(config|settings)([-_.]|$)') { return $false }
    if ($p -match '(?i)(^|/)(node_modules|venv|\.venv|\.git|\.svelte-kit|logs|data|build|dist|htmlcov|playwright-report|test-results|coverage|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.cache|__pycache__)(/|$)') { return $false }
    if ($p -match '^(?i:backend/static/ambient/|frontend-svelte/static/3d/)') { return $false }

    # Only export text/source/config formats from explicit project source trees.
    # Tracked status does not widen this allowlist.
    $safePrefixes = @('backend/','frontend-svelte/','tests/','docs/','scripts/','deployment/','docker/','alexa_skill/','mcp_server/','static/','.github/')
    $safeExtensions = @(
        '.md','.txt','.py','.pyi','.ps1','.psm1','.psd1','.cmd','.bat','.sh','.vbs',
        '.js','.mjs','.cjs','.ts','.tsx','.jsx','.svelte','.css','.scss','.html',
        '.json','.jsonc','.toml','.yaml','.yml','.sql','.service','.timer','.desktop',
        '.ini','.cfg','.conf','.xml','.csv','.lock'
    )
    $rootSafeNames = @('.gitattributes','.gitignore','Dockerfile','Makefile','Procfile')
    $extension = [IO.Path]::GetExtension($leaf).ToLowerInvariant()
    $allowedType = ($safeExtensions -contains $extension) -or ($rootSafeNames -contains $leaf) -or
        ($p -match '(?i)(^|/)\.env\.example$')
    if (-not $allowedType) { return $false }

    $allowedLocation = ($p -notmatch '/')
    foreach ($prefix in $safePrefixes) {
        if ($p.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { $allowedLocation = $true; break }
    }
    if (-not $allowedLocation) { return $false }
    return $true
}

function Test-SafeRepositoryFile {
    param([Parameter(Mandatory=$true)][string]$RelativePath)
    if (-not (Test-SnapshotPath $RelativePath)) { return $false }
    $separator = [IO.Path]::DirectorySeparatorChar
    $candidate = Join-Path $RepoRoot ($RelativePath.Replace([char]'/', $separator))
    try { $full = [IO.Path]::GetFullPath($candidate) } catch { return $false }
    $rootSeparators = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $rootFull = [IO.Path]::GetFullPath($RepoRoot).TrimEnd($rootSeparators) + $separator
    if (-not $full.StartsWith($rootFull,[StringComparison]::OrdinalIgnoreCase)) { return $false }
    $current = $RepoRoot
    foreach ($part in $RelativePath.Replace('\','/').Split('/')) {
        $current = Join-Path $current $part
        if (-not (Test-Path -LiteralPath $current)) { return $false }
        try { $item = Get-Item -LiteralPath $current -Force } catch { return $false }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { return $false }
    try { $resolved = (Resolve-Path -LiteralPath $full -ErrorAction Stop).ProviderPath } catch { return $false }
    return $resolved.StartsWith($rootFull,[StringComparison]::OrdinalIgnoreCase)
}

function Assert-SnapshotArchiveSafe {
    param([Parameter(Mandatory=$true)][string]$ArchivePath)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $manifestSeen = $false
        foreach ($entry in $archive.Entries) {
            $member = $entry.FullName.Replace('\','/')
            if ($member -eq 'SNAPSHOT_MANIFEST.txt') {
                if ($manifestSeen) { throw 'Archive validation failed: duplicate manifest.' }
                $manifestSeen = $true
                $reader = New-Object IO.StreamReader($entry.Open())
                try { $manifestText = $reader.ReadToEnd() } finally { $reader.Dispose() }
                if ($manifestText -notmatch '(?m)^Home Hub - ChatGPT Snapshot Manifest$' -or
                    $manifestText -match '(?im)^(Repository|Origin)\s*:' -or
                    $manifestText -match '(?i)(https?://|git@|\.git/config)') {
                    throw 'Archive validation failed: unsafe manifest.'
                }
                continue
            }
            if (-not (Test-SnapshotPath $member)) {
                throw 'Archive validation failed: disallowed member.'
            }
        }
        if (-not $manifestSeen) { throw 'Archive validation failed: missing manifest.' }
    } finally {
        $archive.Dispose()
    }
}

# Dot-sourcing loads the policy functions for focused synthetic tests.
if ($MyInvocation.InvocationName -eq '.') { return }

$inside = Invoke-Git @('rev-parse','--is-inside-work-tree')
if (($inside | Select-Object -First 1).Trim() -ne 'true') { throw 'Expected a Git worktree.' }
New-Item -ItemType Directory -Force -Path $SnapshotsDir | Out-Null
$branch = ((Invoke-Git @('branch','--show-current')) | Select-Object -First 1).Trim()
if (-not $branch) { $branch = 'detached' }
$sha = ((Invoke-Git @('rev-parse','--short=12','HEAD')) | Select-Object -First 1).Trim()
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$zipName = "home-hub-chatgpt-$timestamp-$sha.zip"
$zipPath = Join-Path $SnapshotsDir $zipName
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "home-hub-chatgpt-$timestamp-$PID"
$stageRoot = Join-Path $tempRoot 'home-hub'
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
$included = New-Object 'System.Collections.Generic.List[string]'
$skippedCount = 0
$maxFileBytes = 25MB

try {
    $tracked = @(Invoke-Git @('ls-files','--cached'))
    $untracked = @(Invoke-Git @('ls-files','--others','--exclude-standard'))
    foreach ($relative in @($tracked + $untracked | Sort-Object -Unique)) {
        if (-not (Test-SnapshotPath $relative) -or -not (Test-SafeRepositoryFile $relative)) { $skippedCount++; continue }
        try { $item = Get-Item -LiteralPath (Join-Path $RepoRoot $relative) -Force } catch { $skippedCount++; continue }
        if ($item.Length -gt $maxFileBytes) { $skippedCount++; continue }
        $dest = Join-Path $stageRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
        $included.Add($relative) | Out-Null
    }

    $manifest = @"
Home Hub - ChatGPT Snapshot Manifest
====================================

Created:        $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')
Branch:         $branch
HEAD:           $sha
Files included: $($included.Count)
Files skipped:  $skippedCount

Snapshot policy
---------------
- Includes allowlisted source, documentation, and safe examples only.
- Excludes local credentials/configuration, runtime and generated files, and unsafe paths.
- Does not include Git metadata or remote configuration.
"@
    Set-Content -LiteralPath (Join-Path $stageRoot 'SNAPSHOT_MANIFEST.txt') -Value $manifest -Encoding UTF8

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $zipPath) { throw 'Snapshot archive path already exists.' }
    [IO.Compression.ZipFile]::CreateFromDirectory($stageRoot,$zipPath,[IO.Compression.CompressionLevel]::Optimal,$false)

    # Independently apply the same policy to every final archive member.
    Assert-SnapshotArchiveSafe -ArchivePath $zipPath
    Write-Host "Snapshot created successfully."
    Write-Host "Path: $zipPath"
    Write-Host "Files: $($included.Count)"
    Write-Host "Branch: $branch"
    Write-Host "HEAD: $sha"
}
catch {
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue }
    throw
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
