# One-shot safe installer for the CONTROL reply handoff fix.
# Run from the existing repository checkout; never edits signal.json or queue state.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$handoff = Join-Path $repo ".agent-handoff"
$dispatcher = Join-Path $handoff "dispatcher.py"
$module = Join-Path $handoff "control_reply_handoff.py"
$statePath = Join-Path $HOME ".ai-dispatcher-state.json"
$controlPath = Join-Path $HOME ".ai-dispatcher-control.json"
$credentialPath = Join-Path $env:LOCALAPPDATA "AI-Dispatcher\github-token.dpapi"
$codeCommit = "e5694880877662a09d76ca5c0f9365a119120978"
$dispatcherBlob = "ec23434a0864c81c0d0ea69ecbde771b7445b70f"
$moduleBlob = "f1aba7a9b3c1bd5c608dcabc5fa4a079004ffcec"
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$codeCommit/.agent-handoff"
$stage = Join-Path $env:TEMP ("AI_Dispatcher_ControlReply_" + [guid]::NewGuid().ToString("N"))
$stageHandoff = Join-Path $stage ".agent-handoff"
$testPath = Join-Path $stageHandoff "tests"
$null = New-Item -ItemType Directory -Force -Path $testPath

function Stop-Install([string]$message) { throw "STOP: $message" }
function GitBlob([string]$path) {
    $full = [IO.Path]::GetFullPath($path)
    $root = [IO.Path]::GetFullPath($repo).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        $relative = $full.Substring($root.Length).Replace('\','/')
        $hash = & git.exe -C $repo hash-object ("--path=" + $relative) -- $full 2>$null
    } else {
        $hash = & git.exe -C $repo hash-object -- $full 2>$null
    }
    if ($LASTEXITCODE -ne 0 -or !$hash) { Stop-Install "cannot verify file hash" }
    return ([string]$hash).Trim()
}
function Read-DpapiToken([string]$path) {
    if (!(Test-Path -LiteralPath $path)) { return $null }
    $secureText = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $secure = ConvertTo-SecureString $secureText
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
function Test-GitHubSignal([string]$token) {
    try {
        $headers = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json"; "X-GitHub-Api-Version" = "2022-11-28"; "User-Agent" = "AI-Dispatcher-2.2.19" }
        $uri = "https://api.github.com/repos/dvikt33-ux/arena-archicad-project/contents/.agent-handoff/signal.json?ref=agent-handoff"
        $response = Invoke-RestMethod -Method Get -Headers $headers -Uri $uri -TimeoutSec 8
        $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($response.content -replace '\s','')))
        $signal = $json | ConvertFrom-Json
        if ([int]$signal.turn_id -ne 76 -or [string]$signal.target -ne "GPT" -or [string]$signal.source -ne "ARENA" -or [string]$signal.status -ne "ready") { return $false }
        if ($signal.PSObject.Properties.Name -contains "requires_codex" -and ($signal.requires_codex -isnot [bool] -or $signal.requires_codex)) { return $false }
        return $true
    } catch { return $false }
}
function Test-DispatcherMutex {
    $opened = $null
    try { return [bool][System.Threading.Mutex]::TryOpenExisting("Local\AI_Dispatcher_22", [ref]$opened) }
    finally { if ($null -ne $opened) { $opened.Dispose() } }
}

if (!(Test-Path -LiteralPath $dispatcher) -or !(Test-Path -LiteralPath $statePath) -or !(Test-Path -LiteralPath $controlPath)) { Stop-Install "existing dispatcher, state, and CONTROL records must all be present" }
$branch = (& git.exe -C $repo branch --show-current 2>$null).Trim()
if ($branch -ne "fix/arena-control-stale-rescue-20261016") { Stop-Install "run from branch fix/arena-control-stale-rescue-20261016" }
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$state.last_turn_id -ne 75 -or [int]$state.inflight.turn_id -ne 76 -or [string]$state.inflight.target -ne "GPT") { Stop-Install "pending dispatcher state is not exactly turn 76 to GPT" }
$control = Get-Content -LiteralPath $controlPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$control.chatgpt_control_url -notmatch '^https://chatgpt\.com/c/[^/?#]+') { Stop-Install "saved CONTROL URL is not a durable existing conversation" }

