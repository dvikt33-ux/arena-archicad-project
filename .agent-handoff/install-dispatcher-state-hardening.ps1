# Safe incremental state/terminal-loop repair for AI Dispatcher 2.2.19.
# ASCII-only script for Windows PowerShell 5.1; never edits the GitHub mailbox.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo '.agent-handoff'
$dispatcher = Join-Path $handoff 'dispatcher.py'
$helper = Join-Path $handoff 'control_reply_handoff.py'
$statePath = Join-Path $HOME '.ai-dispatcher-state.json'
$controlPath = Join-Path $HOME '.ai-dispatcher-control.json'
$codeCommit = 'a8c74ea8f7afa228afad36decaa943c21170e978'
$oldBlob = '25f705baa274676ba88aeaab82e31896e8a1309e'
$newBlob = '9b2368367e916d4e8ace1fb06ed038cf05fd5026'
$helperBlob = 'b79a002bcdd1bb517421c9b2f6792f00cd5e1d75'
$controlURL = 'https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a'
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$codeCommit/.agent-handoff"
$stage = Join-Path $env:TEMP ('dispatcher-hardening-' + [guid]::NewGuid().ToString('N'))
$stagedHandoff = Join-Path $stage '.agent-handoff'
$stagedTests = Join-Path $stagedHandoff 'tests'
$null = New-Item -ItemType Directory -Path $stagedTests -Force

function Refuse([string]$reason) { throw "STOP: $reason" }
function FileBlob([string]$path) {
    $resolved = [IO.Path]::GetFullPath($path)
    $root = [IO.Path]::GetFullPath($repo).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        $relative = $resolved.Substring($root.Length).Replace('\','/')
        $hash = & git.exe -C $repo hash-object ('--path=' + $relative) -- $resolved 2>$null
    } else {
        $hash = & git.exe -C $repo hash-object -- $resolved 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or !$hash) { Refuse 'source blob verification failed' }
    return ([string]$hash).Trim()
}
function MutexPresent {
    $handle = $null
    try {
        return [bool][Threading.Mutex]::TryOpenExisting('Local\AI_Dispatcher_22', [ref]$handle)
    } finally {
        if ($handle) { $handle.Dispose() }
    }
}
function AssertSafeState {
    $record = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$record.chatgpt_control_url -ne $controlURL) {
        Refuse 'unexpected CONTROL identity'
    }
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $pending = $state.inflight
    if ($null -eq $pending) {
        if ([int]$state.last_turn_id -lt 87) { Refuse 'unexpected idle turn number' }
        return
    }
    if ([int]$state.last_turn_id -ne 86 -or
        [int]$pending.turn_id -ne 87 -or
        [string]$pending.target -ne 'GPT' -or
        $pending.terminal_report -ne $true -or
        [string]$pending.wake -notmatch 'turn_id=87$' -or
        $pending.wake_seen -ne $true -or
        $pending.submitted -ne $true -or
        [int]$pending.send_attempts -ne 1 -or
        [string]$pending.wake_seen_control_identity -ne '6ad27341-1ea4-83eb-8238-5ce1cada094a' -or
        $pending.terminal_resume_intent -eq $true) {
        Refuse 'queue is not the pinned pending terminal 87'
    }
}
if (!(Test-Path -LiteralPath $dispatcher) -or !(Test-Path -LiteralPath $helper) -or
    !(Test-Path -LiteralPath $statePath) -or !(Test-Path -LiteralPath $controlPath)) {
    Refuse 'existing dispatcher, helper, queue or CONTROL record missing'
}
AssertSafeState
$initialQueueHash = (Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash
if ((FileBlob $helper) -ne $helperBlob) {
    Refuse 'CONTROL multi-ACK helper is not verified baseline'
}
$current = FileBlob $dispatcher
if ($current -eq $newBlob) {
    Write-Host 'ALREADY INSTALLED: reviewed dispatcher state hardening.'
    exit 0
}
if ($current -ne $oldBlob) {
    Refuse 'dispatcher source is not the pinned 25f705 baseline'
}
$normalPath = $dispatcher.Replace('/','\').ToLowerInvariant()
$processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
        $cmd.Contains($normalPath)
})
if ($processes.Count -ne 1 -or !(MutexPresent)) {
    Refuse 'dispatcher Python process/mutex identity ambiguous'
}
$process = $processes[0]
$python = [string]$process.ExecutablePath
if (!(Test-Path -LiteralPath $python)) { Refuse 'running Python executable not accessible' }

