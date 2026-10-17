# Recover existing CONTROL turn 78 with historical wake/ACK pairs.
# 7-bit ASCII for Windows PowerShell 5.1; no persistent execution-policy changes.
# Only replaces control_reply_handoff.py. No queue, token or GitHub writes.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo ".agent-handoff"
$module = Join-Path $handoff "control_reply_handoff.py"
$dispatcher = Join-Path $handoff "dispatcher.py"
$statePath = Join-Path $HOME ".ai-dispatcher-state.json"
$controlPath = Join-Path $HOME ".ai-dispatcher-control.json"
$codeCommit = "d365e2fa08c58575499938d43203c3beaf3fa0f6"
$previousHelperBlob = "eb4d64030a027940d9fee50255fd66953f5fd40d"
$newHelperBlob = "b79a002bcdd1bb517421c9b2f6792f00cd5e1d75"
$dispatcherBlob = "37bed0d797bae940a2ad52b7445fbbb8f36aedcb"
$controlUrl = "https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$codeCommit/.agent-handoff"
$stage = Join-Path $env:TEMP ("arena-control-multiack-" + [guid]::NewGuid().ToString("N"))
$stageHandoff = Join-Path $stage ".agent-handoff"
$tests = Join-Path $stageHandoff "tests"
$null = New-Item -ItemType Directory -Path $tests -Force

function Stop-Install([string]$reason) { throw "STOP: $reason" }
function GitBlob([string]$path) {
    $resolved = [IO.Path]::GetFullPath($path)
    $root = [IO.Path]::GetFullPath($repo).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        $relative = $resolved.Substring($root.Length).Replace('\','/')
        $sha = & git.exe -C $repo hash-object ("--path=" + $relative) -- $resolved 2>$null
    } else {
        $sha = & git.exe -C $repo hash-object -- $resolved 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or !$sha) { Stop-Install "file hash cannot be verified" }
    return ([string]$sha).Trim()
}
function HasMutex {
    $mutex = $null
    try { return [bool][Threading.Mutex]::TryOpenExisting("Local\AI_Dispatcher_22", [ref]$mutex) }
    finally { if ($mutex) { $mutex.Dispose() } }
}
function Assert-State {
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$state.last_turn_id -ne 77 -or
        [int]$state.inflight.turn_id -ne 78 -or
        [string]$state.inflight.target -ne "GPT" -or
        !$state.inflight.wake_seen -or !$state.inflight.submitted) {
        Stop-Install "turn 78 is not the reviewed pending GPT delivery; no changes made"
    }
}
if (!(Test-Path -LiteralPath $module) -or !(Test-Path -LiteralPath $dispatcher) -or
    !(Test-Path -LiteralPath $statePath) -or !(Test-Path -LiteralPath $controlPath)) {
    Stop-Install "installed module, dispatcher or state is missing"
}
$control = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$control.chatgpt_control_url -ne $controlUrl) { Stop-Install "unexpected CONTROL identity" }
if ((GitBlob $dispatcher) -ne $dispatcherBlob) { Stop-Install "dispatcher is not the reviewed live version" }
$current = GitBlob $module
if ($current -eq $newHelperBlob) {
    Write-Host "ALREADY INSTALLED: multi-ACK parser verified by hash."
    exit 0
}
if ($current -ne $previousHelperBlob) { Stop-Install "helper differs from reviewed installed baseline" }
Assert-State

$target = $dispatcher.Replace('/','\').ToLowerInvariant()
$processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $line = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
    $line.Contains($target)
})
if ($processes.Count -ne 1 -or !(HasMutex)) {
    Stop-Install "running dispatcher process or mutex is ambiguous"
}
$process = $processes[0]
$python = [string]$process.ExecutablePath
if (!(Test-Path -LiteralPath $python)) { Stop-Install "dispatcher Python not accessible" }