$currentDispatcherBlob = GitBlob $dispatcher
if ($currentDispatcherBlob -notin @("a1160915fb6f3681bf92b181cd48dd3e5bce7814", $dispatcherBlob)) { Stop-Install "installed dispatcher differs from the reviewed source" }
if (Test-Path -LiteralPath $module) {
    if ((GitBlob $module) -ne $moduleBlob) { Stop-Install "existing helper module differs from the reviewed source" }
}

# Obtain a token only if this Windows user has no DPAPI-protected token.
$token = $env:GITHUB_TOKEN
$newCredential = $false
if (!$token) { $token = Read-DpapiToken $credentialPath }
if (!$token) {
    $secureToken = Read-Host "GitHub token with Contents write access for this repository" -AsSecureString
    if (!$secureToken -or $secureToken.Length -lt 20) { Stop-Install "GitHub token was not supplied" }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    $newCredential = $true
}
if (!(Test-GitHubSignal $token)) { Stop-Install "GitHub token invalid or signal is not the expected turn 76" }

Write-Host "Downloading pinned dispatcher, helper, and regression tests..."
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile (Join-Path $stageHandoff "dispatcher.py")
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/control_reply_handoff.py" -OutFile (Join-Path $stageHandoff "control_reply_handoff.py")
foreach ($name in @("test_control_reply_handoff.py","test_control_marker_fallback.py","test_stale_control_rescue.py","test_arena_feedback_dismiss.py")) {
    Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/$name" -OutFile (Join-Path $testPath $name)
}
if ((GitBlob (Join-Path $stageHandoff "dispatcher.py")) -ne $dispatcherBlob -or (GitBlob (Join-Path $stageHandoff "control_reply_handoff.py")) -ne $moduleBlob) { Stop-Install "pinned download hash mismatch" }

# Select an existing Python that has Playwright. Install no dependencies.
$candidates = @(
    [pscustomobject]@{ Exe = (Join-Path $repo ".venv\Scripts\python.exe"); Args = @() },
    [pscustomobject]@{ Exe = (Join-Path $HOME "AppData\Roaming\uv\tools\archicad-mcp-server\Scripts\python.exe"); Args = @() },
    [pscustomobject]@{ Exe = "py.exe"; Args = @("-3") },
    [pscustomobject]@{ Exe = "python.exe"; Args = @() }
)
$runner = $null
foreach ($candidate in $candidates) {
    $found = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
    if (!$found) { continue }
    try {
        $probeArgs = @($candidate.Args) + @("-c", "from playwright.sync_api import sync_playwright")
        & $found.Source @probeArgs 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $runner = [pscustomobject]@{ Exe = $found.Source; Args = @($candidate.Args) }; break }
    } catch { continue }
}
if ($null -eq $runner) { Stop-Install "no existing Python with Playwright was found" }
$runnerArgs = @($runner.Args)
& $runner.Exe @runnerArgs -m py_compile (Join-Path $stageHandoff "dispatcher.py") (Join-Path $stageHandoff "control_reply_handoff.py")
if ($LASTEXITCODE -ne 0) { Stop-Install "Python syntax check failed" }
& $runner.Exe @runnerArgs -m unittest discover -s $testPath -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { Stop-Install "regression tests failed; installed files unchanged" }

# Identify only the exact current Python dispatcher; never stop an ambiguous process.
$targetNorm = $dispatcher.Replace("/","\").ToLowerInvariant()
$matches = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace("/","\").ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and $cmd.Contains($targetNorm)
})
$mutexActive = Test-DispatcherMutex
if ($matches.Count -gt 1 -or ($matches.Count -eq 0 -and $mutexActive) -or ($matches.Count -eq 1 -and !$mutexActive)) { Stop-Install "dispatcher process ownership is ambiguous" }
if ($matches.Count -ne 1) { Stop-Install "the expected existing dispatcher process is not running" }

