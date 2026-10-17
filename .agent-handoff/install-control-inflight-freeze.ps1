# Pinned installation of submitted-CONTROL read-only hold. Windows PowerShell 5.1.
# Refuses a running dispatcher and never changes queue, CONTROL, mailbox or PLN.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo '.agent-handoff'
$src = Join-Path $handoff 'dispatcher.py'
$helper = Join-Path $handoff 'control_reply_handoff.py'
$statePath = Join-Path $HOME '.ai-dispatcher-state.json'
$controlPath = Join-Path $HOME '.ai-dispatcher-control.json'
$sourceCommit = '62728e3a2d1cb659bd5a386d98f98ac51c836935'
$expectedOld = '86f60e2bf9c64589962851474ca5cc5975786a3e'
$expectedNew = '75412cf5f2d410b2f855efd45a5899a37e933677'
$helperBlob = 'b79a002bcdd1bb517421c9b2f6792f00cd5e1d75'
$url = 'https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a'
$reboundURL = 'https://chatgpt.com/c/6ad3e97f-5980-83eb-babf-d34379e0df0c'
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$sourceCommit/.agent-handoff"
function Refuse([string]$reason) { throw "STOP: $reason" }
function Blob([string]$file,[string]$gitPath) {
  $value = & git.exe -C $repo hash-object ('--path=' + $gitPath) -- $file 2>$null
  if ($LASTEXITCODE -ne 0 -or !$value) { Refuse 'git blob check failed' }
  return ([string]$value).Trim()
}
function DispatcherProcesses {
  return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
    $cmd.Contains($src.Replace('/','\').ToLowerInvariant())
  })
}
function MutexPresent {
  $handle = $null
  try { return [bool][Threading.Mutex]::TryOpenExisting('Local\AI_Dispatcher_22',[ref]$handle) }
  finally { if ($handle) { $handle.Dispose() } }
}
function QueueHash { return (Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash }
function CheckQueue {
  $control = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$control.chatgpt_control_url -ne $reboundURL -or
      [string]$control.rebind_for_url -ne $reboundURL -or
      [string]$control.rebind_status -ne 'pending' -or
      [int]$control.rebind_count -ne 1) {
    Refuse 'CONTROL rebind state differs from observed 87 failure'
  }
  $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
  $pending = $state.inflight
  if ([int]$state.last_turn_id -ne 86 -or $null -eq $pending -or
      [int]$pending.turn_id -ne 87 -or [string]$pending.target -ne 'GPT' -or
      $pending.terminal_report -ne $true -or $pending.submitted -ne $true -or
      [int]$pending.send_attempts -ne 1 -or $pending.wake_seen -ne $true -or
      $pending.terminal_resume_intent -ne $true -or
      [string]$pending.wake_seen_control_url -ne $url -or
      [string]$pending.wake -notmatch 'turn_id=87$' -or
      [string]$pending.wake_seen_control_identity -ne '6ad27341-1ea4-83eb-8238-5ce1cada094a') {
    Refuse 'saved queue differs from approved pending 87'
  }
}
foreach($file in @($src,$helper,$statePath,$controlPath)) {
  if (!(Test-Path -LiteralPath $file)) { Refuse 'required local file missing' }
}
if ((DispatcherProcesses).Count -ne 0 -or (MutexPresent)) { Refuse 'dispatcher still running' }
if ((Blob $src '.agent-handoff/dispatcher.py') -ne $expectedOld) { Refuse 'unexpected installed dispatcher blob' }
if ((Blob $helper '.agent-handoff/control_reply_handoff.py') -ne $helperBlob) { Refuse 'unexpected CONTROL parser helper' }
CheckQueue
$initialQueue = QueueHash
$initialControl = (Get-FileHash -LiteralPath $controlPath -Algorithm SHA256).Hash
$stage = Join-Path $env:TEMP ('control-freeze-' + [guid]::NewGuid().ToString('N'))
$stagedRoot = Join-Path $stage '.agent-handoff'
$tests = Join-Path $stagedRoot 'tests'
$null = New-Item -ItemType Directory -Path $tests -Force
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile (Join-Path $stagedRoot 'dispatcher.py')
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/control_reply_handoff.py" -OutFile (Join-Path $stagedRoot 'control_reply_handoff.py')
$names = @(
  'test_control_reply_handoff.py','test_control_marker_fallback.py',
  'test_stale_control_rescue.py','test_arena_feedback_dismiss.py',
  'test_control_multi_ack.py','test_dispatcher_state_loop.py',
  'test_arena_feedback_inline.py','test_dispatcher_atmost_once.py',
  'test_dispatcher_recovery_contract.py','test_arena_terminal_receipt.py',
  'test_control_terminal_resume.py','test_submitted_control_readonly_hold.py'
)
foreach($name in $names) {
  Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/$name" -OutFile (Join-Path $tests $name)
}
if ((Blob (Join-Path $stagedRoot 'dispatcher.py') '.agent-handoff/dispatcher.py') -ne $expectedNew -or
    (Blob (Join-Path $stagedRoot 'control_reply_handoff.py') '.agent-handoff/control_reply_handoff.py') -ne $helperBlob) {
  Refuse 'downloaded code hash mismatch'
}
$python = (& py -c 'import sys; print(sys.executable)')
if ($LASTEXITCODE -ne 0 -or !$python -or !(Test-Path -LiteralPath $python)) { Refuse 'Python interpreter unavailable' }
& $python -c 'from playwright.sync_api import sync_playwright' 
if ($LASTEXITCODE -ne 0) { Refuse 'Python missing Playwright; no source change' }
& $python -m py_compile (Join-Path $stagedRoot 'dispatcher.py') (Join-Path $stagedRoot 'control_reply_handoff.py')
if ($LASTEXITCODE -ne 0) { Refuse 'candidate syntax error' }
& $python -m unittest discover -s $tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { Refuse 'candidate tests failed' }
if ((DispatcherProcesses).Count -ne 0 -or (MutexPresent) -or
    (QueueHash) -ne $initialQueue -or
    (Get-FileHash -LiteralPath $controlPath -Algorithm SHA256).Hash -ne $initialControl -or
    (Blob $src '.agent-handoff/dispatcher.py') -ne $expectedOld) {
  Refuse 'dispatcher, queue or installed code changed during staging'
}
CheckQueue
$backup = "$src.before-control-freeze-$($expectedOld.Substring(0,12)).bak"
Copy-Item -LiteralPath $src -Destination $backup -ErrorAction Stop
$tmp = "$src.installing"
Copy-Item -LiteralPath (Join-Path $stagedRoot 'dispatcher.py') -Destination $tmp -Force
[IO.File]::Replace($tmp,$src,("$src.pre-control-freeze-"+[guid]::NewGuid().ToString('N')+'.bak'))
if ((Blob $src '.agent-handoff/dispatcher.py') -ne $expectedNew) {
  Copy-Item -LiteralPath $backup -Destination $src -Force
  Refuse 'post-install hash mismatch; prior source restored'
}
Write-Host 'INSTALL PASS: pending CONTROL 87 pinned-history readback installed.'
Write-Host 'Dispatcher remains stopped. CONTROL rebind record and pending 87 preserved unchanged.'
Write-Host "BACKUP: $backup"
Write-Host "PYTHON: $python"
