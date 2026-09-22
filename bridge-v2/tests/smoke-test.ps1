# smoke-test.ps1 — end-to-end test of Arena Bridge v2 with FAKE git/gh shims.
# No network, no real repo, no GitHub. Works on Windows PowerShell 5.1 and pwsh.
#
#   pwsh -NoProfile -File smoke-test.ps1
#   powershell -NoProfile -File smoke-test.ps1
#
# The test plants a fake v1 last-task.txt (id 17) and then forces the bridge to
# ignore it. On a real Windows machine that file already exists, and reading it
# made check [1] fail with last_seq != 0.

$ErrorActionPreference = 'Stop'
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$root    = Split-Path -Parent $here
$bridge  = Join-Path $root 'arena-bridge-v2.ps1'
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

# A real v1 machine has these files. The suite must still start at last_seq=0.
$fakeProfile = Join-Path $tmp 'FakeProfile'
$fakeDocs = Join-Path $fakeProfile 'Documents'
New-Item -ItemType Directory -Path $fakeDocs -Force | Out-Null
$ascii = [System.Text.Encoding]::ASCII
[System.IO.File]::WriteAllText((Join-Path $fakeDocs 'arena-bridge-last-task.txt'), "17`r`n", $ascii)
[System.IO.File]::WriteAllText((Join-Path $fakeDocs 'arena-bridge-task.txt'), "GIT_STATUS`r`n", $ascii)
$env:USERPROFILE = $fakeProfile
$env:HOME = $fakeProfile

$missingLegacy = Join-Path $tmp 'missing-legacy-state.txt'
$missingTask = Join-Path $tmp 'missing-legacy-task.txt'
$env:ARENA_BRIDGE_LEGACY_STATE_FILE = $missingLegacy
$env:ARENA_BRIDGE_LEGACY_TASK_FILE = $missingTask

# ---- fake git / gh shims ----
$fakeTop    = $repoDir
$fakeOrigin = 'https://github.com/dvikt33-ux/arena-archicad-project.git'
$ghLog      = Join-Path $tmp 'gh.log'

