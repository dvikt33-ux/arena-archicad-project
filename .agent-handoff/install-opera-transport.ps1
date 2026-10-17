# Migrate AI Dispatcher 2.2.19 to the existing Opera profile. PowerShell 5.1 ASCII.
# Never launches Chrome or signs in to a second Opera profile.
# Preserves closed queue 87 and the historical GitHub signal.
param([switch]$StartOnly)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo '.agent-handoff'
$localCore = Join-Path $handoff 'dispatcher.py'
$localRuntime = Join-Path $handoff 'dispatcher-runtime.py'
$homeCore = Join-Path $HOME 'dispatcher_core.py'
$homeRuntime = Join-Path $HOME 'dispatcher.py'
$homeHelper = Join-Path $HOME 'control_reply_handoff.py'
$helper = Join-Path $handoff 'control_reply_handoff.py'
$statePath = Join-Path $HOME '.ai-dispatcher-state.json'
$controlPath = Join-Path $HOME '.ai-dispatcher-control.json'
$oldBlob = '663a905bbe98da4c1170d42a169e52a7dae23d05'
$newBlob = 'c463861c2f40c99381fa9abdc58c27d8f9d773b0'
$newRuntimeBlob = '00809ccd2fcf5ca5f1d3edf5db267c9587db0c96'
$helperBlob = 'b79a002bcdd1bb517421c9b2f6792f00cd5e1d75'
$commit = '0443f414f3a6ee73f5ff0d6b2b7ff54519e2ff67'
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$commit/.agent-handoff"
$pinned = 'https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a'
$rebound = 'https://chatgpt.com/c/6ad3e97f-5980-83eb-babf-d34379e0df0c'

