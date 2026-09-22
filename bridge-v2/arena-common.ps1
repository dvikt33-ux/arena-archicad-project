# arena-common.ps1 — shared helpers for Arena Bridge v2 (bridge + router).
# Dot-source this file from arena-bridge-v2.ps1 and arena-qwen-router-v2.ps1.

# ---- action IDs (the ONLY things Qwen may emit) ----
$script:ActionIds = @('GIT_VERSION', 'GIT_STATUS', 'GIT_DIFF', 'GIT_LOG10')

# ---- legacy v1 paths (used only to seed the sequence once) ----
# $env:USERPROFILE exists on Windows; fall back to $env:HOME elsewhere (tests).
$script:UserProfile = $env:USERPROFILE
if ([string]::IsNullOrWhiteSpace($script:UserProfile)) { $script:UserProfile = $env:HOME }
if ([string]::IsNullOrWhiteSpace($script:UserProfile)) { $script:UserProfile = [System.IO.Path]::GetTempPath() }
# Two Join-Path calls: Windows PowerShell 5.1 treats '\' in the child as a
# separator, PowerShell 7 on Linux does too, but a single child with '\' is
# easy to get wrong. Keep the v1 files exactly where v1 wrote them.
$script:LegacyStateFile = Join-Path (Join-Path $script:UserProfile 'Documents') 'arena-bridge-last-task.txt'
$script:LegacyTaskFile  = Join-Path (Join-Path $script:UserProfile 'Documents') 'arena-bridge-task.txt'

function New-Dirs {
    param([string]$ArenaRoot)
    $paths = @(
        $ArenaRoot,
        (Join-Path $ArenaRoot 'inbox'),
        (Join-Path $ArenaRoot 'outbox'),
        (Join-Path $ArenaRoot 'results'),
        (Join-Path $ArenaRoot 'inbox\.done'),
        (Join-Path $ArenaRoot 'outbox\.dead')
    )
    foreach ($p in $paths) {
        if (-not (Test-Path -LiteralPath $p)) {
            New-Item -ItemType Directory -Path $p -Force | Out-Null
        }
    }
}

function Write-FileAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Text = '')
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $tmp = Join-Path $dir ('~' + [guid]::NewGuid().ToString('N') + '.tmp')
    $enc = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($tmp, $Text, $enc)
    try {
        if (Test-Path -LiteralPath $Path) {
            # Atomic replace (Windows .NET Framework). On .NET Core / Unix this
            # throws on a null backup name, so fall back to Move-Item -Force,
            # which is rename-based and still atomic on the same volume.
            try {
                [System.IO.File]::Replace($tmp, $Path, $null)
            }
            catch {
                Move-Item -LiteralPath $tmp -Destination $Path -Force
            }
        }
        else {
            Move-Item -LiteralPath $tmp -Destination $Path -Force
        }
    }
    catch {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Test-OriginMatches {
    param([string]$Origin, [string]$Repo)
    $o = $Origin.Trim()
    $o = $o -replace '\.git/?$', ''
    $o = $o -replace '^https?://', ''
    $o = $o -replace '^ssh://', ''
    $o = $o -replace '^git@', ''
    $o = $o -replace '^github\.com[:/]', ''
    $o = $o.TrimEnd('/')
    return ($o -ieq $Repo)
}

function Read-State {
    # Returns @{ last_seq = <int>; tasks = @{ "<seq>" = @{...} } }.
    # Throws on corrupt/empty/invalid state — callers must fail closed.
    param([string]$StatePath)
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return @{ last_seq = 0; tasks = @{} }
    }
    $raw = Get-Content -LiteralPath $StatePath -Raw -ErrorAction Stop
    if ([string]::IsNullOrWhiteSpace($raw)) { throw 'state file is empty' }
    $s = $null
    try {
        $s = $raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "state file is corrupt: $($_.Exception.Message)"
    }
    if ($null -eq $s -or ($s.PSObject.Properties.Name -notcontains 'last_seq')) {
        throw 'state schema invalid (missing last_seq)'
    }
    $st = @{ last_seq = [int]$s.last_seq; tasks = @{} }
    if ($s.PSObject.Properties.Name -notcontains 'tasks') { return $st }
    foreach ($p in $s.tasks.PSObject.Properties) {
        $v = $p.Value
        $names = $v.PSObject.Properties.Name
        $st.tasks[$p.Name] = @{
            action      = if ($names -contains 'action')      { $v.action }      else { '' }
            state       = if ($names -contains 'state')       { $v.state }       else { '' }
            status      = if ($names -contains 'status')      { $v.status }      else { '' }
            exit        = if ($names -contains 'exit')        { $v.exit }        else { $null }
            result_file = if ($names -contains 'result_file') { $v.result_file } else { '' }
            comment_id  = if ($names -contains 'comment_id')  { $v.comment_id }  else { $null }
            reason      = if ($names -contains 'reason')      { $v.reason }      else { '' }
            pid         = if ($names -contains 'pid')         { $v.pid }         else { $null }
            started     = if ($names -contains 'started')     { $v.started }     else { '' }
            updated     = if ($names -contains 'updated')     { $v.updated }     else { '' }
        }
    }
    return $st
}

function Save-State {
    param([string]$StatePath, $State)
    $obj = [ordered]@{ last_seq = [int]$State.last_seq; tasks = [ordered]@{} }
    foreach ($k in $State.tasks.Keys) {
        $obj.tasks[$k] = $State.tasks[$k]
    }
    $json = $obj | ConvertTo-Json -Depth 12 -Compress
    Write-FileAtomic $StatePath $json
}

function Get-SeedLastSeq {
    # One-time seed from the v1 state file (last completed task id).
    param([string]$LegacyStateFile)
    if (-not (Test-Path -LiteralPath $LegacyStateFile)) { return 0 }
    $raw = "$(Get-Content -LiteralPath $LegacyStateFile -Raw -ErrorAction SilentlyContinue)".Trim()
    $n = 0
    if ($raw -match '^\d+$') { $n = [int]$raw }
    return $n
}
