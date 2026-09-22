# smoke-test.ps1 — end-to-end test of Arena Bridge v2 with FAKE git/gh shims.
# No network, no real repo, no GitHub. Works on Windows PowerShell 5.1 and pwsh.
#
#   pwsh -NoProfile -File smoke-test.ps1        (or:  powershell -NoProfile -File smoke-test.ps1)

$ErrorActionPreference = 'Stop'
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$root    = Split-Path -Parent $here
$bridge  = Join-Path $root 'arena-bridge-v2.ps1'
$router  = Join-Path $root 'arena-qwen-router-v2.ps1'
$isWin   = ($env:OS -eq 'Windows_NT')

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('arena-v2-smoke-' + [guid]::NewGuid().ToString('N'))
$repoDir   = Join-Path $tmp 'repo'
$arenaRoot = Join-Path $tmp 'ArenaBridge'
$shimDir   = Join-Path $tmp 'shims'
$notARepo  = Join-Path $tmp 'notarepo'

$inboxDir   = Join-Path $arenaRoot 'inbox'
$outboxDir  = Join-Path $arenaRoot 'outbox'
$resultsDir = Join-Path $arenaRoot 'results'
$statePath  = Join-Path $arenaRoot 'state.json'

New-Item -ItemType Directory -Path $repoDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $repoDir '.git') -Force | Out-Null
New-Item -ItemType Directory -Path $notARepo -Force | Out-Null
New-Item -ItemType Directory -Path $shimDir -Force | Out-Null

# ---- fake git / gh shims ----
$fakeTop    = $repoDir
$fakeOrigin = 'https://github.com/dvikt33-ux/arena-archicad-project.git'
$ghLog      = Join-Path $tmp 'gh.log'

if ($isWin) {
    $gitCmd = @'
@echo off
if "%1"=="-C" ( shift & shift )
if "%FAKE_GIT_FAIL%"=="1" (
  if not "%1"=="rev-parse" (
    if not "%1"=="remote" (
      echo fake git failure 1>&2
      exit /b 1
    )
  )
)
if "%1"=="--version" ( echo git version 2.44.0.fake & exit /b 0 )
if "%1"=="rev-parse" ( echo %FAKE_GIT_TOP% & exit /b 0 )
if "%1"=="remote" (
  if "%2"=="get-url" (
    echo %FAKE_GIT_ORIGIN%
    exit /b 0
  )
)
if "%1"=="status" ( echo On branch fake & echo nothing to commit, working tree clean & exit /b 0 )
if "%1"=="log" ( echo abc1234 first fake commit & echo def5678 second fake commit & exit /b 0 )
if "%1"=="diff" ( echo fake-diff-line & exit /b 0 )
echo fake git: unknown command %1 1>&2
exit /b 1
'@
    $ghCmd = @'
@echo off
echo %* >> "%FAKE_GH_LOG%"
echo %* | findstr /c:".[]" >nul
if %errorlevel%==0 ( exit /b 0 )
echo 999
exit /b 0
'@
    Set-Content -LiteralPath (Join-Path $shimDir 'git.cmd') -Value $gitCmd -Encoding ASCII
    Set-Content -LiteralPath (Join-Path $shimDir 'gh.cmd')  -Value $ghCmd  -Encoding ASCII
}
else {
    $gitSh = @(
        '#!/bin/sh'
        'if [ "$1" = "-C" ]; then shift 2; fi'
        'if [ "$FAKE_GIT_FAIL" = "1" ]; then'
        '  case "$1" in'
        '    rev-parse|remote) : ;;'
        '    *) echo "fake git failure" >&2; exit 1;;'
        '  esac'
        'fi'
        'case "$1" in'
        '  --version) echo "git version 2.44.0.fake"; exit 0;;'
        '  rev-parse) echo "$FAKE_GIT_TOP"; exit 0;;'
        '  remote) if [ "$2" = "get-url" ]; then echo "$FAKE_GIT_ORIGIN"; exit 0; fi;;'
        '  status) echo "On branch fake"; echo "nothing to commit, working tree clean"; exit 0;;'
        '  log) echo "abc1234 first fake commit"; echo "def5678 second fake commit"; exit 0;;'
        '  diff) echo "fake-diff-line"; exit 0;;'
        'esac'
        'echo "fake git: unknown command $1" >&2'
        'exit 1'
    ) -join "`n"
    $ghSh = @(
        '#!/bin/sh'
        'echo "$*" >> "$FAKE_GH_LOG"'
        'case "$*" in'
        '  *".[]"*) exit 0;;'
        'esac'
        'echo 999'
        'exit 0'
    ) -join "`n"
    $gitShim = Join-Path $shimDir 'git'
    $ghShim  = Join-Path $shimDir 'gh'
    Set-Content -LiteralPath $gitShim -Value $gitSh -Encoding UTF8
    Set-Content -LiteralPath $ghShim  -Value $ghSh  -Encoding UTF8
    & chmod +x $gitShim $ghShim
}

