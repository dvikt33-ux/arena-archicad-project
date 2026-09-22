# fake-gh.ps1 — local stand-in for `gh` used by smoke-test.ps1.
# No network. Prints fixture files. Does not read tokens.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GhArgs
)

$ErrorActionPreference = 'Continue'
$line = @($GhArgs) -join ' '
$log = $env:FAKE_GH_LOG
if (-not [string]::IsNullOrWhiteSpace($log)) {
    try { [System.IO.File]::AppendAllText($log, ($line + "`n")) } catch { }
}

if ($env:FAKE_GH_FAIL -eq '1') { exit 1 }
if ($env:FAKE_GH_SLEEP_SEC -match '^[0-9]+$') {
    Start-Sleep -Seconds ([int]$env:FAKE_GH_SLEEP_SEC)
}

function Write-RawFile {
    param([string]$Path)
    $text = [System.IO.File]::ReadAllText($Path)
    [Console]::Out.Write($text)
    if (-not $text.EndsWith("`n")) { [Console]::Out.Write("`n") }
}

if ($line -match '-X POST' -or $line -match '--method POST') {
    if (-not [string]::IsNullOrWhiteSpace($env:FAKE_GH_SEEN)) {
        try { [System.IO.File]::WriteAllText($env:FAKE_GH_SEEN, 'seen') } catch { }
    }
    if (-not [string]::IsNullOrWhiteSpace($env:FAKE_GH_POST_FILE) -and (Test-Path -LiteralPath $env:FAKE_GH_POST_FILE)) {
        Write-RawFile $env:FAKE_GH_POST_FILE
        exit 0
    }
    [Console]::Out.WriteLine('{"id":999}')
    exit 0
}
if ($line -match '-X PATCH' -or $line -match '--method PATCH') {
    if (-not [string]::IsNullOrWhiteSpace($env:FAKE_GH_POST_FILE) -and (Test-Path -LiteralPath $env:FAKE_GH_POST_FILE)) {
        Write-RawFile $env:FAKE_GH_POST_FILE
        exit 0
    }
    [Console]::Out.WriteLine('{"id":999}')
    exit 0
}

$dir = $env:FAKE_MAILBOX_DIR
if ($line -match '/contents/inbox/([0-9]+)\.json') {
    $seq = $Matches[1]
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir ("content-" + $seq + ".json")
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('{"message":"Not Found"}')
    exit 1
}
if ($line -match '/contents/inbox') {
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir 'index.json'
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('[]')
    exit 0
}
if ($line -match '/commits') {
    $seq = ''
    if ($line -match 'path=inbox/([0-9]+)\.json') { $seq = $Matches[1] }
    if (-not [string]::IsNullOrWhiteSpace($dir) -and $seq -ne '') {
        $f = Join-Path $dir ("commit-" + $seq + ".json")
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir 'commit.json'
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('[]')
    exit 0
}
if ($line -match '/collaborators') {
    if ($env:FAKE_GH_COLLAB_FAIL -eq '1') { exit 1 }
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir 'collaborators.json'
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('[{"login":"dvikt33-ux","permissions":{"admin":true,"maintain":true,"push":true,"triage":true,"pull":true}}]')
    exit 0
}
if ($line -match '/keys') {
    if ($env:FAKE_GH_KEYS_FAIL -eq '1') { exit 1 }
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir 'keys.json'
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('[]')
    exit 0
}
if ($line -match 'repos/' -and $line -notmatch '/contents/' -and $line -notmatch '/commits' -and $line -notmatch '/issues' -and $line -notmatch '/comments') {
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir 'repo.json'
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('{"message":"Not Found"}')
    exit 1
}

if (-not [string]::IsNullOrWhiteSpace($env:FAKE_GH_SEEN) -and (Test-Path -LiteralPath $env:FAKE_GH_SEEN) -and -not [string]::IsNullOrWhiteSpace($env:FAKE_GH_GET_FILE) -and (Test-Path -LiteralPath $env:FAKE_GH_GET_FILE)) {
    Write-RawFile $env:FAKE_GH_GET_FILE
    exit 0
}
[Console]::Out.WriteLine('[]')
exit 0
