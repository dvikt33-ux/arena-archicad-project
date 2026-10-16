# Safe local upgrade for Arena -> ChatGPT CONTROL recovery.
# Only modifies the dispatcher.py file after exact source verification and tests.
# Never changes Git branches, ChatGPT state, model/PLN/APX, or signal.json.
param()
$ErrorActionPreference = "Stop"

$repo = Join-Path $HOME "Documents\arena-archicad-project"
$dispatcher = Join-Path $repo ".agent-handoff\dispatcher.py"
$sourceBlob = "f690895dc2ebb36dae76b3442e1943dc225cfe42"
$previousPatchedBlob = "e8b570511d55e9cda47a4e5a65d63f86c34d5fb9"
$secondPatchedBlob = "8d4a4f2187c9ab009e7b1883c5e87b832ba5668e"
$thirdPatchedBlob = "e69e7cc50c1488c2fac9341ef681100521e65bc2"
$fourthPatchedBlob = "48fb5c32f6d2c3d3a3ce0bf7be0d4fd4152d57cc"
$patchedBlob = "a1160915fb6f3681bf92b181cd48dd3e5bce7814"
$commit = "518c33fbc02ed0f5c522913589efdc16a7f8e179"
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$commit/.agent-handoff"
$stage = Join-Path $env:TEMP ("APA_Control_Rescue_" + [DateTime]::UtcNow.ToString("yyyyMMdd_HHmmss"))
$testPath = Join-Path $stage "tests"
$null = New-Item -ItemType Directory -Force -Path $testPath
$downloaded = Join-Path $stage "dispatcher.py"
$testFile = Join-Path $testPath "test_stale_control_rescue.py"
$feedbackTestFile = Join-Path $testPath "test_arena_feedback_dismiss.py"
$controlFallbackTestFile = Join-Path $testPath "test_control_marker_fallback.py"

function GitBlob([string]$file) {
    $hash = & git.exe hash-object -- $file 2>$null
    if ($LASTEXITCODE -ne 0 -or !$hash) { throw "git hash-object failed: $file" }
    return ([string]$hash).Trim()
}
if (!(Test-Path -LiteralPath $dispatcher)) { throw "Dispatcher not found: $dispatcher" }
$current = GitBlob $dispatcher
if ($current -notin @($sourceBlob, $previousPatchedBlob, $secondPatchedBlob, $thirdPatchedBlob, $fourthPatchedBlob, $patchedBlob)) {
    throw "STOP: installed dispatcher differs from reviewed source (blob=$current). Nothing changed."
}

Write-Host "Downloading pinned dispatcher and regression tests from commit $commit"
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile $downloaded
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/test_stale_control_rescue.py" -OutFile $testFile
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/test_arena_feedback_dismiss.py" -OutFile $feedbackTestFile
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/test_control_marker_fallback.py" -OutFile $controlFallbackTestFile
if ((GitBlob $downloaded) -ne $patchedBlob) {
    throw "STOP: downloaded code SHA mismatch. Nothing changed."
}

# Pick an existing Python interpreter with Playwright. No dependencies installed.
$candidates = @(
    [pscustomobject]@{ Exe = (Join-Path $repo ".venv\\Scripts\\python.exe"); Args = @() },
    [pscustomobject]@{ Exe = (Join-Path $HOME "AppData\\Roaming\\uv\\tools\\archicad-mcp-server\\Scripts\\python.exe"); Args = @() },
    [pscustomobject]@{ Exe = "py.exe"; Args = @("-3") },
    [pscustomobject]@{ Exe = "python.exe"; Args = @() }
)
$runner = $null
foreach ($candidate in $candidates) {
    $found = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
    if (!$found) { continue }
    $bin = [string]$found.Source
    $flags = @($candidate.Args)
    try {
        & $bin @flags -c "from playwright.sync_api import sync_playwright" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $runner = [pscustomobject]@{ Exe = $bin; Args = $flags }
            break
        }
    } catch { continue }
}
if ($null -eq $runner) {
    throw "STOP: no existing Python interpreter with Playwright found. Nothing changed."
}
Write-Host "PYTHON SELECTED: $($runner.Exe)"
$runnerArgs = @($runner.Args)
& ($runner.Exe) @runnerArgs -m py_compile $downloaded
if ($LASTEXITCODE -ne 0) { throw "STOP: Python syntax error; no changes." }
& ($runner.Exe) @runnerArgs -m unittest discover -s $testPath -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "STOP: regression tests failed; no changes." }
Write-Host "PREFLIGHT PASS"

