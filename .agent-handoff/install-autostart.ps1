$ErrorActionPreference = 'Stop'

$CoreUrl = 'https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/agent-handoff/.agent-handoff/dispatcher.py'
$RuntimeUrl = 'https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/agent-handoff/.agent-handoff/dispatcher-runtime.py'
$DispatcherPath = Join-Path $HOME 'dispatcher.py'
$CorePath = Join-Path $HOME 'dispatcher_core.py'
$LogPath = Join-Path $HOME 'ai-dispatcher.log'
$StartupDir = [Environment]::GetFolderPath('Startup')
$VbsPath = Join-Path $StartupDir 'AI-Dispatcher.vbs'

Write-Host '=== AI Dispatcher 2.2.4 installer ==='

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

Write-Host 'Checking required Python packages...'
& py -c "import playwright, pyautogui, pygetwindow; print('Python packages: OK')"
if ($LASTEXITCODE -ne 0) {
    throw 'Required Python packages are missing. Install playwright, pyautogui and pygetwindow first.'
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

Write-Host 'Starting AI Dispatcher 2.2.4 hidden...'
$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = 'wscript.exe'
$startInfo.Arguments = '"' + $VbsPath + '"'
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$startInfo.UseShellExecute = $true
[System.Diagnostics.Process]::Start($startInfo) | Out-Null

$deadline = (Get-Date).AddSeconds(15)
$started = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Path $LogPath) {
        $item = Get-Item $LogPath
        if ($item.Length -gt $logBytesBefore) {
            $tail = Get-Content $LogPath -Tail 30 -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($tail -match 'AI Dispatcher 2\.2\.4 запущен') {
                $started = $true
                break
            }
        }
    }
    Start-Sleep -Milliseconds 500
}

if (-not $started) {
    Write-Warning "Autostart created, but a fresh AI Dispatcher 2.2.4 startup was not confirmed in $LogPath"
    exit 1
}

Write-Host 'Closing Arena completion prompt if it is currently blocking input...'
& py $DispatcherPath 'DISMISS-ARENA-PROMPT'
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Dispatcher started, but the one-shot Arena prompt check failed.'
}

Write-Host ''
Write-Host '=== Installed ==='
Write-Host "Dispatcher: $DispatcherPath"
Write-Host "Core:       $CorePath"
Write-Host "Autostart:  $VbsPath"
Write-Host "Log:        $LogPath"
Write-Host ''

if (Test-Path $LogPath) {
    Write-Host 'Last log lines:'
    Get-Content $LogPath -Tail 25 -Encoding UTF8
}