Write-Host "Staging pinned multi-ACK helper and regression suite..."
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/control_reply_handoff.py" -OutFile (Join-Path $stageHandoff "control_reply_handoff.py")
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile (Join-Path $stageHandoff "dispatcher.py")
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/install-control-reply-handoff.ps1" -OutFile (Join-Path $stageHandoff "install-control-reply-handoff.ps1")
foreach ($name in @("test_control_reply_handoff.py","test_control_marker_fallback.py",
    "test_stale_control_rescue.py","test_arena_feedback_dismiss.py","test_control_multi_ack.py")) {
    Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/$name" -OutFile (Join-Path $tests $name)
}
if ((GitBlob (Join-Path $stageHandoff "control_reply_handoff.py")) -ne $newHelperBlob -or
    (GitBlob (Join-Path $stageHandoff "dispatcher.py")) -ne $dispatcherBlob) {
    Stop-Install "pinned source hashes differ; no changes made"
}
& $python -m py_compile (Join-Path $stageHandoff "control_reply_handoff.py") (Join-Path $stageHandoff "dispatcher.py")
if ($LASTEXITCODE -ne 0) { Stop-Install "Python syntax failed; no changes made" }
& $python -m unittest discover -s $tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { Stop-Install "regression tests failed; no changes made" }

# Probe the real, persisted CONTROL page with the EXACT staged parser.
# Never print the response body or GitHub token; no browser action is performed.
$probeSource = @'
import sys, json
from playwright.sync_api import sync_playwright
sys.path.insert(0, sys.argv[1])
from control_reply_handoff import _read_verified_ack_pair, parse_control_reply
with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9223", timeout=8000)
    url = sys.argv[2].rstrip("/")
    pages = [page for ctx in browser.contexts for page in ctx.pages
             if page.url.split("?", 1)[0].split("#", 1)[0].rstrip("/") == url]
    if len(pages) != 1:
        print("STOP: CONTROL page_count =", len(pages))
        sys.exit(8)
    diag = {}
    messages = _read_verified_ack_pair(pages[0], diag)
    reply = parse_control_reply(messages, 78)
    print("LIVE READ-ONLY: reason =", diag.get("reason"),
          "pairs =", len(messages) // 2,
          "turn78 =", bool(reply))
    if diag.get("reason") != "verified" or not reply:
        sys.exit(9)
    print("LIVE PRECHECK PASS: existing turn 78 ACK is recognized")
'@
$probeFile = Join-Path $stage "probe_multi_ack.py"
[IO.File]::WriteAllText($probeFile, $probeSource, [Text.UTF8Encoding]::new($false))
& $python $probeFile $stageHandoff $controlUrl
if ($LASTEXITCODE -ne 0) { Stop-Install "live CONTROL readback failed; no changes made" }
Assert-State

$backup = "$module.before-multi-ack-$($current.Substring(0,12)).bak"
if (!(Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath $module -Destination $backup -ErrorAction Stop
}
$pidToStop = [int]$process.ProcessId
$stopped = $false
$replaced = $false
$started = $null
try {
    Stop-Process -Id $pidToStop -ErrorAction Stop
    $stopped = $true
    for ($j=0; $j -lt 40; $j++) {
        if (!(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(HasMutex)) { break }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -or (HasMutex)) {
        Stop-Install "dispatcher did not release mutex; helper unchanged"
    }
    $temporary = "$module.installing"
    Copy-Item -LiteralPath (Join-Path $stageHandoff "control_reply_handoff.py") -Destination $temporary -Force
    [IO.File]::Replace(
        $temporary, $module,
        ("$module.replace-" + [guid]::NewGuid().ToString("N") + ".bak")
    )
    $replaced = $true
    if ((GitBlob $module) -ne $newHelperBlob) {
        Stop-Install "installed helper hash differs"
    }
} catch {
    if ($stopped -and $replaced) {
        Copy-Item -LiteralPath $backup -Destination $module -Force
    }
    throw
} finally {
    if ($stopped -and !(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(HasMutex)) {
        $started = Start-Process -FilePath $python -ArgumentList @("-u", ('"' + $dispatcher + '"')) -WorkingDirectory $handoff -PassThru
        Start-Sleep -Seconds 6
    }
}
if ($started -and $started.HasExited) { Stop-Install "dispatcher restart exited; check log" }
if (!(HasMutex)) { Stop-Install "dispatcher mutex missing after restart" }
if ((GitBlob $module) -ne $newHelperBlob) { Stop-Install "installed helper hash changed after restart" }
Write-Host "INSTALL PASS: multi-ACK CONTROL parser installed; dispatcher restarted."
Write-Host "No changes to queue, CONTROL identity, GitHub signal, or dispatcher.py."
Write-Host "Turn 78 completion still requires GitHub CAS readback and local consume."
Write-Host "Backup: $backup"
