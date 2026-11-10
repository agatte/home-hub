# One-shot #431 Last.fm recent-tracks checker. Read-only and aggregate-only.
# Opt-in execution only. NOT imported by HomeHub runtime or scheduled.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]{2,32}$')]
    [string]$Username,
    [ValidateRange(1, 50)]
    [int]$Limit = 50,
    [string]$ConfigFile,
    [string]$OfflineFixtureJson,
    [switch]$OfflineFixtureStdin
)
# Provider JSON has legitimate optional properties; validate required fields
# and deliberately treat absent track fields as abstentions.
$ErrorActionPreference = 'Stop'
$phase = 'initialization'
$apiKey = $null
try {
    if ($OfflineFixtureStdin -or $OfflineFixtureJson) {
        # Synthetic fixtures only; never accepted as source-backed evidence.
        $phase = 'offline_fixture'
        $raw = if ($OfflineFixtureStdin) { [Console]::In.ReadToEnd() }
               else { $OfflineFixtureJson }
    } else {
        $phase = 'key_availability'
        $apiKey = [Environment]::GetEnvironmentVariable('LASTFM_API_KEY')
        if ([string]::IsNullOrWhiteSpace($apiKey) -and $ConfigFile) {
            if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) {
                throw 'Config file unavailable'
            }
            foreach ($line in [IO.File]::ReadLines($ConfigFile)) {
                if ($line -match '^\s*LASTFM_API_KEY\s*=\s*([0-9a-fA-F]{32})\s*(?:#.*)?$') {
                    $apiKey = $Matches[1]
                    break
                }
            }
        }
        if ($apiKey -notmatch '^[0-9a-fA-F]{32}$') {
            throw 'Last.fm API key unavailable'
        }
        $phase = 'https_get'
        $uri = 'https://ws.audioscrobbler.com/2.0/?' +
            'method=user.getrecenttracks&format=json&page=1&limit=' + $Limit +
            '&user=' + [Uri]::EscapeDataString($Username) +
            '&api_key=' + [Uri]::EscapeDataString($apiKey)
        # Use the Windows trust store. Never turn off certificate checks.
        # Never print an exception: HTTP exceptions may contain the key-bearing URL.
        $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $uri `
            -MaximumRedirection 0 -TimeoutSec 15 -ErrorAction Stop
        if ([int]$response.StatusCode -ne 200) {
            throw 'Unexpected API HTTP status'
        }
        $raw = [string]$response.Content
    }
    $phase = 'response_budget'
    if ([string]::IsNullOrWhiteSpace($raw) -or $raw.Length -gt 512000) {
        throw 'Response outside bounded JSON size'
    }
    $phase = 'parse'
    $data = ConvertFrom-Json -InputObject $raw -ErrorAction Stop
    if ($null -ne $data.error) {
        $code = [int]$data.error
        if ($code -lt 1 -or $code -gt 100) { $code = 0 }
        @{ status = 'api_error'; error_code = $code } | ConvertTo-Json -Compress
        exit 3
    }
    if ($null -eq $data.recenttracks -or $null -eq $data.recenttracks.'@attr') {
        throw 'Unexpected API envelope'
    }
    $attr = $data.recenttracks.'@attr'
    if (-not [string]::Equals([string]$attr.user, $Username,
                             [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Returned account does not match requested account'
    }
    $items = @()
    if ($null -ne $data.recenttracks.track) {
        $items = @($data.recenttracks.track)
    }
    if ($items.Count -gt ($Limit + 1)) {
        throw 'API result count outside budget'
    }
    $phase = 'aggregate'
    $current = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $dated = 0; $nowPlaying = 0; $invalid = 0; $missing = 0
    $today = 0; $week = 0; $newest = 0L; $repeat = 0
    $pairs = 0; $seen = @{}
    foreach ($item in $items) {
        if ([string]$item.'@attr'.nowplaying -eq 'true') {
            $nowPlaying++
            continue
        }
        if ($null -eq $item.date) {
            $missing++
            continue
        }
        $rawTime = [string]$item.date.uts
        $unix = 0L
        if ($rawTime -notmatch '^[0-9]{9,10}$' -or
            -not [long]::TryParse($rawTime, [ref]$unix) -or
            $unix -lt 946684800 -or $unix -gt ($current + 600)) {
            $invalid++
            continue
        }
        $dated++
        if ($unix -gt $newest) { $newest = $unix }
        if (($current - $unix) -le 86400) { $today++ }
        if (($current - $unix) -le 604800) { $week++ }
        if ($seen.ContainsKey($rawTime)) { $repeat++ }
        else { $seen[$rawTime] = $true }
        if ($item.name -is [string] -and $item.name.Length -gt 0 -and
            $null -ne $item.artist -and
            $item.artist.'#text' -is [string] -and
            $item.artist.'#text'.Length -gt 0) { $pairs++ }
    }
    $total = $null
    if ([string]$attr.total -match '^[0-9]{1,9}$') {
        $total = [int]$attr.total
    }
    $result = [ordered]@{
        status = if ($OfflineFixtureStdin -or $OfflineFixtureJson) {
            'synthetic_only'
        } else { 'ok' }
        returned_account_matches_requested = $true
        items_returned = $items.Count
        total_scrobbles_reported = $total
        currently_playing = $nowPlaying
        timestamped_scrobbles = $dated
        missing_timestamp = $missing
        invalid_timestamp = $invalid
        scrobbles_last_24h = $today
        scrobbles_last_7d = $week
        newest_age_hours = if ($newest -gt 0) {
            [math]::Floor(($current - $newest) / 3600)
        } else { $null }
        newest_year = if ($newest -gt 0) {
            [DateTimeOffset]::FromUnixTimeSeconds($newest).Year
        } else { $null }
        timestamps_with_collisions = $repeat
        has_artist_and_track = $pairs
        verified_distinct_play_sessions = 0
        taste_eligible = $false
    }
    $result | ConvertTo-Json -Compress
} catch {
    # No exception messages or raw responses: may contain the query key, user,
    # media labels, or other private values.
    @{ status = 'blocked'; phase = $phase; error_type = $_.Exception.GetType().Name } |
        ConvertTo-Json -Compress
    exit 2
} finally {
    Remove-Variable apiKey, raw, response, uri, data -ErrorAction SilentlyContinue
}