function Write-AsciiCrlf {
    param([string]$Path, [string[]]$Lines)
    $text = ($Lines -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText($Path, $text, [System.Text.Encoding]::ASCII)
}

if ($isWin) {
    # CRLF, no BOM. cmd.exe mis-parses LF-only batch files, and a UTF-8 BOM
    # makes "@echo off" fail. Verbs are detected in the raw command line so a
    # path with spaces (common under C:\Users\...) cannot shift %1 off the verb.
    Write-AsciiCrlf (Join-Path $shimDir 'git.cmd') @(
        '@echo off',
        'setlocal EnableExtensions',
        'echo %* | findstr /I /C:"--version" >nul',
        'if not errorlevel 1 goto version',
        'echo %* | findstr /I /C:"rev-parse" >nul',
        'if not errorlevel 1 goto revparse',
        'echo %* | findstr /I /C:"remote" >nul',
        'if not errorlevel 1 goto remote',
        'if "%FAKE_GIT_FAIL%"=="1" goto fail',
        'echo %* | findstr /I /C:" status" >nul',
        'if not errorlevel 1 goto status',
        'echo %* | findstr /I /C:" log" >nul',
        'if not errorlevel 1 goto gitlog',
        'echo %* | findstr /I /C:" diff" >nul',
        'if not errorlevel 1 goto diff',
        'echo fake git: unknown command 1>&2',
        'exit /b 1',
        ':version',
        'echo git version 2.44.0.fake',
        'exit /b 0',
        ':revparse',
        'echo.%FAKE_GIT_TOP%',
        'exit /b 0',
        ':remote',
        'echo.%FAKE_GIT_ORIGIN%',
        'exit /b 0',
        ':fail',
        'echo fake git failure 1>&2',
        'exit /b 1',
        ':status',
        'echo On branch fake',
        'echo nothing to commit, working tree clean',
        'exit /b 0',
        ':gitlog',
        'echo abc1234 first fake commit',
        'echo def5678 second fake commit',
        'exit /b 0',
        ':diff',
        'echo fake-diff-line',
        'exit /b 0'
    )
    # FAKE_GH_POST_FILE / FAKE_GH_GET_FILE let a test return a real GitHub
    # comment object (id larger than Int32) without putting "<" into cmd.exe.
    Write-AsciiCrlf (Join-Path $shimDir 'gh.cmd') @(
        '@echo off',
        'setlocal EnableExtensions',
        '>>"%FAKE_GH_LOG%" echo %*',
        'echo %* | findstr /I /C:"-X POST" >nul',
        'if not errorlevel 1 goto dopost',
        'echo %* | findstr /I /C:"-X PATCH" >nul',
        'if not errorlevel 1 goto dobody',
        'if "%FAKE_GH_SEEN%"=="" goto empty',
        'if not exist "%FAKE_GH_SEEN%" goto empty',
        'if "%FAKE_GH_GET_FILE%"=="" goto empty',
        'if not exist "%FAKE_GH_GET_FILE%" goto empty',
        'type "%FAKE_GH_GET_FILE%"',
        'exit /b 0',
        ':empty',
        'echo []',
        'exit /b 0',
        ':dopost',
        'if not "%FAKE_GH_SEEN%"=="" echo seen>"%FAKE_GH_SEEN%"',
        'goto dobody',
        ':dobody',
        'if "%FAKE_GH_POST_FILE%"=="" goto smallid',
        'if not exist "%FAKE_GH_POST_FILE%" goto smallid',
        'type "%FAKE_GH_POST_FILE%"',
        'exit /b 0',
        ':smallid',
        'echo {"id":999}',
        'exit /b 0'
    )
}
else {
    $gitSh = @(
        '#!/bin/sh',
        'if [ "$1" = "-C" ]; then shift 2; fi',
        'if [ "$FAKE_GIT_FAIL" = "1" ]; then',
        '  case "$1" in',
        '    rev-parse|remote) : ;;',
        '    *) echo "fake git failure" >&2; exit 1;;',
        '  esac',
        'fi',
        'case "$1" in',
        '  --version) echo "git version 2.44.0.fake"; exit 0;;',
        '  rev-parse) echo "$FAKE_GIT_TOP"; exit 0;;',
        '  remote) if [ "$2" = "get-url" ]; then echo "$FAKE_GIT_ORIGIN"; exit 0; fi;;',
        '  status) echo "On branch fake"; echo "nothing to commit, working tree clean"; exit 0;;',
        '  log) echo "abc1234 first fake commit"; echo "def5678 second fake commit"; exit 0;;',
        '  diff) echo "fake-diff-line"; exit 0;;',
        'esac',
        'echo "fake git: unknown command $1" >&2',
        'exit 1'
    ) -join "`n"
    $ghSh = @'
#!/bin/sh
echo "$*" >> "$FAKE_GH_LOG"
case "$*" in
  *"-X POST"*)
    if [ -n "$FAKE_GH_SEEN" ]; then : > "$FAKE_GH_SEEN"; fi
    if [ -n "$FAKE_GH_POST_FILE" ] && [ -f "$FAKE_GH_POST_FILE" ]; then
      cat "$FAKE_GH_POST_FILE"
      exit 0
    fi
    printf '%s\n' '{"id":999}'
    exit 0
    ;;
  *"-X PATCH"*)
    if [ -n "$FAKE_GH_POST_FILE" ] && [ -f "$FAKE_GH_POST_FILE" ]; then
      cat "$FAKE_GH_POST_FILE"
      exit 0
    fi
    printf '%s\n' '{"id":999}'
    exit 0
    ;;
esac
if [ -n "$FAKE_GH_SEEN" ] && [ -f "$FAKE_GH_SEEN" ] && [ -n "$FAKE_GH_GET_FILE" ] && [ -f "$FAKE_GH_GET_FILE" ]; then
  cat "$FAKE_GH_GET_FILE"
  exit 0
fi
printf '%s\n' '[]'
exit 0
'@
    $gitShim = Join-Path $shimDir 'git'
    $ghShim  = Join-Path $shimDir 'gh'
    [System.IO.File]::WriteAllText($gitShim, $gitSh + "`n")
    [System.IO.File]::WriteAllText($ghShim, $ghSh + "`n")
    & chmod +x $gitShim $ghShim
}

$env:PATH = $shimDir + [System.IO.Path]::PathSeparator + $env:PATH
$env:FAKE_GIT_TOP    = $fakeTop
$env:FAKE_GIT_ORIGIN = $fakeOrigin
$env:FAKE_GH_LOG     = $ghLog
Remove-Item Env:FAKE_GIT_FAIL -ErrorAction SilentlyContinue

$runner = (Get-Process -Id $PID).Path