# Save a new credential encrypted for this Windows user after all read-only preflight succeeds.
if ($newCredential) {
    $credentialDir = Split-Path -Parent $credentialPath
    $null = New-Item -ItemType Directory -Force -Path $credentialDir
    $cipher = ConvertFrom-SecureString $secureToken
    [IO.File]::WriteAllText($credentialPath, $cipher, [Text.UTF8Encoding]::new($false))
}
$backupDispatcher = "$dispatcher.before-control-reply-$($currentDispatcherBlob.Substring(0,12)).bak"
if (!(Test-Path -LiteralPath $backupDispatcher)) { Copy-Item -LiteralPath $dispatcher -Destination $backupDispatcher }
if (Test-Path -LiteralPath $module) {
    $currentModuleBlob = GitBlob $module
    $backupModule = "$module.before-control-reply-$($currentModuleBlob.Substring(0,12)).bak"
    if (!(Test-Path -LiteralPath $backupModule)) { Copy-Item -LiteralPath $module -Destination $backupModule }
} else { $backupModule = $null }

$stoppedId = [int]$matches[0].ProcessId
$stopped = $false
$started = $null
try {
    Stop-Process -Id $stoppedId -ErrorAction Stop
    $stopped = $true
    for ($i=0; $i -lt 40; $i++) {
        if (!(Get-Process -Id $stoppedId -ErrorAction SilentlyContinue) -and !(Test-DispatcherMutex)) { break }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-Process -Id $stoppedId -ErrorAction SilentlyContinue) -or (Test-DispatcherMutex)) {
        throw "dispatcher did not stop cleanly; source files remain unchanged"
    }
    try {
        $newDispatcher = "$dispatcher.installing"
        $newModule = "$module.installing"
        Copy-Item -LiteralPath (Join-Path $stageHandoff "dispatcher.py") -Destination $newDispatcher -Force
        Copy-Item -LiteralPath (Join-Path $stageHandoff "control_reply_handoff.py") -Destination $newModule -Force
        if (Test-Path -LiteralPath $module) { [IO.File]::Replace($newModule, $module, $null) }
        else { Move-Item -LiteralPath $newModule -Destination $module }
        [IO.File]::Replace($newDispatcher, $dispatcher, $null)
        if ((GitBlob $dispatcher) -ne $dispatcherBlob -or (GitBlob $module) -ne $moduleBlob) {
            throw "installed hashes do not match"
        }
    } catch {
        Copy-Item -LiteralPath $backupDispatcher -Destination $dispatcher -Force
        if ($backupModule) { Copy-Item -LiteralPath $backupModule -Destination $module -Force }
        elseif (Test-Path -LiteralPath $module) { Remove-Item -LiteralPath $module -Force }
        throw "install failed; verified backups restored: $($_.Exception.Message)"
    }
} finally {
    if ($stopped -and !(Get-Process -Id $stoppedId -ErrorAction SilentlyContinue) -and !(Test-DispatcherMutex)) {
        $startArgs = $runnerArgs + @("-u", ('"' + $dispatcher + '"'))
        $started = Start-Process -FilePath $runner.Exe -ArgumentList $startArgs -WorkingDirectory $handoff -PassThru
        Start-Sleep -Seconds 8
    }
}
if ($started -and $started.HasExited -and $started.ExitCode -ne 0) { Stop-Install "patched dispatcher exited during startup" }
if (!(Test-DispatcherMutex)) { Stop-Install "patched dispatcher mutex did not appear" }
Write-Host "INSTALL PASS: dispatcher and helper hashes verified; existing state and CONTROL URL preserved."
Write-Host "No GitHub signal write was attempted by the installer; live turn 76 completion remains unverified."
Write-Host "Installer backup: $backupDispatcher"
