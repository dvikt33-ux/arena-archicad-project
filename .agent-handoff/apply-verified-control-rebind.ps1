# One-time CONTROL URL repair; never changes source, GitHub, PLN or inflight.
# Requires existing initialized ChatGPT conversation already OPEN in CDP Chrome.
$ErrorActionPreference = "Stop"
$repo = Join-Path $HOME "Documents\arena-archicad-project"
$dispatcher = Join-Path $repo ".agent-handoff\dispatcher.py"
$expectedDispatcherBlob = "a1160915fb6f3681bf92b181cd48dd3e5bce7814"
$sourceCommit = "40e0faa8f3e039d6fa724beaf63d24da973e3b07"
$helperBlob = "4f4af2d70fa09bd551487c2002f719031f82ef5e"
$helper = Join-Path $env:TEMP "APA_Control_Rebind_Verified_Turn76.py"
$helperUrl = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$sourceCommit/.agent-handoff/verified-control-rebind.py"
$oldUrl = "https://chatgpt.com/c/6ab69cd1-9334-83eb-b03a-9e1b4b23c91a"
$newUrl = "https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
$control = Join-Path $HOME ".ai-dispatcher-control.json"
$state = Join-Path $HOME ".ai-dispatcher-state.json"

function Blob([string]$file) {
    $h = & git.exe hash-object -- $file 2>$null
    if ($LASTEXITCODE -ne 0 -or !$h) { throw "STOP: cannot verify git blob: $file" }
    return ([string]$h).Trim()
}
function MutexActive {
    $m = $null
    try {
        return [bool][System.Threading.Mutex]::TryOpenExisting("Local\AI_Dispatcher_22", [ref]$m)
    } finally {
        if ($null -ne $m) { $m.Dispose() }
    }
}
if (!(Test-Path -LiteralPath $dispatcher)) { throw "STOP: dispatcher source missing" }
if ((Blob $dispatcher) -ne $expectedDispatcherBlob) {
    throw "STOP: installed dispatcher is not the verified v5 version; no changes."
}
if (!(Test-Path -LiteralPath $control) -or !(Test-Path -LiteralPath $state)) {
    throw "STOP: dispatcher state/control not found"
}
$r = Get-Content -LiteralPath $control -Raw -Encoding UTF8 | ConvertFrom-Json
if ($r.chatgpt_control_url -eq $newUrl) {
    Write-Host "ALREADY_REBOUND: CONTROL points to the working chat. No writes."
    exit 0
}
if ($r.chatgpt_control_url -ne $oldUrl) {
    throw "STOP: CONTROL URL is different from inspected source. No changes."
}

Write-Host "Verifying pinned read-only CDP helper..."
Invoke-WebRequest -UseBasicParsing -Uri $helperUrl -OutFile $helper
if ((Blob $helper) -ne $helperBlob) {
    throw "STOP: helper SHA mismatch; no changes."
}
$py = (Get-Command py.exe -ErrorAction Stop).Source
& $py -3 -m py_compile $helper
if ($LASTEXITCODE -ne 0) { throw "STOP: helper syntax error; no changes." }

Write-Host "Probing the already-open ChatGPT CONTROL tab (no clicks/messages)..."
& $py -3 $helper --probe
if ($LASTEXITCODE -ne 0) {
    throw "STOP: target chat identity not verified. Dispatcher untouched."
}

# The script restarts only the exact Python process executing the known
# dispatcher.py, never arbitrary Python or Chrome processes.
$target = $dispatcher.Replace("/", "\").ToLowerInvariant()
$procs = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace("/", "\").ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
    $cmd.Contains($target)
})
$mutex = MutexActive
Write-Host "DISPATCHER: matching_python=$($procs.Count) mutex=$mutex"
if ($procs.Count -ne 1 -or !$mutex) {
    throw "STOP: dispatcher ownership ambiguous. Nothing changed."
}
$pidToStop = [int]$procs[0].ProcessId
$stopped = $false
$restarted = $false
try {
    Stop-Process -Id $pidToStop -ErrorAction Stop
    $stopped = $true
    for ($i=0; $i -lt 40; $i++) {
        if (!(Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) -and !(MutexActive)) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-Process -Id $pidToStop -ErrorAction SilentlyContinue) {
        throw "STOP: old process still exists; no control file edited."
    }
    if (MutexActive) {
        throw "STOP: dispatcher mutex still held; no control file edited."
    }
    & $py -3 $helper --apply
    if ($LASTEXITCODE -ne 0) { throw "STOP: safe rebind failed; CONTROL preserved or backed up." }
} finally {
    if ($stopped) {
        if (!(MutexActive)) {
            $args = @("-3", "-u", ('"' + $dispatcher + '"'))
            $started = Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory (Split-Path $dispatcher) -PassThru
            $restarted = $true
            Write-Host "DISPATCHER_RESTART_REQUESTED: pid=$($started.Id)"
            Start-Sleep -Seconds 8
        } else {
            Write-Host "DISPATCHER_ALREADY_ACTIVE: refusing duplicate restart."
        }
    }
}
if (!(MutexActive)) { throw "STOP: new dispatcher not running. Check ai-dispatcher.log." }
$after = Get-Content -LiteralPath $control -Raw -Encoding UTF8 | ConvertFrom-Json
if ($after.chatgpt_control_url -ne $newUrl) {
    throw "STOP: rebind was not persisted; examine log and backup."
}
Write-Host "CONTROL_REBIND_VERIFIED: existing initialized conversation selected; no new chat created."
Write-Host "INFLIGHT: not changed by this script. Check wake turn 76 live in log."
Get-Content (Join-Path $HOME "ai-dispatcher.log") -Tail 12 -Encoding UTF8 |
    ForEach-Object { $_ -replace 'https://chatgpt\.com/c/[^\s]+', '[CONTROL_URL]' }
