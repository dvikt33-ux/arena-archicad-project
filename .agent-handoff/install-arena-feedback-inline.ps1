# Incremental recovery for a visible Arena inline completion-feedback card.
# ASCII-only Windows PowerShell 5.1, no permanent execution policy changes.
# Update only dispatcher.py after actual read-only CDP comparison.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo ".agent-handoff"
$dispatcher = Join-Path $handoff "dispatcher.py"
$helper = Join-Path $handoff "control_reply_handoff.py"
$statePath = Join-Path $HOME ".ai-dispatcher-state.json"
$controlPath = Join-Path $HOME ".ai-dispatcher-control.json"
$codeCommit = "b0b3b011754df9a76a940513dcf99c4d0ae8dd58"
$oldDispatcherBlob = "37bed0d797bae940a2ad52b7445fbbb8f36aedcb"
$newDispatcherBlob = "43e3ec9fe9e3d1123533a99f3b0a411726bb86b7"
$requiredHelperBlob = "b79a002bcdd1bb517421c9b2f6792f00cd5e1d75"
$controlUrl = "https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
$arenaUrl = "https://arena.ai/agent/01a09014-9139-71e7-b51b-5b3f8a49d904"
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$codeCommit/.agent-handoff"
$stage = Join-Path $env:TEMP ("arena-feedback-inline-" + [guid]::NewGuid().ToString("N"))
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
    if ($LASTEXITCODE -ne 0 -or !$sha) { Stop-Install "hash check failed" }
    return ([string]$sha).Trim()
}
function HasMutex {
    $mutex = $null
    try { return [bool][Threading.Mutex]::TryOpenExisting("Local\AI_Dispatcher_22", [ref]$mutex) }
    finally { if ($mutex) { $mutex.Dispose() } }
}
function VerifyState {
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$state.last_turn_id -lt 78) {
        Stop-Install "dispatcher state unexpectedly older than turn 78"
    }
    $control = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$control.chatgpt_control_url -ne $controlUrl) {
        Stop-Install "CONTROL identity changed"
    }
}
if (!(Test-Path -LiteralPath $dispatcher) -or
    !(Test-Path -LiteralPath $helper) -or
    !(Test-Path -LiteralPath $statePath) -or
    !(Test-Path -LiteralPath $controlPath)) {
    Stop-Install "expected installed files or state missing"
}
VerifyState
if ((GitBlob $helper) -ne $requiredHelperBlob) {
    Stop-Install "verified CONTROL multi-ACK helper differs"
}
$current = GitBlob $dispatcher
if ($current -eq $newDispatcherBlob) {
    Write-Host "ALREADY INSTALLED: inline Arena feedback detection."
    exit 0
}
if ($current -ne $oldDispatcherBlob) {
    Stop-Install "dispatcher differs from reviewed 37bed0 baseline"
}
$target = $dispatcher.Replace('/','\').ToLowerInvariant()
$processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $line = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
        $line.Contains($target)
})
if ($processes.Count -ne 1 -or !(HasMutex)) {
    Stop-Install "running dispatcher ownership ambiguous"
}
$process = $processes[0]
$python = [string]$process.ExecutablePath
if (!(Test-Path -LiteralPath $python)) {
    Stop-Install "dispatcher Python not found"
}
Write-Host "Downloading pinned inline-feedback patch and regression suite..."
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile (Join-Path $stageHandoff "dispatcher.py")
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/control_reply_handoff.py" -OutFile (Join-Path $stageHandoff "control_reply_handoff.py")
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/install-control-reply-handoff.ps1" -OutFile (Join-Path $stageHandoff "install-control-reply-handoff.ps1")
foreach ($name in @(
    "test_control_reply_handoff.py",
    "test_control_marker_fallback.py",
    "test_stale_control_rescue.py",
    "test_control_multi_ack.py",
    "test_arena_feedback_dismiss.py",
    "test_arena_feedback_inline.py"
)) {
    Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/$name" -OutFile (Join-Path $tests $name)
}
if ((GitBlob (Join-Path $stageHandoff "dispatcher.py")) -ne $newDispatcherBlob -or
    (GitBlob (Join-Path $stageHandoff "control_reply_handoff.py")) -ne $requiredHelperBlob) {
    Stop-Install "staged SHA differs from published patch"
}
& $python -m py_compile (Join-Path $stageHandoff "dispatcher.py")
if ($LASTEXITCODE -ne 0) { Stop-Install "Python syntax check failed" }
& $python -m unittest discover -s $tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { Stop-Install "regression tests failed; no installation" }