function Assert {
    param([bool]$Cond, [string]$Msg)
    if (-not $Cond) { throw "ASSERT FAILED: $Msg" }
    Write-Host "  ok: $Msg"
}

function Invoke-Bridge {
    # Paths go through the environment. Windows PowerShell 5.1 re-joins native
    # arguments, and a profile path with spaces would otherwise split -ArenaRoot.
    param(
        [string]$WorkDir = $repoDir,
        [string]$Repo = 'dvikt33-ux/arena-archicad-project',
        [string]$ArenaRoot = $arenaRoot,
        [switch]$NoGithub
    )
    $env:ARENA_BRIDGE_WORKDIR = $WorkDir
    $env:ARENA_BRIDGE_REPO = $Repo
    $env:ARENA_BRIDGE_ROOT = $ArenaRoot
    $env:ARENA_BRIDGE_ISSUE = '1'
    $a = @('-NoProfile', '-File', $bridge, '-Once')
    if ($NoGithub) { $a += '-NoGithub' }
    $out = & $runner @a 2>&1
    $code = $LASTEXITCODE
    # Do not use Out-String: it wraps at the console width, and a Windows
    # temp path is often longer than 80 columns.
    $text = @($out | ForEach-Object { "$_" }) -join "`n"
    return [pscustomobject]@{ Code = $code; Out = $text }
}

function Get-StateObj {
    param([string]$Path = $statePath)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
}

