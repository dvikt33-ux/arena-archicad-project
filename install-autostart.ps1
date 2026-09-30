$ErrorActionPreference = 'Stop'

$CoreUrl = 'https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/agent-handoff/.agent-handoff/dispatcher.py'
$RuntimeUrl = 'https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/agent-handoff/.agent-handoff/dispatcher-runtime.py'
$DispatcherPath = Join-Path $HOME 'dispatcher.py'
$CorePath = Join-Path $HOME 'dispatcher_core.py'
$LogPath = Join-Path $HOME 'ai-dispatcher.log'
$BootstrapLog = Join-Path $HOME 'ai-dispatcher-bootstrap.log'
$StartupDir = [Environment]::GetFolderPath('Startup')
$VbsPath = Join-Path $StartupDir 'AI-Dispatcher.vbs'

Write-Host '=== AI Dispatcher installer ==='

if (Test-Path $DispatcherPath) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = "$DispatcherPath.bak-$stamp"
    Copy-Item $DispatcherPath $backup -Force
    Write-Host "Backup: $backup"
}

$cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
Write-Host 'Downloading dispatcher core from GitHub...'
Invoke-WebRequest -UseBasicParsing -Uri ($CoreUrl + '?ts=' + $cacheBust) -OutFile $CorePath
Write-Host 'Downloading dispatcher runtime from GitHub...'
Invoke-WebRequest -UseBasicParsing -Uri ($RuntimeUrl + '?ts=' + $cacheBust) -OutFile $DispatcherPath

Write-Host 'Checking Python syntax...'
& py -m py_compile $CorePath $DispatcherPath
if ($LASTEXITCODE -ne 0) {
    throw 'dispatcher syntax check failed.'
}

$coreVersionMatch = Select-String -Path $CorePath -Pattern '^VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
$runtimeVersionMatch = Select-String -Path $DispatcherPath -Pattern '^VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $coreVersionMatch -or -not $runtimeVersionMatch) {
    throw 'Could not determine Dispatcher version from downloaded files.'
}
$ExpectedVersion = $coreVersionMatch.Matches[0].Groups[1].Value
$RuntimeVersion = $runtimeVersionMatch.Matches[0].Groups[1].Value
if ($ExpectedVersion -ne $RuntimeVersion) {
    throw "Dispatcher core/runtime version mismatch: core=$ExpectedVersion runtime=$RuntimeVersion"
}
Write-Host "Downloaded AI Dispatcher $ExpectedVersion"

Write-Host 'Checking required Python packages...'
& py -c "import playwright, pyautogui, pygetwindow; print('Python packages: OK')"
if ($LASTEXITCODE -ne 0) {
    throw 'Required Python packages are missing. Install playwright, pyautogui and pygetwindow first.'
}

Write-Host 'Checking dispatcher core import...'
& py -c "import importlib.util,pathlib; p=pathlib.Path.home()/'dispatcher_core.py'; s=importlib.util.spec_from_file_location('dispatcher_core_preflight',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('Core import: OK', m.VERSION)"
if ($LASTEXITCODE -ne 0) {
    throw 'dispatcher core import check failed.'
}

$VbsContent = @'
Set shell = CreateObject("WScript.Shell")
userProfile = shell.ExpandEnvironmentStrings("%USERPROFILE%")
cmd = "cmd /c py """ & userProfile & "\dispatcher.py"""
shell.Run cmd, 0, False
'@

Set-Content -Path $VbsPath -Value $VbsContent -Encoding ASCII
Write-Host "Autostart created: $VbsPath"

Write-Host 'Stopping old dispatcher instances...'
Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^(py|python|pythonw)(\.exe)?$') -and
        ($_.CommandLine -match '(?i)[\\/](dispatcher|dispatcher_core)\.py')
    } |
    ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped PID $($_.ProcessId)"
        }
        catch {
            Write-Host "Could not stop PID $($_.ProcessId): $($_.Exception.Message)"
        }
    }

Start-Sleep -Seconds 1

$logBytesBefore = 0L
if (Test-Path $LogPath) {
    $logBytesBefore = (Get-Item $LogPath).Length
}
$bootstrapBytesBefore = 0L
if (Test-Path $BootstrapLog) {
    $bootstrapBytesBefore = (Get-Item $BootstrapLog).Length
}

Write-Host "Starting AI Dispatcher $ExpectedVersion hidden..."
$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = 'wscript.exe'
$startInfo.Arguments = '"' + $VbsPath + '"'
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$startInfo.UseShellExecute = $true
[System.Diagnostics.Process]::Start($startInfo) | Out-Null

$escapedVersion = [regex]::Escape($ExpectedVersion)
# ASCII-only match on purpose: Windows PowerShell 5.1 can misread UTF-8 scripts without BOM.
$startPattern = "AI Dispatcher $escapedVersion"
$deadline = (Get-Date).AddSeconds(30)
$started = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Path $LogPath) {
        $item = Get-Item $LogPath
        if ($item.Length -gt $logBytesBefore) {
            $tail = Get-Content $LogPath -Tail 60 -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($tail -match $startPattern) {
                $started = $true
                break
            }
        }
    }
    Start-Sleep -Milliseconds 500
}

if (-not $started) {
    $proc = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match '^(py|python|pythonw)(\.exe)?$') -and
        ($_.CommandLine -match '(?i)[\\/]dispatcher\.py')
    }
    if ($proc -and (Test-Path $LogPath)) {
        $tail = Get-Content $LogPath -Tail 80 -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($tail -match $startPattern) {
            $started = $true
        }
    }
}

if (-not $started) {
    Write-Warning "Autostart created, but AI Dispatcher $ExpectedVersion startup could not be confirmed."
    Write-Host ''
    Write-Host '--- Dispatcher processes ---'
    Get-CimInstance Win32_Process |
        Where-Object {
            ($_.Name -match '^(py|python|pythonw)(\.exe)?$') -and
            ($_.CommandLine -match '(?i)[\\/]dispatcher\.py')
        } |
        Select-Object ProcessId, Name, CommandLine |
        Format-List

    Write-Host '--- ai-dispatcher.log ---'
    if (Test-Path $LogPath) {
        Get-Content $LogPath -Tail 80 -Encoding UTF8 -ErrorAction SilentlyContinue
    }
    else {
        Write-Host 'Log file not found.'
    }

    Write-Host '--- ai-dispatcher-bootstrap.log ---'
    if (Test-Path $BootstrapLog) {
        $bootItem = Get-Item $BootstrapLog
        if ($bootItem.Length -gt $bootstrapBytesBefore) {
            Get-Content $BootstrapLog -Tail 80 -Encoding UTF8 -ErrorAction SilentlyContinue
        }
        else {
            Write-Host 'No new bootstrap error was recorded.'
        }
    }
    else {
        Write-Host 'Bootstrap log not found.'
    }
    exit 1
}

Write-Host 'Closing Arena completion prompt if it is currently blocking input...'
& py $DispatcherPath 'DISMISS-ARENA-PROMPT'
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Dispatcher started, but the one-shot Arena prompt check failed.'
}

Write-Host ''
Write-Host '=== Installed ==='
Write-Host "Version:    $ExpectedVersion"
Write-Host "Dispatcher: $DispatcherPath"
Write-Host "Core:       $CorePath"
Write-Host "Autostart:  $VbsPath"
Write-Host "Log:        $LogPath"
Write-Host ''

if (Test-Path $LogPath) {
    Write-Host 'Last log lines:'
    Get-Content $LogPath -Tail 30 -Encoding UTF8
}