# Read-only side-by-side evaluation of exact existing and candidate function.
# If both see the prompt, the issue is in clicking rather than detection.
# If neither sees it, the true DOM markup needs more diagnostics. Fail closed.
$probe = @'
import ast, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

def predicate(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    fn, = [node for node in tree.body if isinstance(node, ast.FunctionDef)
           and node.name == "arena_feedback_visible"]
    env = {}
    code = compile(ast.fix_missing_locations(
        ast.Module(body=[fn], type_ignores=[])), str(path), "exec")
    exec(code, env)
    return env["arena_feedback_visible"]

old = predicate(sys.argv[1])
new = predicate(sys.argv[2])
url = sys.argv[3].rstrip("/")
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223", timeout=8000)
    pages = [page for context in browser.contexts for page in context.pages
             if page.url.split("?",1)[0].split("#",1)[0].rstrip("/") == url]
    if len(pages) != 1:
        print("STOP: Arena tab count:",len(pages))
        sys.exit(7)
    original = old(pages[0])
    proposed = new(pages[0])
    print("LIVE ARENA READ-ONLY: old_detects =",original,
          "new_detects =",proposed)
    if original or not proposed:
        print("STOP: detection regression not proven; no files changed")
        sys.exit(8)
    print("LIVE INLINE FEEDBACK PRECHECK PASS")
'@
$probeFile = Join-Path $stage "probe_inline_feedback.py"
[IO.File]::WriteAllText($probeFile, $probe, [Text.UTF8Encoding]::new($false))
& $python $probeFile $dispatcher (Join-Path $stageHandoff "dispatcher.py") $arenaUrl
if ($LASTEXITCODE -ne 0) {
    Stop-Install "live read-only card detection preflight failed; installation skipped"
}
VerifyState
if ((GitBlob $dispatcher) -ne $oldDispatcherBlob -or
    (GitBlob $helper) -ne $requiredHelperBlob -or !(HasMutex) -or
    !(Get-Process -Id ([int]$process.ProcessId) -ErrorAction SilentlyContinue)) {
    Stop-Install "installed source or running dispatcher changed during staging"
}
$backup = "$dispatcher.before-arena-inline-$($current.Substring(0,12)).bak"
if (!(Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath $dispatcher -Destination $backup -ErrorAction Stop
}
$pidToStop = [int]$process.ProcessId
$stopped = $false
$replaced = $false
$started = $null
try {
    Stop-Process -Id $pidToStop -ErrorAction Stop
    $stopped = $true
    for ($n=0; $n -lt 40; $n++) {
        if (!(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(HasMutex)) { break }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -or (HasMutex)) {
        Stop-Install "dispatcher did not release mutex; original source unchanged"
    }
    $temporary = "$dispatcher.installing"
    Copy-Item -LiteralPath (Join-Path $stageHandoff "dispatcher.py") -Destination $temporary -Force
    [IO.File]::Replace($temporary, $dispatcher,
        ("$dispatcher.replace-" + [guid]::NewGuid().ToString("N") + ".bak"))
    $replaced = $true
    if ((GitBlob $dispatcher) -ne $newDispatcherBlob) {
        Stop-Install "installed dispatcher hash mismatch"
    }
} catch {
    if ($stopped -and $replaced) {
        Copy-Item -LiteralPath $backup -Destination $dispatcher -Force
    }
    throw
} finally {
    if ($stopped -and !(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(HasMutex)) {
        $started = Start-Process -FilePath $python -ArgumentList @("-u", ('"' + $dispatcher + '"')) -WorkingDirectory $handoff -PassThru
        Start-Sleep -Seconds 6
    }
}
if ($started -and $started.HasExited) { Stop-Install "restarted dispatcher exited; inspect log" }
if (!(HasMutex)) { Stop-Install "dispatcher mutex not restored" }
if ((GitBlob $dispatcher) -ne $newDispatcherBlob) {
    Stop-Install "dispatcher modified after restart"
}
Write-Host "INSTALL PASS: inline feedback detection installed and dispatcher restarted."
Write-Host "Queue, CONTROL, token, and GitHub mailbox were not modified by installer."
Write-Host "LIVE DISMISSAL: pending check against active Arena feedback card."
Write-Host "Backup: $backup"