# Identify only the exact dispatcher script. A running launcher (py.exe) may
# have a separate python.exe child; never kill arbitrary Python processes.
$targetNorm = $dispatcher.Replace("/","\").ToLowerInvariant()
$allProcs = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$matches = @($allProcs | Where-Object {
    $cmd = ([string]$_.CommandLine).Replace("/","\").ToLowerInvariant()
    $_.Name -match '^(python|pythonw|python[0-9.]+|pythonw[0-9.]+)\.exe$' -and
    ($cmd.Contains($targetNorm) -or $cmd -match '(?:^|[\s\\\"])dispatcher\.py(?:$|[\s\"])')
})

# The original dispatcher uses Local\\AI_Dispatcher_22: it is a stronger
# runtime-presence check than a guessed executable or command-line path.
function Test-DispatcherMutex {
    $opened = $null
    try {
        $present = [System.Threading.Mutex]::TryOpenExisting(
            "Local\AI_Dispatcher_22", [ref]$opened
        )
        return [bool]$present
    } finally {
        if ($null -ne $opened) { $opened.Dispose() }
    }
}
$mutexActive = Test-DispatcherMutex
Write-Host "PROCESS CHECK: python-dispatchers=$($matches.Count), mutex-active=$mutexActive"
if ($matches.Count -gt 1) {
    throw "STOP: multiple candidate Python dispatchers. Nothing changed."
}
if ($matches.Count -eq 0 -and $mutexActive) {
    throw "STOP: dispatcher mutex held by unidentified process; will not risk duplicate. Nothing changed."
}
if ($matches.Count -eq 1 -and !$mutexActive) {
    throw "STOP: dispatcher process found without its expected mutex; refusing to stop unknown process."
}
if ($current -eq $patchedBlob -and $mutexActive) {
    Write-Host "ALREADY_PATCHED_AND_RUNNING: true; no action required."
    exit 0
}

if ($current -ne $patchedBlob) {
    $backup = "$dispatcher.before-control-rescue-$($current.Substring(0,12)).bak"
    if (Test-Path -LiteralPath $backup) {
        if ((GitBlob $backup) -ne $current) {
            throw "STOP: an existing backup has unexpected SHA; nothing changed."
        }
        Write-Host "VERIFIED EXISTING BACKUP: $backup"
    } else {
        Copy-Item -LiteralPath $dispatcher -Destination $backup -ErrorAction Stop
        if ((GitBlob $backup) -ne $current) {
            throw "STOP: backup verification failed; source unchanged."
        }
        Write-Host "VERIFIED BACKUP: $backup"
    }

    if ($matches.Count -eq 1) {
        $id = [int]$matches[0].ProcessId
        Stop-Process -Id $id -ErrorAction Stop
        for ($i=0; $i -lt 30; $i++) {
            if (!(Get-Process -Id $id -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
            throw "STOP: dispatcher did not exit; source untouched."
        }
        if (Test-DispatcherMutex) {
            throw "STOP: mutex still held; original source untouched."
        }
    } else {
        Write-Host "NO RUNNING DISPATCHER: install without stopping any process."
    }

    try {
        Copy-Item -LiteralPath $downloaded -Destination $dispatcher -Force
        if ((GitBlob $dispatcher) -ne $patchedBlob) {
            throw "Installed hash check failed"
        }
    } catch {
        Copy-Item -LiteralPath $backup -Destination $dispatcher -Force
        throw "Restored backup after install failure: $($_.Exception.Message)"
    }
    Write-Host "PATCH INSTALLED: blob=$patchedBlob"
} else {
    Write-Host "ALREADY_PATCHED_NOT_RUNNING: starting existing patch."
}

# Preserve %USERPROFILE% state files intact; the new code reads pending turn 72.
$startArgs = @($runner.Args) + @("-u", ('"' + $dispatcher + '"'))
$started = Start-Process -FilePath $runner.Exe -ArgumentList $startArgs -WorkingDirectory (Split-Path $dispatcher) -PassThru
Write-Host "DISPATCHER LAUNCH REQUESTED: pid=$($started.Id)"
Start-Sleep -Seconds 8
if ($started.HasExited -and $started.ExitCode -ne 0) {
    throw "PATCH INSTALLED but launcher failed (exit=$($started.ExitCode)). Check ai-dispatcher.log."
}
$runtimeActive = Test-DispatcherMutex
Write-Host "RUNTIME MUTEX ACTIVE: $runtimeActive"
if (!$runtimeActive) {
    throw "PATCH INSTALLED but dispatcher not running; no state was deleted. Check ai-dispatcher.log."
}
Write-Host "DISPATCHER RUNNING; GitHub inflight and ChatGPT state files untouched."
Write-Host "Arena feedback auto-dismiss retained. CONTROL marker fallback added; LIVE receipt of turn 76 still requires log verification."
Write-Host "CONTROL delivery must be confirmed separately; patch does not reset queue or claim its success."
Write-Host "Watch live: Get-Content `"$HOME\ai-dispatcher.log`" -Tail 20 -Wait -Encoding UTF8"
