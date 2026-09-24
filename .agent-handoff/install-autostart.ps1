$ErrorActionPreference = 'Stop'

$DispatcherUrl = 'https://raw.githubusercontent.com/dvikt33-ux/arena-archicad-project/agent-handoff/.agent-handoff/dispatcher.py'
$DispatcherPath = Join-Path $HOME 'dispatcher.py'
$LogPath = Join-Path $HOME 'ai-dispatcher.log'
$StartupDir = [Environment]::GetFolderPath('Startup')
$VbsPath = Join-Path $StartupDir 'AI-Dispatcher.vbs'

Write-Host '=== AI Dispatcher 2.2 installer ==='

if (Test-Path $DispatcherPath) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = "$DispatcherPath.bak-$stamp"
    Copy-Item $DispatcherPath $backup -Force
    Write-Host "Backup: $backup"
}

Write-Host 'Downloading dispatcher.py from GitHub...'
Invoke-WebRequest -UseBasicParsing -Uri $DispatcherUrl -OutFile $DispatcherPath

Write-Host 'Checking Python syntax...'
& py -m py_compile $DispatcherPath
if ($LASTEXITCODE -ne 0) {
    throw 'dispatcher.py syntax check failed.'
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

Write-Host 'Stopping old dispatcher.py instances...'
Get-CimInstance Win32_Process |
    Where-Object {
        ($_.Name -match '^python(w)?\.exe$') -and
        ($_.CommandLine -match '(?i)[\\/]dispatcher\.py(?:\s|$|\")')
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

Write-Host 'Starting AI Dispatcher 2.2 hidden...'
Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$VbsPath`""

$deadline = (Get-Date).AddSeconds(12)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $LogPath) {
        $tail = Get-Content $LogPath -Tail 20 -ErrorAction SilentlyContinue
        if ($tail -match 'AI Dispatcher 2.2') {
            break
        }
    }
    Start-Sleep -Milliseconds 500
}

Write-Host ''
Write-Host '=== Installed ==='
Write-Host "Dispatcher: $DispatcherPath"
Write-Host "Autostart:  $VbsPath"
Write-Host "Log:        $LogPath"
Write-Host ''

if (Test-Path $LogPath) {
    Write-Host 'Last log lines:'
    Get-Content $LogPath -Tail 15
}
else {
    Write-Host 'Log has not appeared yet. Check in a few seconds:'
    Write-Host "  Get-Content `"$LogPath`" -Tail 30"
}