Write-Host 'Staging pinned dispatcher safety update and tests...'
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile (Join-Path $stagedHandoff 'dispatcher.py')
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/control_reply_handoff.py" -OutFile (Join-Path $stagedHandoff 'control_reply_handoff.py')
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/install-control-reply-handoff.ps1" -OutFile (Join-Path $stagedHandoff 'install-control-reply-handoff.ps1')
foreach ($name in @(
    'test_control_reply_handoff.py','test_control_marker_fallback.py',
    'test_stale_control_rescue.py','test_arena_feedback_dismiss.py',
    'test_control_multi_ack.py','test_dispatcher_state_loop.py','test_arena_feedback_inline.py',
    'test_dispatcher_atmost_once.py','test_dispatcher_recovery_contract.py',
    'test_arena_terminal_receipt.py','test_control_terminal_resume.py'
)) {
    Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/$name" -OutFile (Join-Path $stagedTests $name)
}
if ((FileBlob (Join-Path $stagedHandoff 'dispatcher.py')) -ne $newBlob -or
    (FileBlob (Join-Path $stagedHandoff 'control_reply_handoff.py')) -ne $helperBlob) {
    Refuse 'staged pinned file hash mismatch'
}
& $python -m py_compile (Join-Path $stagedHandoff 'dispatcher.py') (Join-Path $stagedHandoff 'control_reply_handoff.py')
if ($LASTEXITCODE -ne 0) { Refuse 'Python compile failed; installed code untouched' }
& $python -m unittest discover -s $stagedTests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { Refuse 'regression suite failed; installed code untouched' }

# Safe to restart ONLY an idle dispatcher with exactly matching current state.
AssertSafeState
if ((FileBlob $dispatcher) -ne $oldBlob -or
    (FileBlob $helper) -ne $helperBlob -or !(MutexPresent) -or
    !(Get-Process -Id ([int]$process.ProcessId) -ErrorAction SilentlyContinue)) {
    Refuse 'live dispatcher changed while staging; install skipped'
}
$backup = "$dispatcher.before-state-hardening-$($current.Substring(0,12)).bak"
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
    for ($j=0; $j -lt 40; $j++) {
        if (!(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(MutexPresent)) { break }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -or (MutexPresent)) {
        Refuse 'dispatcher did not release mutex; existing code kept'
    }
    # Close the last-moment race between idle precheck and process stop.
    # On changed state, restart the original dispatcher without a file edit.
    AssertSafeState
    if ((Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash -ne $initialQueueHash) {
        Refuse 'queue changed while staging; original code restarted'
    }
    $temporary = "$dispatcher.installing"
    Copy-Item -LiteralPath (Join-Path $stagedHandoff 'dispatcher.py') -Destination $temporary -Force
    [IO.File]::Replace($temporary, $dispatcher,
        ("$dispatcher.replace-" + [guid]::NewGuid().ToString('N') + '.bak'))
    $replaced = $true
    if ((FileBlob $dispatcher) -ne $newBlob) {
        Refuse 'installed dispatcher hash mismatch'
    }
} catch {
    if ($stopped -and $replaced) {
        Copy-Item -LiteralPath $backup -Destination $dispatcher -Force
    }
    throw
} finally {
    if ($stopped -and !(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(MutexPresent)) {
        $started = Start-Process -FilePath $python -ArgumentList @('-u', ('"' + $dispatcher + '"')) -WorkingDirectory $handoff -PassThru
        Start-Sleep -Seconds 6
    }
}
if ($started -and $started.HasExited) { Refuse 'dispatcher exited after restart; check log' }
if (!(MutexPresent)) { Refuse 'dispatcher mutex not restored' }
if ((FileBlob $dispatcher) -ne $newBlob) { Refuse 'installed source changed after restart' }
Write-Host 'INSTALL PASS: one-shot CONTROL ACK recovery installed.'
Write-Host 'Queue preserved, pending turn 87 will resume once. No mailbox, PLN or main writes.'
Write-Host 'LIVE confirmation of recovered CONTROL ACK is still pending.'
Write-Host "Backup: $backup"
