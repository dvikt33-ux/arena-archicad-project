# Launch persistent, isolated Opera profile for AI Dispatcher 2.2.19.
# No Chrome, no default Opera profile, no cookie copies, no process termination.
# Preserves pending turn 88; does not publish any GitHub signal.
$ErrorActionPreference = 'Stop'
$port = 9224
$profile = Join-Path $env:LOCALAPPDATA 'AI-Dispatcher\Opera-Agent-Profile'
$expectedControl = 'https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a'
$arenaURL = 'https://arena.ai/agent/01a09014-9139-71e7-b51b-5b3f8a49d904'
$signalBlob = 'c82202ac54bcd9675bd5786d5f12f784ac6a5c27'

function Fail([string]$why) { throw "STOP: $why" }
function FindOpera {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Opera\launcher.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Opera GX\launcher.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Opera Software\Opera Stable\launcher.exe'),
    (Join-Path $env:ProgramFiles 'Opera Software\Opera\launcher.exe')
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  if ($candidates.Count -gt 0) { return [string]$candidates[0] }
  $running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^opera.*\.exe$' -and $_.ExecutablePath -and
    (Test-Path -LiteralPath $_.ExecutablePath)
  })
  if ($running.Count -gt 0) { return [string]$running[0].ExecutablePath }
  return ''
}
function PortOwners {
  return @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}
function VerifiedOperaPort {
  $listeners = @(PortOwners)
  if ($listeners.Count -ne 1) { return $null }
  $listener = $listeners[0]
  if (@('127.0.0.1','::1') -notcontains [string]$listener.LocalAddress) {
    Fail 'debug port is exposed beyond loopback'
  }
  $ownerProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener.OwningProcess)
  if (!$ownerProcess -or $ownerProcess.Name -notmatch '^(opera|opera\w*|launcher)\.exe$') {
    Fail 'debug port owned by an unknown executable'
  }
  $cmd = [string]$ownerProcess.CommandLine
  if (!$cmd.Contains('--remote-debugging-port=9224') -or
      !$cmd.Contains($profile)) {
    Fail 'debug port owner is not the dedicated Opera agent profile'
  }
  try {
    $version = Invoke-RestMethod -UseBasicParsing -TimeoutSec 3 -Uri 'http://127.0.0.1:9224/json/version'
  } catch { Fail 'Opera opened port but JSON debugger endpoint is unreachable' }
  if ([string]$version.webSocketDebuggerUrl -notmatch '^ws://(127\.0\.0\.1|localhost):9224/devtools/browser/') {
    Fail 'Opera debugger endpoint identity is not valid'
  }
  return $ownerProcess
}
$statePath = Join-Path $HOME '.ai-dispatcher-state.json'
$controlPath = Join-Path $HOME '.ai-dispatcher-control.json'
if (!(Test-Path -LiteralPath $statePath) -or !(Test-Path -LiteralPath $controlPath)) {
  Fail 'local dispatcher state or CONTROL missing'
}
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$control = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$state.last_turn_id -ne 87 -or
    [int]$state.inflight.turn_id -ne 88 -or
    [string]$state.inflight.target -ne 'ARENA') {
  Fail 'pending queue differs from approved 87 -> 88 transport test'
}
if ([bool]$state.inflight.submitted -or [bool]$state.inflight.send_intent -or
    [int]$state.inflight.send_attempts -gt 0) {
  Fail 'turn 88 may have been submitted; do not start another browser transport'
}
if ([string]$control.chatgpt_control_url -ne $expectedControl) {
  Fail 'pinned CONTROL identity changed'
}
$api = 'https://api.github.com/repos/dvikt33-ux/arena-archicad-project/contents/.agent-handoff/signal.json?ref=agent-handoff'
$headers = @{ 'User-Agent'='AI-Dispatcher-Opera-Profile'; 'Accept'='application/vnd.github+json' }
try { $doc = Invoke-RestMethod -UseBasicParsing -TimeoutSec 12 -Headers $headers -Uri $api }
catch { Fail 'GitHub signal read-only preflight unavailable; do not relaunch blindly' }
if ([string]$doc.sha -ne $signalBlob) { Fail 'turn 88 signal changed since last observation' }

$owners = @(PortOwners)
if ($owners.Count -gt 0) {
  $verified = VerifiedOperaPort
  if (!$verified) { Fail 'port in use but no verified Opera listener' }
  Write-Host ('OPERA_CDP_READY: port=9224 pid=' + $verified.ProcessId)
  Write-Host 'Existing dedicated Opera browser retained.'
  Write-Host 'QUEUE=87/PENDING_88: dispatcher will resume without any new signal.'
  return
}
$opera = FindOpera
if (!$opera) { Fail 'Opera executable not found, browser not launched' }
$null = New-Item -Path $profile -ItemType Directory -Force
$arguments = @(
  ('--user-data-dir="' + $profile + '"'),
  '--remote-debugging-port=9224',
  '--remote-debugging-address=127.0.0.1',
  $expectedControl,
  $arenaURL
)
Write-Host 'Starting a persistent Opera agent profile; personal Opera remains open.'
Start-Process -FilePath $opera -ArgumentList $arguments -ErrorAction Stop | Out-Null
$verified = $null
for($attempt=0;$attempt -lt 24;$attempt++) {
  Start-Sleep -Seconds 1
  if (@(PortOwners).Count -gt 0) {
    $verified = VerifiedOperaPort
    break
  }
}
if (!$verified) {
  Write-Host 'OPERA_CDP_CLOSED: dedicated browser did not expose debugger port.'
  Write-Host ('EXECUTABLE: ' + $opera)
  Write-Host ('PROFILE: ' + $profile)
  Fail 'no remote debugger; do not restart personal Opera or resubmit turn 88'
}
Write-Host ('OPERA_CDP_READY: port=9224 pid=' + $verified.ProcessId)
Write-Host ('PROFILE: ' + $profile)
Write-Host 'Sign in to ChatGPT and Arena in the new Opera window if asked.'
Write-Host 'The running dispatcher will reconnect automatically. No new GitHub signal.'
Write-Host 'QUEUE=87/PENDING_88 until the existing test finishes.'
