# Safe local upgrade for Arena -> ChatGPT CONTROL recovery.
# Only modifies the dispatcher.py file after exact source verification and tests.
# Never changes Git branches, ChatGPT state, model/PLN/APX, or signal.json.
param()
$ErrorActionPreference = "Stop"

$repo = Join-Path $HOME "Documents\arena-archicad-project"
$dispatcher = Join-Path $repo ".agent-handoff\dispatcher.py"
$sourceBlob = "f690895dc2ebb36dae76b3442e1943dc225cfe42"
$patchedBlob = "e8b570511d55e9cda47a4e5a65d63f86c34d5fb9"
$commit = "493c1624bfc1d01be42bfce845ee6ea9d1a13b87"
$prefix = "https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/$commit/.agent-handoff"
$stage = Join-Path $env:TEMP ("APA_Control_Rescue_" + [DateTime]::UtcNow.ToString("yyyyMMdd_HHmmss"))
$testPath = Join-Path $stage "tests"
$null = New-Item -ItemType Directory -Force -Path $testPath
$downloaded = Join-Path $stage "dispatcher.py"
$testFile = Join-Path $testPath "test_stale_control_rescue.py"

function GitBlob([string]$file) {
    $hash = & git.exe hash-object -- $file 2>$null
    if ($LASTEXITCODE -ne 0 -or !$hash) { throw "git hash-object failed: $file" }
    return ([string]$hash).Trim()
}
if (!(Test-Path -LiteralPath $dispatcher)) { throw "Dispatcher not found: $dispatcher" }
$current = GitBlob $dispatcher
if ($current -eq $patchedBlob) {
    Write-Host "ALREADY_PATCHED: true; no replacement required."
    exit 0
}
if ($current -ne $sourceBlob) {
    throw "STOP: installed dispatcher differs from reviewed source (blob=$current). Nothing changed."
}

Write-Host "Downloading pinned dispatcher and regression tests from commit $commit"
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/dispatcher.py" -OutFile $downloaded
Invoke-WebRequest -UseBasicParsing -Uri "$prefix/tests/test_stale_control_rescue.py" -OutFile $testFile
if ((GitBlob $downloaded) -ne $patchedBlob) {
    throw "STOP: downloaded code SHA mismatch. Nothing changed."
}

# Execute only syntax and unit tests; never run the dispatcher during preflight.
& py.exe -3 -m py_compile $downloaded
if ($LASTEXITCODE -ne 0) { throw "STOP: Python syntax error; no changes." }
& py.exe -3 -m unittest discover -s $testPath -p "test_stale_control_rescue.py" -v
if ($LASTEXITCODE -ne 0) { throw "STOP: regression tests failed; no changes." }
Write-Host "PREFLIGHT PASS"

# Only stop a Python process explicitly running this exact script.
$targetNorm = $dispatcher.Replace("/","\").ToLowerInvariant()
$matches = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
    Where-Object {
        $_.Name -match '^(python|pythonw)\.exe$' -and
        ([string]$_.CommandLine).Replace("/","\").ToLowerInvariant().Contains($targetNorm)
    }
)
if ($matches.Count -ne 1) {
    throw "STOP: expected exactly ONE running dispatcher, found $($matches.Count). No process or source changed."
}

$backup = "$dispatcher.before-control-rescue-20261016.bak"
if (Test-Path -LiteralPath $backup) {
    throw "STOP: backup already exists ($backup). No process or source changed."
}
Copy-Item -LiteralPath $dispatcher -Destination $backup -ErrorAction Stop
if ((GitBlob $backup) -ne $sourceBlob) {
    throw "STOP: backup verification failed; dispatcher not stopped or replaced."
}
Write-Host "VERIFIED BACKUP: $backup"

$id = [int]$matches[0].ProcessId
Stop-Process -Id $id -ErrorAction Stop
for ($i=0; $i -lt 20; $i++) {
    if (!(Get-Process -Id $id -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}
if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
    throw "STOP: dispatcher did not exit; original source untouched."
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

# Preserve %USERPROFILE% state files intact; the new code reads pending turn 72.
$py = (Get-Command py.exe -ErrorAction Stop).Source
Start-Process -FilePath $py -ArgumentList @("-3", "-u", ('"' + $dispatcher + '"')) -WorkingDirectory (Split-Path $dispatcher)
Write-Host "PATCH INSTALLED AND DISPATCHER START REQUESTED"
Write-Host "Existing state and GitHub signal were not modified."
Write-Host "Watch live: Get-Content `"$HOME\ai-dispatcher.log`" -Tail 20 -Wait -Encoding UTF8"
