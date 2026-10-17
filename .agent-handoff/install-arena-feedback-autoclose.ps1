# Incremental Arena finished-task overlay repair for AI Dispatcher 2.2.19.
# Update ONLY dispatcher.py. Preserve queue, CONTROL URL, token, and mailbox.
# Intended for Windows PowerShell 5.1; entire script is 7-bit ASCII.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo ".agent-handoff"
$dispatcher = Join-Path $handoff "dispatcher.py"
$helper = Join-Path $handoff "control_reply_handoff.py"
$statePath = Join-Path $HOME ".ai-dispatcher-state.json"
$controlPath = Join-Path $HOME ".ai-dispatcher-control.json"
$sourceCommit = "b33e8c0fb3e11ade93ebdb3e99783d0791dcaed3"
$oldDispatcherBlob = "227ca28fd9b911a327c1012888c1089df9e273e2"
$newDispatcherBlob = "191a1d7b54aa14cee23ce06b3965780766063824"
$requiredHelperBlob = "eb4d64030a027940d9fee50255fd66953f5fd40d"
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$sourceCommit/.agent-handoff"
$stage = Join-Path $env:TEMP ("arena-feedback-autoclose-" + [guid]::NewGuid().ToString("N"))
$tests = Join-Path $stage "tests"
$null = New-Item -ItemType Directory -Path $tests -Force

function Stop-Install([string]$reason) { throw "STOP: $reason" }
function GitBlob([string]$path) {
    $resolved = [IO.Path]::GetFullPath($path)
    $root = [IO.Path]::GetFullPath($repo).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) {
        $relative = $resolved.Substring($root.Length).Replace('\','/')
        $sha = & git.exe -C $repo hash-object ("--path=" + $relative) -- $resolved 2>$null
    } else {
        $sha = & git.exe -C $repo hash-object -- $resolved 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or !$sha) { Stop-Install "source hash could not be verified" }
    return ([string]$sha).Trim()
}
function HasMutex {
    $mutex = $null
    try { return [bool][Threading.Mutex]::TryOpenExisting("Local\AI_Dispatcher_22", [ref]$mutex) }
    finally { if ($mutex) { $mutex.Dispose() } }
}

if (!(Test-Path -LiteralPath $dispatcher) -or !(Test-Path -LiteralPath $helper) -or
    !(Test-Path -LiteralPath $statePath) -or !(Test-Path -LiteralPath $controlPath)) {
    Stop-Install "installed dispatcher, helper, state or CONTROL record missing"
}
$record = Get-Content -LiteralPath $controlPath -Encoding UTF8 -Raw | ConvertFrom-Json
if ([string]$record.chatgpt_control_url -ne "https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a") {
    Stop-Install "unexpected CONTROL identity"
}
$state = Get-Content -LiteralPath $statePath -Encoding UTF8 -Raw | ConvertFrom-Json
if ([int]$state.last_turn_id -lt 76) { Stop-Install "turn 76 is not marked consumed" }
if ((GitBlob $helper) -ne $requiredHelperBlob) { Stop-Install "CONTROL helper differs from the verified live installation" }
$existing = GitBlob $dispatcher
if ($existing -eq $newDispatcherBlob) {
    Write-Host "ALREADY INSTALLED: Arena feedback auto-close, no restart necessary."
    exit 0
}
if ($existing -ne $oldDispatcherBlob) { Stop-Install "dispatcher hash differs from the approved live baseline" }

Write-Host "Downloading pinned Arena auto-close patch and focused tests..."
$incoming = Join-Path $stage "dispatcher.py"
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile $incoming
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/test_arena_feedback_dismiss.py" -OutFile (Join-Path $tests "test_arena_feedback_dismiss.py")
if ((GitBlob $incoming) -ne $newDispatcherBlob) { Stop-Install "downloaded dispatcher does not match pinned commit" }

$targetNorm = $dispatcher.Replace('/','\').ToLowerInvariant()
$processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $line = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
        $line.Contains($targetNorm)
})
if ($processes.Count -ne 1 -or !(HasMutex)) { Stop-Install "running dispatcher ownership ambiguous or mutex missing" }
$process = $processes[0]
$python = [string]$process.ExecutablePath
if (!(Test-Path -LiteralPath $python)) { Stop-Install "running dispatcher Python executable is not accessible" }

& $python -m py_compile $incoming
if ($LASTEXITCODE -ne 0) { Stop-Install "patched Python syntax invalid; no installation performed" }
& $python -m unittest discover -s $tests -p "test_arena_feedback_dismiss.py" -v
if ($LASTEXITCODE -ne 0) { Stop-Install "Arena overlay regression failed; no installation performed" }

$backup = "$dispatcher.before-arena-feedback-$($existing.Substring(0,12)).bak"
if (!(Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $dispatcher -Destination $backup -ErrorAction Stop }
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
        Stop-Install "dispatcher process did not release mutex; existing source remains unchanged"
    }
    $tempDestination = "$dispatcher.installing"
    Copy-Item -LiteralPath $incoming -Destination $tempDestination -Force
    [IO.File]::Replace(
        $tempDestination, $dispatcher,
        ("$dispatcher.replace-" + [guid]::NewGuid().ToString("N") + ".bak")
    )
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
if ($started -and $started.HasExited) { Stop-Install "restarted dispatcher exited; see dispatcher log and backup" }
if (!(HasMutex)) { Stop-Install "dispatcher mutex did not return after restart" }
if ((GitBlob $dispatcher) -ne $newDispatcherBlob) { Stop-Install "installed dispatcher was modified after restart" }
Write-Host "INSTALL PASS: Arena auto-close installed; running dispatcher restarted."
Write-Host "State, CONTROL URL, GitHub signal and helper were NOT modified."
Write-Host "LIVE ARENA OVERLAY CLOSURE: pending; check next Arena overlay and dispatcher log."
Write-Host "Backup: $backup"