function StopSafe([string]$why) { throw "STOP: $why" }
function Blob([string]$file,[string]$gitPath) {
  $sha = & git.exe -C $repo hash-object ('--path=' + $gitPath) -- $file 2>$null
  if ($LASTEXITCODE -ne 0 -or !$sha) { StopSafe 'git hash unavailable' }
  return ([string]$sha).Trim()
}
function MutexPresent {
  $handle = $null
  try { return [bool][Threading.Mutex]::TryOpenExisting('Local\AI_Dispatcher_22',[ref]$handle) }
  finally { if ($handle) { $handle.Dispose() } }
}
function DispatcherProcesses {
  return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
    ($cmd.Contains($localCore.ToLowerInvariant()) -or
     $cmd.Contains($homeRuntime.ToLowerInvariant()))
  })
}
function QueueCheck {
  $s = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$s.last_turn_id -ne 87 -or $null -ne $s.inflight) {
    StopSafe 'expected completed queue LAST_TURN=87 PENDING=NONE'
  }
  $c = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$c.chatgpt_control_url -notin @($pinned, $rebound)) {
    StopSafe 'CONTROL identity not recognized'
  }
  if ([string]$c.chatgpt_control_url -eq $rebound -and
      ([string]$c.rebind_status -ne 'pending' -or [int]$c.rebind_count -ne 1)) {
    StopSafe 'observed CONTROL rebind state changed'
  }
  return $c
}
function OperaAt9224 {
  try {
    $listener = @(Get-NetTCPConnection -LocalPort 9224 -State Listen -ErrorAction SilentlyContinue)
    $ids = @($listener | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ids.Count -ne 1) { return $false }
    $ownerProc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ids[0])
    if (!$ownerProc -or $ownerProc.Name -notmatch '^(opera|opera\w*|launcher)\.exe$') { return $false }
    if ([string]$ownerProc.CommandLine -notmatch '--remote-debugging-port=9224(\s|$)') { return $false }
    $json = Invoke-RestMethod -UseBasicParsing -TimeoutSec 3 -Uri 'http://127.0.0.1:9224/json/version'
    return ([string]$json.webSocketDebuggerUrl -match '^ws://(127\.0\.0\.1|localhost):9224/devtools/browser/')
  } catch { return $false }
}
function OperaPath {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Opera\launcher.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Opera GX\launcher.exe'),
    (Join-Path $env:ProgramFiles 'Opera\launcher.exe')
  )
  foreach($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  $installed = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(opera|opera\w*|launcher)\.exe$' -and
    $_.ExecutablePath -and (Test-Path -LiteralPath $_.ExecutablePath)
  })
  if ($installed.Count -gt 0) { return [string]$installed[0].ExecutablePath }
  return ''
}
if ($StartOnly) {
  if (!(Test-Path -LiteralPath $localCore) -or
      !(Test-Path -LiteralPath $homeCore) -or
      (Blob $localCore '.agent-handoff/dispatcher.py') -ne $newBlob -or
      (Blob $homeCore '.agent-handoff/dispatcher.py') -ne $newBlob -or
      !(Test-Path -LiteralPath $homeHelper) -or
      (Blob $homeHelper '.agent-handoff/control_reply_handoff.py') -ne $helperBlob) {
    StopSafe 'Opera migration not installed'
  }
  $s = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
  $c = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$s.last_turn_id -ne 87 -or $null -ne $s.inflight -or
      [string]$c.chatgpt_control_url -ne $pinned) {
    StopSafe 'queue or pinned CONTROL changed'
  }
  if (!(OperaAt9224)) { StopSafe 'Opera debug endpoint 127.0.0.1:9224 unavailable or not owned by Opera' }
  $running = @(DispatcherProcesses)
  if ($running.Count -gt 1) { StopSafe 'multiple dispatcher instances' }
  if ($running.Count -eq 0 -and (MutexPresent)) { StopSafe 'dispatcher mutex in use by unknown process' }
  if ($running.Count -eq 1) {
    Write-Host ("OPERA DISPATCHER RUNNING: PID=" + $running[0].ProcessId)
    return
  }
  $python = & py -c 'import sys; print(sys.executable)'
  if ($LASTEXITCODE -ne 0) { StopSafe 'Python missing' }
  $proc = Start-Process -FilePath $python -ArgumentList ('"' + $localCore + '"') -PassThru
  Start-Sleep -Seconds 6
  if ($proc.HasExited) { StopSafe 'dispatcher did not remain running' }
  Write-Host ("OPERA DISPATCHER STARTED: PID=" + $proc.Id)
  Write-Host 'QUEUE LAST_TURN=87 PENDING=NONE, original CONTROL pinned.'
  return
}
foreach($file in @($localCore,$helper,$statePath,$controlPath)) {
  if (!(Test-Path -LiteralPath $file)) { StopSafe "required file missing: $file" }
}
if ((Blob $localCore '.agent-handoff/dispatcher.py') -ne $oldBlob) { StopSafe 'unexpected dispatcher baseline' }
if ((Blob $helper '.agent-handoff/control_reply_handoff.py') -ne $helperBlob) { StopSafe 'unexpected CONTROL parser' }
$control = QueueCheck
$queueSHA = (Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash
$controlSHA = (Get-FileHash -LiteralPath $controlPath -Algorithm SHA256).Hash
$processes = @(DispatcherProcesses)
if ($processes.Count -gt 1) { StopSafe 'multiple dispatcher processes, refusing mutation' }
if ($processes.Count -eq 0 -and (MutexPresent)) { StopSafe 'dispatcher mutex owned by unknown process' }
$stage = Join-Path $env:TEMP ('opera-dispatcher-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $stage '.agent-handoff'
$tests = Join-Path $root 'tests'
New-Item -ItemType Directory -Path $tests -Force | Out-Null
foreach($name in @('dispatcher.py','dispatcher-runtime.py','control_reply_handoff.py','install-control-reply-handoff.ps1')) {
  Invoke-WebRequest -UseBasicParsing -Uri "$prefix/$name" -OutFile (Join-Path $root $name)
}
$names = @(
  'test_control_reply_handoff.py','test_control_marker_fallback.py',
  'test_stale_control_rescue.py','test_arena_feedback_dismiss.py',
  'test_control_multi_ack.py','test_dispatcher_state_loop.py',
  'test_arena_feedback_inline.py','test_dispatcher_atmost_once.py',
  'test_dispatcher_recovery_contract.py','test_arena_terminal_receipt.py',
  'test_control_terminal_resume.py','test_submitted_control_readonly_hold.py',
  'test_terminal_github_receipt_87.py','test_opera_only_transport.py'
)
foreach($name in $names) {
  Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/$name" -OutFile (Join-Path $tests $name)
}
if ((Blob (Join-Path $root 'dispatcher.py') '.agent-handoff/dispatcher.py') -ne $newBlob -or
    (Blob (Join-Path $root 'dispatcher-runtime.py') '.agent-handoff/dispatcher-runtime.py') -ne $newRuntimeBlob -or
    (Blob (Join-Path $root 'control_reply_handoff.py') '.agent-handoff/control_reply_handoff.py') -ne $helperBlob) {
  StopSafe 'downloaded code SHA mismatch'
}
$python = & py -c 'import sys; print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $python)) { StopSafe 'Python missing' }
& $python -c 'from playwright.sync_api import sync_playwright'
if ($LASTEXITCODE -ne 0) { StopSafe 'Python Playwright missing' }
& $python -m py_compile (Join-Path $root 'dispatcher.py') (Join-Path $root 'dispatcher-runtime.py')
if ($LASTEXITCODE -ne 0) { StopSafe 'Python compile failed' }
& $python -m unittest discover -s $tests -p 'test_*.py' -q
if ($LASTEXITCODE -ne 0) { StopSafe 'staged offline suite failed; no files changed' }
if ((Get-FileHash $statePath -Algorithm SHA256).Hash -ne $queueSHA -or
    (Get-FileHash $controlPath -Algorithm SHA256).Hash -ne $controlSHA -or
    (Blob $localCore '.agent-handoff/dispatcher.py') -ne $oldBlob) {
  StopSafe 'state, CONTROL or dispatcher changed during offline checks'
}
$null = QueueCheck
$processes = @(DispatcherProcesses)
if ($processes.Count -gt 1) { StopSafe 'multiple dispatcher processes before install' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach($pair in @(
  @($localCore, (Join-Path $root 'dispatcher.py')),
  @($localRuntime, (Join-Path $root 'dispatcher-runtime.py')),
  @($homeCore, (Join-Path $root 'dispatcher.py')),
  @($homeRuntime, (Join-Path $root 'dispatcher-runtime.py')),
  @($homeHelper, (Join-Path $root 'control_reply_handoff.py'))
)) {
  $dest = [string]$pair[0]
  if (Test-Path -LiteralPath $dest) { Copy-Item -LiteralPath $dest -Destination ($dest + '.before-opera-' + $stamp + '.bak') -ErrorAction Stop }
}
Copy-Item -LiteralPath $controlPath -Destination ($controlPath + '.before-opera-' + $stamp + '.bak') -ErrorAction Stop
if ($processes.Count -eq 1) {
  Stop-Process -Id $processes[0].ProcessId -Force -ErrorAction Stop
  Start-Sleep -Seconds 2
}
if ((DispatcherProcesses).Count -ne 0 -or (MutexPresent)) {
  StopSafe 'dispatcher did not stop, no installation performed'
}
if ((Get-FileHash $statePath -Algorithm SHA256).Hash -ne $queueSHA) { StopSafe 'queue changed after stop' }
foreach($pair in @(
  @($localCore, (Join-Path $root 'dispatcher.py')),
  @($localRuntime, (Join-Path $root 'dispatcher-runtime.py')),
  @($homeCore, (Join-Path $root 'dispatcher.py')),
  @($homeRuntime, (Join-Path $root 'dispatcher-runtime.py')),
  @($homeHelper, (Join-Path $root 'control_reply_handoff.py'))
)) {
  $dest = [string]$pair[0]
  $source = [string]$pair[1]
  Copy-Item -LiteralPath $source -Destination ($dest + '.installing') -Force
  if (Test-Path -LiteralPath $dest) {
    [IO.File]::Replace(($dest + '.installing'),$dest,($dest + '.pre-opera-replace-' + $stamp + '.bak'))
  } else {
    Move-Item -LiteralPath ($dest + '.installing') -Destination $dest
  }
}
$control.chatgpt_control_url = $pinned
$control.rebind_status = 'retired'
$control.rebind_for_url = $rebound
$control | Add-Member -NotePropertyName unready_checks -NotePropertyValue 0 -Force
$json = $control | ConvertTo-Json -Depth 20
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(($controlPath + '.installing'),$json,$utf8NoBom)
[IO.File]::Replace(($controlPath + '.installing'),$controlPath,($controlPath + '.pre-opera-replace-' + $stamp + '.bak'))
if ((Blob $localCore '.agent-handoff/dispatcher.py') -ne $newBlob -or
    (Blob $homeCore '.agent-handoff/dispatcher.py') -ne $newBlob -or
    (Blob $homeRuntime '.agent-handoff/dispatcher-runtime.py') -ne $newRuntimeBlob -or
    (Blob $homeHelper '.agent-handoff/control_reply_handoff.py') -ne $helperBlob) {
  StopSafe 'post-install source validation failed; see backups'
}
if ((Get-FileHash $statePath -Algorithm SHA256).Hash -ne $queueSHA) { StopSafe 'queue changed unexpectedly' }
Write-Host 'OPERA INSTALL PASS: dispatcher source, runtime and autostart core replaced.'
Write-Host 'CONTROL PINNED: original ChatGPT conversation; rebind retired.'
Write-Host 'QUEUE PRESERVED: LAST_TURN=87 PENDING=NONE.'
if (!(OperaAt9224)) {
  $operaExe = OperaPath
  if (!$operaExe) {
    Write-Host 'OPERA NOT FOUND: dispatcher installed but stopped. No Chrome fallback.'
    Write-Host 'Launch Opera with --remote-debugging-port=9224 then rerun -StartOnly.'
    return
  }
  $runningOpera = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^opera.*\.exe$'
  })
  if ($runningOpera.Count -gt 0) {
    Write-Host 'ACTION REQUIRED: close Opera normally via its menu (Exit). Tabs are preserved.'
    $null = Read-Host 'After all Opera windows are closed, press Enter'
    $runningOpera = @(Get-CimInstance Win32_Process | Where-Object {
      $_.Name -match '^opera.*\.exe$'
    })
    if ($runningOpera.Count -gt 0) {
      Write-Host 'OPERA STILL RUNNING: no forced closure; dispatcher remains stopped.'
      Write-Host 'Exit Opera, start it with debugging and rerun installer -StartOnly.'
      return
    }
  }
  Start-Process -FilePath $operaExe -ArgumentList @(
    '--remote-debugging-port=9224','--remote-debugging-address=127.0.0.1'
  ) -ErrorAction Stop | Out-Null
  $connected = $false
  for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    if (OperaAt9224) { $connected = $true; break }
  }
  if (!$connected) {
    Write-Host 'OPERA CDP NOT READY: dispatcher installed but safely stopped.'
    Write-Host 'No new profile and no Chrome fallback. Rerun installer -StartOnly.'
    return
  }
}
$proc = Start-Process -FilePath $python -ArgumentList ('"' + $localCore + '"') -PassThru
Write-Host ("DISPATCHER STARTED WITH OPERA PID=" + $proc.Id)
Start-Sleep -Seconds 6
if ($proc.HasExited) { StopSafe 'new dispatcher exited; inspect ai-dispatcher.log' }
Write-Host 'OPERA READY: existing authenticated Opera attached on localhost:9224.'
Write-Host 'QUEUE=87/NONE; original CONTROL pinned; no new signals.'