$env:PATH = $shimDir + [System.IO.Path]::PathSeparator + $env:PATH
$env:FAKE_GIT_TOP    = $fakeTop
$env:FAKE_GIT_ORIGIN = $fakeOrigin
$env:FAKE_GH_LOG     = $ghLog
Remove-Item Env:FAKE_GIT_FAIL -ErrorAction SilentlyContinue

$runner = (Get-Process -Id $PID).Path

# ---- helpers ----
function Assert {
    param([bool]$Cond, [string]$Msg)
    if (-not $Cond) { throw "ASSERT FAILED: $Msg" }
    Write-Host "  ok: $Msg"
}

function Invoke-Bridge {
    param(
        [string]$WorkDir = $repoDir,
        [string]$Repo = 'dvikt33-ux/arena-archicad-project',
        [string]$ArenaRoot = $arenaRoot,
        [switch]$NoGithub
    )
    $a = @('-NoProfile', '-File', $bridge, '-Once')
    $a += '-WorkDir', $WorkDir
    $a += '-Repo', $Repo
    $a += '-ArenaRoot', $ArenaRoot
    if ($NoGithub) { $a += '-NoGithub' }
    $out = & $runner @a 2>&1
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Code = $code; Out = ($out | Out-String) }
}

function Get-StateObj {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    return (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json)
}

function Get-TaskObj {
    param([string]$Seq)
    $s = Get-StateObj
    if ($null -eq $s -or $null -eq $s.tasks) { return $null }
    return $s.tasks."$Seq"
}

function Write-TaskFile {
    param([int]$Seq, [string]$Action)
    $o = [ordered]@{ seq = $Seq; action = $Action; ts = (Get-Date -Format o); request = 'smoke' }
    $o | ConvertTo-Json -Depth 5 -Compress |
        Set-Content -LiteralPath (Join-Path $inboxDir "$Seq.json") -Encoding UTF8
}

Write-Host ''
Write-Host '=== Arena Bridge v2 smoke test ==='
Write-Host "runner: $runner"
Write-Host ''

# 1. first run creates + seeds state
Write-Host '[1] first run (no tasks)'
$r = Invoke-Bridge -NoGithub
Assert ($r.Code -eq 0) 'first run exit 0'
$s = Get-StateObj
Assert ($null -ne $s -and $s.last_seq -eq 0) 'state.json created with last_seq=0'

# 2. normal task GIT_STATUS
Write-Host '[2] GIT_STATUS task'
Write-TaskFile 1 'GIT_STATUS'
$r = Invoke-Bridge -NoGithub
Assert ($r.Code -eq 0) 'run exit 0'
$s = Get-StateObj
Assert ($s.last_seq -eq 1) 'last_seq advanced to 1'
$t = Get-TaskObj '1'
Assert ($t.state -eq 'PENDING_PUBLISH' -and $t.status -eq 'COMPLETED' -and $t.exit -eq 0) 'task 1 COMPLETED exit 0'
$res1Path = Join-Path $resultsDir 'result-1.txt'
Assert (Test-Path -LiteralPath $res1Path) 'result-1.txt written'
$res1 = Get-Content -LiteralPath $res1Path -Raw
Assert ($res1 -match 'On branch fake') 'result contains fake git output'
Assert (Test-Path -LiteralPath (Join-Path $outboxDir '1.json')) 'outbox has 1.json (pending publish)'
Assert (-not (Test-Path -LiteralPath (Join-Path $inboxDir '1.json'))) 'inbox 1.json consumed'

# 3. duplicate / replay
Write-Host '[3] duplicate seq 1 (replay)'
Write-TaskFile 1 'GIT_STATUS'
$r = Invoke-Bridge -NoGithub
$s = Get-StateObj
Assert ($s.last_seq -eq 1) 'last_seq unchanged on replay'
Assert (-not (Test-Path -LiteralPath (Join-Path $inboxDir '1.json'))) 'replay file moved aside'

# 4. unknown action -> BLOCKED
Write-Host '[4] unknown action'
Write-TaskFile 2 'RM_RF'
$r = Invoke-Bridge -NoGithub
$s = Get-StateObj
Assert ($s.last_seq -eq 2) 'last_seq=2'
$t = Get-TaskObj '2'
Assert ($t.status -eq 'BLOCKED') 'task 2 BLOCKED'

