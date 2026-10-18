# One-shot recovery for pending terminal CONTROL turn 89.
# No Chrome, no new GitHub signal, no personal Opera windows closed.
$ErrorActionPreference = 'Stop'
$root = Join-Path $HOME 'Documents\arena-archicad-project'
$localCore = Join-Path $root '.agent-handoff\dispatcher.py'
$homeCore = Join-Path $HOME 'dispatcher_core.py'
$homeRuntime = Join-Path $HOME 'dispatcher.py'
$statePath = Join-Path $HOME '.ai-dispatcher-state.json'
$controlPath = Join-Path $HOME '.ai-dispatcher-control.json'
$operaExe = Join-Path $env:LOCALAPPDATA 'Programs\Opera\opera.exe'
$profile = Join-Path $env:LOCALAPPDATA 'AI-Dispatcher\Opera-Agent-Profile'
$controlURL = 'https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a'
$signalBlob = 'ea2eb306a4159a8f4e9244cc630a403e495bf02c'
$oldBlob = 'c463861c2f40c99381fa9abdc58c27d8f9d773b0'
$newBlob = '45270c1a55c98fd70a88d0d8a66f8fb363a92e0a'
$commit = 'c306ca28d6a15ce6358a27e697f9a77acccaf667'
$sourceURL = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$commit/.agent-handoff/dispatcher.py"
function Fail([string]$reason) { throw ("RECOVERY_HOLD: " + $reason) }
function Blob([string]$file) {
  $result = & git.exe -C $root hash-object '--path=.agent-handoff/dispatcher.py' -- $file 2>$null
  if ($LASTEXITCODE -ne 0 -or !$result) { Fail 'git hash-object unavailable' }
  return ([string]$result).Trim()
}
function CheckQueue {
  $s = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
  $c = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$s.last_turn_id -ne 88 -or
      [int]$s.inflight.turn_id -ne 89 -or
      [string]$s.inflight.target -ne 'GPT' -or
      !$s.inflight.terminal_report) {
    Fail 'pending turn is not terminal GPT turn 89; no changes allowed'
  }
  if ([bool]$s.inflight.submitted -or
      [bool]$s.inflight.send_intent -or
      [int]$s.inflight.send_attempts -gt 0) {
    Fail 'CONTROL turn 89 may have been sent; no restart or replay'
  }
  if ([string]$c.chatgpt_control_url -ne $controlURL) {
    Fail 'pinned CONTROL identity changed'
  }
  return $s
}
function DispatcherProcesses {
  return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace('/','\').ToLowerInvariant()
    $_.Name -match '^python(?:w|[0-9.]*)?\.exe$' -and
    ($cmd.Contains($localCore.ToLowerInvariant()) -or
     $cmd.Contains($homeRuntime.ToLowerInvariant()))
  })
}
function BrowserPort {
  $listeners = @(Get-NetTCPConnection -LocalPort 9224 -State Listen -ErrorAction SilentlyContinue)
  if (!$listeners.Count) { return $false }
  $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($owners.Count -ne 1) { Fail 'debugger port owned by multiple processes' }
  foreach ($listener in $listeners) {
    if (@('127.0.0.1','::1') -notcontains [string]$listener.LocalAddress) {
      Fail 'debugger port exposed outside localhost'
    }
  }
  $owner = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $owners[0])
  if (!$owner -or $owner.Name -notmatch '^(opera|opera\w*|launcher)\.exe$' -or
      !([string]$owner.CommandLine).Contains('--remote-debugging-port=9224') -or
      !([string]$owner.CommandLine).Contains($profile)) {
    Fail 'debugger port is not owned by dedicated Opera'
  }
  try {
    $req = [System.Net.HttpWebRequest]::Create('http://127.0.0.1:9224/json/version')
    $req.Proxy = $null
    $req.Timeout = 2000
    $response = $req.GetResponse()
    try {
      $reader = New-Object IO.StreamReader($response.GetResponseStream())
      try { $json = $reader.ReadToEnd() | ConvertFrom-Json }
      finally { $reader.Dispose() }
    } finally { $response.Dispose() }
    return ([string]$json.webSocketDebuggerUrl -match '^ws://(127\.0\.0\.1|localhost):9224/devtools/browser/')
  } catch { return $false }
}
foreach ($file in @($localCore,$homeCore,$homeRuntime,$statePath,$controlPath,$operaExe)) {
  if (!(Test-Path -LiteralPath $file -PathType Leaf)) { Fail ("missing required file: " + $file) }
}
$state = CheckQueue
$api = 'https://api.github.com/repos/dvikt33-ux/arena-archicad-project/contents/.agent-handoff/signal.json?ref=agent-handoff'
$headers = @{ 'Accept'='application/vnd.github+json'; 'User-Agent'='AI-Dispatcher-89-Recovery' }
try {
  $doc = Invoke-RestMethod -UseBasicParsing -TimeoutSec 12 -Headers $headers -Uri $api
} catch { Fail 'GitHub read-only verification unavailable' }
if ([string]$doc.sha -ne $signalBlob) { Fail 'turn 89 GitHub blob changed; no update attempted' }
$pendingSignal = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(([string]$doc.content -replace '\s',''))) | ConvertFrom-Json
if ([int]$pendingSignal.turn_id -ne 89 -or
    [string]$pendingSignal.source -ne 'ARENA' -or
    [string]$pendingSignal.target -ne 'NONE' -or
    [string]$pendingSignal.status -ne 'done' -or
    !([string]$pendingSignal.message).StartsWith('OPERA_E2E_SMOKE_88_RECEIVED')) {
  Fail 'turn 89 GitHub message is unexpected'
}
foreach($file in @($localCore,$homeCore)) {
  if ((Blob $file) -notin @($oldBlob,$newBlob)) { Fail 'unexpected local dispatcher baseline' }
}
$processes = @(DispatcherProcesses)
if ($processes.Count -gt 1) { Fail 'multiple dispatcher processes' }
$stage = Join-Path $env:TEMP 'apa-recover-control-89-core.py'
Invoke-WebRequest -UseBasicParsing -Uri $sourceURL -TimeoutSec 30 -OutFile $stage
if ((Blob $stage) -ne $newBlob) { Fail 'downloaded core hash does not match reviewed fix' }
# This is the only process targeted for shutdown; never touch personal Opera.
if ($processes.Count -eq 1) {
  Stop-Process -Id $processes[0].ProcessId -ErrorAction Stop
  Start-Sleep -Seconds 3
}
if (@(DispatcherProcesses).Count -gt 0) { Fail 'dispatcher did not stop safely' }
$state = CheckQueue
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach($file in @($localCore,$homeCore)) {
  if ((Blob $file) -eq $newBlob) { continue }
  Copy-Item -LiteralPath $file -Destination ($file + ".pre-control89-$stamp.bak") -ErrorAction Stop
  Copy-Item -LiteralPath $stage -Destination $file -Force -ErrorAction Stop
}
if ((Blob $localCore) -ne $newBlob -or (Blob $homeCore) -ne $newBlob) {
  Fail 'core patch validation failed; backups retained'
}
if (!(BrowserPort)) {
  $owned = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(opera|opera\w*|launcher)\.exe$' -and
    ([string]$_.CommandLine).Contains($profile)
  })
  if ($owned.Count) {
    # Stop ONLY dedicated profile root/chromium subprocesses; personal Opera unaffected.
    foreach($proc in $owned) {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
  }
  if (@(Get-NetTCPConnection -LocalPort 9224 -State Listen -ErrorAction SilentlyContinue).Count) {
    if (!(BrowserPort)) { Fail 'unknown or not-ready owner on 9224' }
  } else {
    Write-Host 'Restoring dedicated Opera profile debug port 9224...'
    Start-Process -FilePath $operaExe -ArgumentList @(
      ('--user-data-dir="' + $profile + '"'),
      '--remote-debugging-port=9224',
      '--remote-debugging-address=127.0.0.1'
    )
    $ready = $false
    for($attempt=0;$attempt -lt 30;$attempt++) {
      Start-Sleep -Seconds 1
      if (BrowserPort) { $ready=$true; break }
    }
    if (!$ready) { Fail 'Opera debug port not ready after 30 seconds; state unchanged' }
  }
}
Write-Host 'OPERA_CDP_READY: 9224'
# Ensure queue did not change during repair; pending task remains a single delivery.
$state = CheckQueue
$python = & py -c 'import sys; print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or !$python) { Fail 'Python interpreter unavailable' }
if (@(DispatcherProcesses).Count -gt 0) { Fail 'dispatcher already active, do not duplicate' }
$proc = Start-Process -FilePath ([string]$python).Trim() -ArgumentList ('"' + $localCore + '"') -PassThru
Start-Sleep -Seconds 6
if ($proc.HasExited) { Fail 'dispatcher process exited; inspect ai-dispatcher.log' }
Write-Host ('DISPATCHER_RUNNING: pid=' + $proc.Id)
Write-Host 'CONTROL_89_RESUME: no GitHub signal written, no manual wake, no new chat.'
Get-Content (Join-Path $HOME 'ai-dispatcher.log') -Tail 6 -Encoding UTF8
