# arena-qwen-router-v2.ps1 — Arena Qwen router v2.
#
# Turns a natural-language request into an ACTION ID (never a command string),
# then enqueues it into the bridge inbox as inbox/<seq>.json atomically.
# Qwen/llama-server are unchanged; only the prompt and the enqueue logic differ
# from v1.
#
# Usage:
#   .\arena-qwen-router-v2.ps1
#   .\arena-qwen-router-v2.ps1 -RequestFile C:\path\request.txt -ApiUrl http://127.0.0.1:8080/v1/chat/completions

[CmdletBinding()]
param(
    [string]$RequestFile = "$env:USERPROFILE\Documents\arena-bridge-request.txt",
    [string]$ArenaRoot  = (Join-Path $env:LOCALAPPDATA 'ArenaBridge'),
    [string]$ApiUrl     = 'http://127.0.0.1:8080/v1/chat/completions',
    [string]$Model      = 'C:\LocalAI\models\Qwen3.8-27B-UD-Q4_K_XL.gguf'
)

$ErrorActionPreference = 'Continue'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'arena-common.ps1')

# Same override as the bridge, so a test can sandbox the v1 seed file.
if (-not [string]::IsNullOrWhiteSpace($env:ARENA_BRIDGE_LEGACY_STATE_FILE)) {
    $script:LegacyStateFile = $env:ARENA_BRIDGE_LEGACY_STATE_FILE
}
if (-not [string]::IsNullOrWhiteSpace($env:ARENA_BRIDGE_LEGACY_TASK_FILE)) {
    $script:LegacyTaskFile = $env:ARENA_BRIDGE_LEGACY_TASK_FILE
}

function Invoke-JsonPost {
    # Windows PowerShell 5.1 Invoke-RestMethod encodes -Body with the system
    # ANSI code page and ignores charset=utf-8. HttpWebRequest sends real UTF-8,
    # which matters for Russian requests on a ru-RU machine.
    param([string]$Uri, [string]$Json, [int]$TimeoutSec = 60)
    $req = [System.Net.HttpWebRequest][System.Net.WebRequest]::Create($Uri)
    $req.Method = 'POST'
    $req.ContentType = 'application/json; charset=utf-8'
    $req.Timeout = $TimeoutSec * 1000
    $req.ReadWriteTimeout = $TimeoutSec * 1000
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
    $req.ContentLength = $bytes.Length
    $stream = $req.GetRequestStream()
    try { $stream.Write($bytes, 0, $bytes.Length) }
    finally { $stream.Dispose() }
    $resp = $null
    try {
        $resp = $req.GetResponse()
    }
    catch [System.Net.WebException] {
        $detail = $_.Exception.Message
        $http = $_.Exception.Response
        if ($http) {
            try {
                $errReader = New-Object System.IO.StreamReader($http.GetResponseStream())
                $detail = $errReader.ReadToEnd()
                $errReader.Dispose()
            }
            catch { }
            $http.Close()
        }
        throw $detail
    }
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
    try { $text = $reader.ReadToEnd() }
    finally { $reader.Dispose(); $resp.Close() }
    if ([string]::IsNullOrWhiteSpace($text)) { throw 'empty response' }
    return ($text | ConvertFrom-Json)
}

$inboxDir  = Join-Path $ArenaRoot 'inbox'
$statePath = Join-Path $ArenaRoot 'state.json'
New-Dirs $ArenaRoot

if (-not (Test-Path -LiteralPath $RequestFile)) {
    Write-Host 'ERROR: request file not found:'
    Write-Host $RequestFile
    exit 1
}

$request = (Get-Content -LiteralPath $RequestFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($request)) {
    Write-Host 'ERROR: request is empty'
    exit 1
}

$body = @{
    model    = $Model
    messages = @(
        @{
            role = 'system'
            content = @"
Ты маршрутизатор команд для локального Arena Bridge.

Пользователь пишет обычную просьбу на русском или английском.
Выбери РОВНО один ACTION ID из списка ниже.
Верни только сам идентификатор, без пояснений, без Markdown, без кавычек.

GIT_VERSION
GIT_STATUS
GIT_DIFF
GIT_LOG10

Если просьба не соответствует ни одному действию, ответь ровно:
BLOCKED
"@
        }
        @{ role = 'user'; content = $request }
    )
    temperature = 0
    max_tokens  = 64
} | ConvertTo-Json -Depth 6

try {
    $response = Invoke-JsonPost -Uri $ApiUrl -Json $body -TimeoutSec 60
}
catch {
    Write-Host 'QWEN API ERROR:'
    Write-Host $_.Exception.Message
    exit 1
}

$choice = @($response.choices)[0]
if ($null -eq $choice -or $null -eq $choice.message) {
    Write-Host 'QWEN RESPONSE INVALID: no choices'
    exit 4
}

$action = ("$($choice.message.content)").Trim().ToUpperInvariant()

Write-Host 'REQUEST:'
Write-Host $request
Write-Host ''
Write-Host 'QWEN ACTION:'
Write-Host $action
Write-Host ''

if ($action -eq 'BLOCKED') {
    Write-Host 'BLOCKED BY QWEN'
    exit 2
}

# Second independent gate: the action MUST be a known ID (exact match).
if ($action -notin $script:ActionIds) {
    Write-Host 'BLOCKED BY ROUTER ALLOWLIST'
    exit 3
}

# ---- enqueue atomically under a router mutex ----
$mutex = [System.Threading.Mutex]::new($false, 'Local\ArenaRouter.v2')
try {
    if (-not $mutex.WaitOne(0)) {
        Write-Host 'Another router is running. Exiting.'
        exit 6
    }
}
catch {
    Write-Host "Mutex init failed: $($_.Exception.Message)"
    exit 6
}

try {
    $lastSeq = 0
    if (Test-Path -LiteralPath $statePath) {
        try {
            $lastSeq = [int](Read-State $statePath).last_seq
        }
        catch {
            Write-Host "FATAL: state.json unreadable: $($_.Exception.Message)"
            exit 7
        }
    }
    else {
        # Same seed rule as the bridge, so seq stays monotonic across first runs.
        $lastSeq = Get-SeedLastSeq $script:LegacyStateFile
    }

    $maxInbox = 0
    Get-ChildItem -LiteralPath $inboxDir -Filter '*.json' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -match '^\d+$' } |
        ForEach-Object { $n = [int]$_.BaseName; if ($n -gt $maxInbox) { $maxInbox = $n } }

    $seq = [Math]::Max($lastSeq, $maxInbox) + 1
    for ($i = 0; $i -lt 100; $i++) {
        if (-not (Test-Path -LiteralPath (Join-Path $inboxDir "$seq.json"))) { break }
        $seq++
    }

    $envObj = [ordered]@{ seq = $seq; action = $action; ts = (Get-Date -Format o); request = $request }
    Write-FileAtomic (Join-Path $inboxDir "$seq.json") ($envObj | ConvertTo-Json -Depth 5 -Compress)

    Write-Host 'SENT TO BRIDGE:'
    Write-Host "$seq|$action"
}
finally {
    try { $mutex.ReleaseMutex() } catch { }
}