# 5. gap (missing 3)
Write-Host '[5] gap: seq 4 before 3'
Write-TaskFile 4 'GIT_VERSION'
$r = Invoke-Bridge -NoGithub
$s = Get-StateObj
Assert ($s.last_seq -eq 2) 'gap not executed (last_seq still 2)'
Assert (Test-Path -LiteralPath (Join-Path $inboxDir '4.json')) 'seq 4 still waiting in inbox'

# 6. fill gap -> both drain in order
Write-Host '[6] fill gap with seq 3'
Write-TaskFile 3 'GIT_DIFF'
$r = Invoke-Bridge -NoGithub
$s = Get-StateObj
Assert ($s.last_seq -eq 4) 'drained to 4'
Assert ($(Get-TaskObj '3').status -eq 'COMPLETED') 'task 3 COMPLETED'
Assert ($(Get-TaskObj '4').status -eq 'COMPLETED') 'task 4 COMPLETED'
$o3 = Get-Content -LiteralPath (Join-Path $outboxDir '3.json') -Raw | ConvertFrom-Json
Assert ($o3.public -eq $false) 'GIT_DIFF marked public=false'
Assert ($o3.public_body -match 'local-only') 'GIT_DIFF public body omits result'
Assert (@(Get-ChildItem -LiteralPath $inboxDir -Filter '*.json' -File).Count -eq 0) 'inbox empty'

# 7. repo guard failure (no .git)
Write-Host '[7] repo guard: workdir without .git'
Write-TaskFile 5 'GIT_STATUS'
$r = Invoke-Bridge -NoGithub -WorkDir $notARepo
$s = Get-StateObj
$t = Get-TaskObj '5'
Assert ($s.last_seq -eq 5) 'last_seq=5'
Assert ($t.status -eq 'FAILED' -and $t.reason -eq 'repo-guard:no-git-dir') 'task 5 FAILED (repo-guard:no-git-dir)'

# 8. git non-zero exit -> FAILED (not re-run)
Write-Host '[8] git exit 1 -> FAILED'
$env:FAKE_GIT_FAIL = '1'
Write-TaskFile 6 'GIT_STATUS'
$r = Invoke-Bridge -NoGithub
Remove-Item Env:FAKE_GIT_FAIL -ErrorAction SilentlyContinue
$t = Get-TaskObj '6'
Assert ($t.status -eq 'FAILED' -and $t.exit -eq 1) 'task 6 FAILED exit 1'

# 9. crash recovery: RUNNING -> FAILED(recovered)
Write-Host '[9] crash recovery (RUNNING fence)'
$s = Get-StateObj
$runTask = [pscustomobject]@{ action = 'GIT_STATUS'; state = 'RUNNING'; pid = 12345; started = '2026-09-22T12:00:00Z' }
$s.tasks | Add-Member -NotePropertyName '7' -NotePropertyValue $runTask -Force
$s | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $statePath -Encoding UTF8
$r = Invoke-Bridge -NoGithub
$t = Get-TaskObj '7'
Assert ($t.status -eq 'FAILED' -and ($t.reason -match 'recovered')) 'task 7 FAILED(recovered), no auto re-run'
Assert (Test-Path -LiteralPath (Join-Path $outboxDir '7.json')) 'recovery marker in outbox'

# 10. publish with fake gh (no -NoGithub)
Write-Host '[10] publish via fake gh'
$r = Invoke-Bridge
Assert ($r.Code -eq 0) 'publish run exit 0'
$t = Get-TaskObj '1'
Assert ($t.state -eq 'PUBLISHED' -and $t.comment_id -eq 999) 'task 1 PUBLISHED comment_id=999'
Assert (@(Get-ChildItem -LiteralPath $outboxDir -Filter '*.json' -File).Count -eq 0) 'outbox drained'

# 11. corrupt state -> fail closed (exit 6)
Write-Host '[11] corrupt state.json -> fail closed'
'this is not json' | Set-Content -LiteralPath $statePath -Encoding UTF8
$r = Invoke-Bridge -NoGithub
Assert ($r.Code -eq 6) 'bridge exits 6 on corrupt state'
Assert ($r.Out -match 'FATAL') 'FATAL message printed'

# 12. audit log exists
$audit = Get-ChildItem -LiteralPath $arenaRoot -Filter 'audit-*.jsonl' -File | Select-Object -First 1
Assert ($null -ne $audit -and $audit.Length -gt 0) 'audit log written'

Write-Host ''
Write-Host 'ALL SMOKE TESTS PASSED'
Write-Host "sandbox left at: $tmp"
