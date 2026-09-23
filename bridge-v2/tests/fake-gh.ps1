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

function Get-RequestedPage {
    param([string]$Text)
    $m = [regex]::Match($Text, '(?:^|[^A-Za-z0-9_])page=([0-9]+)')
    if ($m.Success) { return [int]$m.Groups[1].Value }
    return 1
}

function Write-RepeatedJson {
    param([string]$Item, [int]$Count)
    $items = @()
    for ($i = 0; $i -lt $Count; $i++) { $items += $Item }
    [Console]::Out.WriteLine('[' + ($items -join ',') + ']')
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
if ($line -match '--method PUT' -or $line -match '-X PUT') {
    [Console]::Out.WriteLine('{"content":{"name":"queued"}}')
    exit 0
}
if ($line -match '--method DELETE' -or $line -match '-X DELETE') {
    if ($env:FAKE_GH_DELETE_FAIL -eq '1') { exit 1 }
    if ($line -notmatch '/contents/inbox/') { exit 1 }
    [Console]::Out.WriteLine('{}')
    exit 0
}

$dir = $env:FAKE_MAILBOX_DIR
if ($line -match '/contents/inbox/([^/\s]+)\.json') {
    $id = $Matches[1]
    if ($id -match '^[A-Za-z0-9-]+$' -and -not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir ("content-" + $id + ".json")
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
    $page = Get-RequestedPage $line
    if ($page -gt 1 -and $env:FAKE_GH_COLLAB_PAGE2_FAIL -eq '1') { exit 1 }
    $owner = '{"login":"dvikt33-ux","permissions":{"admin":true,"maintain":true,"push":true,"triage":true,"pull":true}}'
    if ($env:FAKE_GH_COLLAB_ALL_FULL -eq '1') {
        Write-RepeatedJson $owner 100
        exit 0
    }
    if ($page -eq 1 -and $env:FAKE_GH_COLLAB_FULL -eq '1') {
        Write-RepeatedJson $owner 100
        exit 0
    }
    if ($page -gt 1) {
        if (-not [string]::IsNullOrWhiteSpace($dir)) {
            $f = Join-Path $dir ("collaborators-page" + $page + ".json")
            if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
        }
        [Console]::Out.WriteLine('[]')
        exit 0
    }
    if (-not [string]::IsNullOrWhiteSpace($dir)) {
        $f = Join-Path $dir 'collaborators.json'
        if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
    }
    [Console]::Out.WriteLine('[{"login":"dvikt33-ux","permissions":{"admin":true,"maintain":true,"push":true,"triage":true,"pull":true}}]')
    exit 0
}
if ($line -match '/keys') {
    if ($env:FAKE_GH_KEYS_FAIL -eq '1') { exit 1 }
    $page = Get-RequestedPage $line
    if ($page -gt 1 -and $env:FAKE_GH_KEYS_PAGE2_FAIL -eq '1') { exit 1 }
    $key = '{"id":1,"key":"ssh-ed25519 AAAA","read_only":true}'
    if ($env:FAKE_GH_KEYS_ALL_FULL -eq '1') {
        Write-RepeatedJson $key 100
        exit 0
    }
    if ($page -eq 1 -and $env:FAKE_GH_KEYS_FULL -eq '1') {
        Write-RepeatedJson $key 100
        exit 0
    }
    if ($page -gt 1) {
        if (-not [string]::IsNullOrWhiteSpace($dir)) {
            $f = Join-Path $dir ("keys-page" + $page + ".json")
            if (Test-Path -LiteralPath $f) { Write-RawFile $f; exit 0 }
        }
        [Console]::Out.WriteLine('[]')
        exit 0
    }
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