function Get-TaskObj {
    param([string]$Seq)
    $s = Get-StateObj
    if ($null -eq $s -or $null -eq $s.tasks) { return $null }
    $prop = $s.tasks.PSObject.Properties[$Seq]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Write-TaskFile {
    param([int]$Seq, [string]$Action)
    $o = [ordered]@{ seq = $Seq; action = $Action; ts = (Get-Date -Format o); request = 'smoke' }
    $json = $o | ConvertTo-Json -Depth 5 -Compress
    $enc = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText((Join-Path $inboxDir "$Seq.json"), $json, $enc)
}

Write-Host ''
Write-Host '=== Arena Bridge v2 smoke test ==='
Write-Host "powershell: $($PSVersionTable.PSVersion)"
Write-Host "runner: $runner"
Write-Host ''

# 1. first run must NOT inherit the real (or fake) v1 last-task id
Write-Host '[1] first run ignores v1 last-task.txt'
$r = Invoke-Bridge -NoGithub
Assert ($r.Code -eq 0) 'first run exit 0'
$s = Get-StateObj
if ($null -eq $s) { throw "ASSERT FAILED: state.json missing at $statePath; out=$($r.Out)" }
Assert ($s.last_seq -eq 0) "last_seq=0 (actual=$($s.last_seq); a v1 last-task.txt must not leak in)"
Assert ($r.Out -match 'ARENA_BRIDGE_LAST_SEQ=0') 'child reported last_seq=0'
Assert ($r.Out -match [regex]::Escape("ARENA_BRIDGE_LEGACY=$missingLegacy")) 'child used the sandboxed legacy path'
Assert ($r.Out -notmatch 'Seeded last_seq=') 'no legacy seed message'

# 1b. seeding still works, but only from the path the test points at
Write-Host '[1b] sandboxed legacy seed'
$seedFile = Join-Path $tmp 'legacy-last-task.txt'
[System.IO.File]::WriteAllText($seedFile, "12`r`n", $ascii)
$seedRoot = Join-Path $tmp 'SeedBridge'
$env:ARENA_BRIDGE_LEGACY_STATE_FILE = $seedFile
$r = Invoke-Bridge -NoGithub -ArenaRoot $seedRoot
Assert ($r.Code -eq 0) 'seed run exit 0'
$seedState = Get-StateObj -Path (Join-Path $seedRoot 'state.json')
Assert ($null -ne $seedState -and $seedState.last_seq -eq 12) "sandboxed legacy file seeds 12 (actual=$($seedState.last_seq))"
$env:ARENA_BRIDGE_LEGACY_STATE_FILE = $missingLegacy
$env:ARENA_BRIDGE_LEGACY_TASK_FILE = $missingTask

# 2. normal task GIT_STATUS
Write-Host '[2] GIT_STATUS task'
Write-TaskFile 1 'GIT_STATUS'
$r = Invoke-Bridge -NoGithub
Assert ($r.Code -eq 0) 'run exit 0'
$s = Get-StateObj
Assert ($s.last_seq -eq 1) "last_seq advanced to 1 (actual=$($s.last_seq))"
$t = Get-TaskObj '1'
Assert ($null -ne $t -and $t.state -eq 'PENDING_PUBLISH' -and $t.status -eq 'COMPLETED' -and $t.exit -eq 0) 'task 1 COMPLETED exit 0'
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
Assert ($null -ne $t -and $t.status -eq 'BLOCKED') 'task 2 BLOCKED'

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
Assert ($null -ne $t -and $t.status -eq 'FAILED' -and $t.reason -eq 'repo-guard:no-git-dir') 'task 5 FAILED (repo-guard:no-git-dir)'

# 8. git non-zero exit -> FAILED (not re-run)
Write-Host '[8] git exit 1 -> FAILED'
$env:FAKE_GIT_FAIL = '1'
Write-TaskFile 6 'GIT_STATUS'
$r = Invoke-Bridge -NoGithub
Remove-Item Env:FAKE_GIT_FAIL -ErrorAction SilentlyContinue
$t = Get-TaskObj '6'
Assert ($null -ne $t -and $t.status -eq 'FAILED' -and $t.exit -eq 1) 'task 6 FAILED exit 1'

# 9. crash recovery: RUNNING -> FAILED(recovered)
Write-Host '[9] crash recovery (RUNNING fence)'
$s = Get-StateObj
$runTask = [pscustomobject]@{ action = 'GIT_STATUS'; state = 'RUNNING'; pid = 12345; started = '2026-09-22T12:00:00Z' }
$s.tasks | Add-Member -NotePropertyName '7' -NotePropertyValue $runTask -Force
$s | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $statePath -Encoding UTF8
$r = Invoke-Bridge -NoGithub
$t = Get-TaskObj '7'
Assert ($null -ne $t -and $t.status -eq 'FAILED' -and ($t.reason -match 'recovered')) 'task 7 FAILED(recovered), no auto re-run'
Assert (Test-Path -LiteralPath (Join-Path $outboxDir '7.json')) 'recovery marker in outbox'

# 10. publish with fake gh (no -NoGithub)
Write-Host '[10] publish via fake gh'
$r = Invoke-Bridge
if ($r.Code -ne 0) { throw "ASSERT FAILED: publish run exit 0 (actual=$($r.Code)) out=$($r.Out)" }
Write-Host '  ok: publish run exit 0'
$t = Get-TaskObj '1'
Assert ($null -ne $t -and $t.state -eq 'PUBLISHED' -and $t.comment_id -eq 999) "task 1 PUBLISHED comment_id=999 (state=$($t.state) id=$($t.comment_id))"
Assert (@(Get-ChildItem -LiteralPath $outboxDir -Filter '*.json' -File).Count -eq 0) 'outbox drained'

# 11. corrupt state -> fail closed (exit 6)
Write-Host '[11] corrupt state.json -> fail closed'
'this is not json' | Set-Content -LiteralPath $statePath -Encoding UTF8
$r = Invoke-Bridge -NoGithub
Assert ($r.Code -eq 6) "bridge exits 6 on corrupt state (actual=$($r.Code))"
Assert ($r.Out -match 'FATAL') 'FATAL message printed'

# 12. audit log exists
$audit = Get-ChildItem -LiteralPath $arenaRoot -Filter 'audit-*.jsonl' -File | Select-Object -First 1
Assert ($null -ne $audit -and $audit.Length -gt 0) 'audit log written'

# 13. GitHub comment ids are larger than Int32. gh exit 0 plus an unrecognized
# id used to retry the POST and duplicate <!-- arena-task:N --> in Issue #1.
Write-Host '[13] large comment id is success, second publish is PATCH'
$bigRoot = Join-Path $tmp 'BigIdBridge'
$bigOut = Join-Path $bigRoot 'outbox'
$bigState = Join-Path $bigRoot 'state.json'
New-Item -ItemType Directory -Path $bigOut -Force | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false
$stateJson = '{"last_seq":4,"tasks":{"4":{"action":"GIT_STATUS","state":"PENDING_PUBLISH","status":"COMPLETED","exit":0}}}'
[System.IO.File]::WriteAllText($bigState, $stateJson, $utf8)
$outJson = (@{
    seq = 4
    action = 'GIT_STATUS'
    status = 'COMPLETED'
    public = $true
    public_body = "[LOCAL RESULT 4] <!-- arena-task:4 -->`r`n`r`nSTATUS:`r`nCOMPLETED"
    attempts = 0
} | ConvertTo-Json -Depth 5 -Compress)
[System.IO.File]::WriteAllText((Join-Path $bigOut '4.json'), $outJson, $utf8)
$postFile = Join-Path $tmp 'gh-post.json'
$getFile = Join-Path $tmp 'gh-get.json'
$seenFile = Join-Path $tmp 'gh-seen'
$postBody = @'
{
  "url": "https://api.github.com/repos/dvikt33-ux/arena-archicad-project/issues/comments/5781348704",
  "id": 5781348704,
  "user": { "login": "dvikt33-ux", "id": 327351075 },
  "body": "[LOCAL RESULT 4] <!-- arena-task:4 -->"
}
'@
$getBody = @'
[
  {
    "id": 111,
    "user": { "login": "older", "id": 1 },
    "body": "older comment"
  },
  {
    "id": 5781348704,
    "user": { "login": "dvikt33-ux", "id": 327351075 },
    "body": "[LOCAL RESULT 4] <!-- arena-task:4 -->"
  }
]
'@
[System.IO.File]::WriteAllText($postFile, $postBody.Trim() + "`n", $utf8)
[System.IO.File]::WriteAllText($getFile, $getBody.Trim() + "`n", $utf8)
if (Test-Path -LiteralPath $seenFile) { Remove-Item -LiteralPath $seenFile -Force }
$env:FAKE_GH_POST_FILE = $postFile
$env:FAKE_GH_GET_FILE = $getFile
$env:FAKE_GH_SEEN = $seenFile
$env:FAKE_GH_LOG = Join-Path $tmp 'gh-bigid.log'
if (Test-Path -LiteralPath $env:FAKE_GH_LOG) { Remove-Item -LiteralPath $env:FAKE_GH_LOG -Force }
$r = Invoke-Bridge -ArenaRoot $bigRoot
Assert ($r.Code -eq 0) "large-id publish exit 0 (actual=$($r.Code))"
if ($r.Out -match 'PUBLISH RETRY') { throw "ASSERT FAILED: no retry after gh exit 0: $($r.Out)" }; Write-Host '  ok: no retry after gh exit 0'
Assert ($r.Out -match 'PUBLISHED \[4\] via POST id=5781348704') 'published with the comment id, not the user id'
$bigObj = Get-Content -LiteralPath $bigState -Raw | ConvertFrom-Json
$bigTask = $bigObj.tasks.PSObject.Properties['4'].Value
Assert ([string]$bigTask.state -eq 'PUBLISHED') 'task 4 state=PUBLISHED'
Assert ([string]$bigTask.comment_id -eq '5781348704') "comment_id stored in full (actual=$($bigTask.comment_id))"
Assert (-not (Test-Path -LiteralPath (Join-Path $bigOut '4.json'))) 'outbox 4.json removed'
$log1 = Get-Content -LiteralPath $env:FAKE_GH_LOG -Raw
$postCount = ([regex]::Matches($log1, '-X POST')).Count
$patchCount = ([regex]::Matches($log1, '-X PATCH')).Count
Assert ($postCount -eq 1) "exactly one POST (actual=$postCount)"
Assert ($patchCount -eq 0) 'first publish does not PATCH'
[System.IO.File]::WriteAllText((Join-Path $bigOut '4.json'), $outJson, $utf8)
$r = Invoke-Bridge -ArenaRoot $bigRoot
Assert ($r.Code -eq 0) 'republish exit 0'
if ($r.Out -match 'PUBLISH RETRY') { throw "ASSERT FAILED: republish does not retry: $($r.Out)" }; Write-Host '  ok: republish does not retry'
Assert ($r.Out -match 'PUBLISHED \[4\] via PATCH id=5781348704') 'republish updates the existing comment'
$log2 = Get-Content -LiteralPath $env:FAKE_GH_LOG -Raw
$postCount = ([regex]::Matches($log2, '-X POST')).Count
$patchCount = ([regex]::Matches($log2, '-X PATCH')).Count
Assert ($postCount -eq 1) "still exactly one POST (actual=$postCount)"
Assert ($patchCount -eq 1) "exactly one PATCH (actual=$patchCount)"
Assert (-not (Test-Path -LiteralPath (Join-Path $bigOut '4.json'))) 'outbox removed after PATCH'
Remove-Item Env:FAKE_GH_POST_FILE -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_GET_FILE -ErrorAction SilentlyContinue

Write-Host ''
Write-Host 'ALL SMOKE TESTS PASSED'
Write-Host "sandbox left at: $tmp"
