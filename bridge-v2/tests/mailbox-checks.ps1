# mailbox-checks.ps1 — remote intake checks. Dot-sourced by smoke-test.ps1.
# No network. No live bridge. Same fake git/gh style as the rest of the suite.

if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $Global:PSNativeCommandUseErrorActionPreference = $false
}

$utf8 = New-Object System.Text.UTF8Encoding $false
$mailRepo = 'dvikt33-ux/arena-bridge-mailbox'
$mailDir = Join-Path $tmp 'mailbox-fixtures'
New-Item -ItemType Directory -Path $mailDir -Force | Out-Null
$env:FAKE_MAILBOX_DIR = $mailDir
$env:FAKE_GIT_LOG = Join-Path $tmp 'git-mail.log'
$env:FAKE_GH_LOG = Join-Path $tmp 'gh-mail.log'
$env:FAKE_PS_EXE = $runner
$env:FAKE_GH_PS1 = Join-Path $here 'fake-gh.ps1'
Remove-Item Env:FAKE_GH_FAIL -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_SLEEP_SEC -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_POST_FILE -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_GET_FILE -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_SEEN -ErrorAction SilentlyContinue
Remove-Item Env:ARENA_MAILBOX_GH_TIMEOUT_MS -ErrorAction SilentlyContinue

$mailShim = Join-Path $tmp 'mailshims'
New-Item -ItemType Directory -Path $mailShim -Force | Out-Null
if ($isWin) {
    $cmd = "@echo off`r`n""%FAKE_PS_EXE%"" -NoProfile -File ""%FAKE_GH_PS1%"" %*`r`nexit /b %ERRORLEVEL%`r`n"
    [System.IO.File]::WriteAllText((Join-Path $mailShim 'gh.cmd'), $cmd, [System.Text.Encoding]::ASCII)
}
else {
    $sh = "#!/bin/sh`nexec `"`$FAKE_PS_EXE`" -NoProfile -File `"`$FAKE_GH_PS1`" `"`$@`"`n"
    $ghWrap = Join-Path $mailShim 'gh'
    [System.IO.File]::WriteAllText($ghWrap, $sh)
    & chmod +x $ghWrap
}
$env:PATH = $mailShim + [System.IO.Path]::PathSeparator + $env:PATH

function Write-Utf8 {
    param([string]$Path, [string]$Text)
    $dir = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($dir) -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Text, $utf8)
}

function Reset-Logs {
    foreach ($f in @($env:FAKE_GIT_LOG, $env:FAKE_GH_LOG)) {
        if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force }
    }
}

function Read-Log {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    return [System.IO.File]::ReadAllText($Path)
}

function Set-MailConfig {
    param([string]$Path, [bool]$Enabled, [string]$Repo)
    $flag = 'false'
    if ($Enabled) { $flag = 'true' }
    Write-Utf8 $Path ('{"enabled":' + $flag + ',"repo":"' + $Repo + '","owner":"dvikt33-ux","poll_sec":15}')
    $env:ARENA_MAILBOX_CONFIG = $Path
}

function Set-RepoFixture {
    param(
        [string]$Dir,
        [bool]$Private,
        [string]$FullName,
        [bool]$Fork = $false,
        [string]$Owner = 'dvikt33-ux'
    )
    $flag = 'false'
    if ($Private) { $flag = 'true' }
    $forkFlag = 'false'
    if ($Fork) { $forkFlag = 'true' }
    $json = '{"full_name":"' + $FullName + '","private":' + $flag + ',"fork":' + $forkFlag + ',"owner":{"login":"' + $Owner + '"}}'
    Write-Utf8 (Join-Path $Dir 'repo.json') $json
}

function Set-RemoteTask {
    param(
        [string]$Dir,
        [int]$Seq,
        [string]$Envelope,
        [string]$Author = 'dvikt33-ux',
        [string]$Committer = 'dvikt33-ux'
    )
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Envelope)
    $b64 = [Convert]::ToBase64String($bytes)
    $content = '{"type":"file","encoding":"base64","size":' + $bytes.Length + ',"path":"inbox/' + $Seq + '.json","sha":"abc","content":"' + $b64 + '"}'
    Write-Utf8 (Join-Path $Dir ("content-$Seq.json")) $content
    $commit = '[{"sha":"c' + $Seq + '","author":{"login":"' + $Author + '","id":1},"committer":{"login":"' + $Committer + '","id":2}}]'
    Write-Utf8 (Join-Path $Dir ("commit-$Seq.json")) $commit
}

function Set-Index {
    param([string]$Dir, [string[]]$Names)
    $items = @()
    foreach ($n in @($Names)) {
        if ([string]::IsNullOrWhiteSpace($n)) { continue }
        $items += '{"name":"' + $n + '","path":"inbox/' + $n + '","type":"file","size":80}'
    }
    $json = '[]'
    if ($items.Count -gt 0) { $json = '[' + ($items -join ',') + ']' }
    Write-Utf8 (Join-Path $Dir 'index.json') $json
}

function New-MailRoot {
    param([int]$LastSeq)
    $dir = Join-Path $tmp ('mail-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $dir 'inbox') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $dir 'outbox') -Force | Out-Null
    Write-Utf8 (Join-Path $dir 'state.json') ('{"last_seq":' + $LastSeq + ',"tasks":{}}')
    return $dir
}

function New-Envelope {
    param([int]$Seq, [string]$Action, [string]$TaskId, [int]$CreatedOffsetMin = -1, [int]$ExpiresOffsetMin = 120)
    $created = (Get-Date).ToUniversalTime().AddMinutes($CreatedOffsetMin).ToString('yyyy-MM-ddTHH:mm:ssZ')
    $expires = (Get-Date).ToUniversalTime().AddMinutes($ExpiresOffsetMin).ToString('yyyy-MM-ddTHH:mm:ssZ')
    return '{"schema":1,"seq":' + $Seq + ',"task_id":"' + $TaskId.ToLowerInvariant() + '","action":"' + $Action + '","args":{},"created_at":"' + $created + '","expires_at":"' + $expires + '"}'
}

function Get-MailState {
    param([string]$Root)
    return (Get-Content -LiteralPath (Join-Path $Root 'state.json') -Raw | ConvertFrom-Json)
}

$cfg = Join-Path $tmp 'mailbox.json'
Set-MailConfig $cfg $true $mailRepo
Set-RepoFixture $mailDir $true $mailRepo

Write-Host '[14] trusted mailbox task auto-runs, no prompt'
$box = New-MailRoot 12
$task13 = '11111111-1111-1111-1111-111111111111'
$env13 = New-Envelope 13 'GIT_STATUS' $task13
Set-RemoteTask $mailDir 13 $env13
Set-Index $mailDir @('13.json', 'evil.ps1')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
if ($r.Code -ne 0) { throw "ASSERT FAILED: mailbox run exit 0 (actual=$($r.Code)) out=$($r.Out)" }
Write-Host '  ok: mailbox run exit 0'
Assert ($r.Out -match 'MAILBOX accepted \[13\] GIT_STATUS') 'accepted the trusted task'
Assert ($r.Out -match 'COMPLETED \[13\]: GIT_STATUS') 'executed GIT_STATUS'
Assert ($r.Out -notmatch 'Read-Host') 'no PowerShell prompt'
$st = Get-MailState $box
Assert ([int]$st.last_seq -eq 13) 'seq continued from 12 to 13, not restarted'
$res13 = Get-Content -LiteralPath (Join-Path $box 'results/result-13.txt') -Raw
Assert ($res13 -match 'On branch fake') 'result is the fixed git status'
Assert (Test-Path -LiteralPath (Join-Path $box 'outbox/13.json')) 'outbox kept for later publish'
$gitLog = Read-Log $env:FAKE_GIT_LOG
Assert ($gitLog -match 'status') 'git status ran once for the accepted task'
Assert ($gitLog -notmatch 'evil') 'a non-json mailbox file was not executed'

Write-Host '[15] unknown action is not executed'
Reset-Logs
$badAction = New-Envelope 14 'NOT_A_COMMAND' '22222222-2222-2222-2222-222222222222'
Set-RemoteTask $mailDir 14 $badAction
Set-Index $mailDir @('13.json', '14.json')
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ($r.Out -match 'MAILBOX rejected \[14\] unknown-action') 'unknown action rejected'
Assert ([int](Get-MailState $box).last_seq -eq 13) 'unknown action did not advance seq'
Assert ((Read-Log $env:FAKE_GIT_LOG) -notmatch 'status') 'unknown action did not run git'

Write-Host '[16] spoofed author login does not authorize when a writer is extra'
Reset-Logs
$forged = New-Envelope 14 'GIT_STATUS' '33333333-3333-3333-3333-333333333333'
Set-RemoteTask $mailDir 14 $forged 'dvikt33-ux' 'dvikt33-ux'
$extra = '[{"login":"dvikt33-ux","permissions":{"admin":true,"maintain":true,"push":true,"triage":true,"pull":true}},{"login":"attacker","permissions":{"admin":false,"maintain":false,"push":true,"triage":false,"pull":true}}]'
Write-Utf8 (Join-Path $mailDir 'collaborators.json') $extra
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Remove-Item -LiteralPath (Join-Path $mailDir 'collaborators.json') -Force -ErrorAction SilentlyContinue
Assert ($r.Out -match 'MAILBOX refused extra-writer') 'extra writer refused'
Assert ($r.Out -notmatch 'MAILBOX accepted') 'spoofed source did not accept a task'
Assert ([int](Get-MailState $box).last_seq -eq 13) 'spoofed source did not run'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'spoofed source did not run git'

Write-Host '[16b] a deploy key is not authorization'
Reset-Logs
$bot = New-Envelope 14 'GIT_STATUS' '44444444-4444-4444-4444-444444444444'
Set-RemoteTask $mailDir 14 $bot 'dvikt33-ux' 'dvikt33-ux'
Write-Utf8 (Join-Path $mailDir 'keys.json') '[{"id":1,"key":"ssh-ed25519 AAAA","read_only":true}]'
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Remove-Item -LiteralPath (Join-Path $mailDir 'keys.json') -Force -ErrorAction SilentlyContinue
Assert ($r.Out -match 'MAILBOX refused deploy-key') 'deploy key refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'deploy key did not run git'
Assert ([int](Get-MailState $box).last_seq -eq 13) 'deploy key did not advance seq'

Write-Host '[21] bad args are not a shell command'
Reset-Logs
$created = (Get-Date).ToUniversalTime().AddMinutes(-1).ToString('yyyy-MM-ddTHH:mm:ssZ')
$expires = (Get-Date).ToUniversalTime().AddMinutes(60).ToString('yyyy-MM-ddTHH:mm:ssZ')
$argsEnv = '{"schema":1,"seq":14,"task_id":"55555555-5555-5555-5555-555555555555","action":"GIT_STATUS","args":{"command":"calc.exe"},"created_at":"' + $created + '","expires_at":"' + $expires + '"}'
Set-RemoteTask $mailDir 14 $argsEnv
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ($r.Out -match 'MAILBOX rejected \[14\] bad-args') 'args rejected'
Assert ($r.Out -notmatch 'calc') 'rejected args are not printed'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'bad args did not run git'
$audit = Get-Content -LiteralPath (Join-Path $box ('audit-' + (Get-Date -Format 'yyyy-MM-dd') + '.jsonl')) -Raw
Assert ($audit -notmatch 'calc') 'audit does not contain the rejected arg'

Write-Host '[22] unknown field and shell text are not executed'
Reset-Logs
$shellEnv = '{"schema":1,"seq":14,"task_id":"66666666-6666-6666-6666-666666666666","action":"GIT_STATUS","args":{},"shell":"powershell -Command calc","created_at":"' + $created + '","expires_at":"' + $expires + '"}'
Set-RemoteTask $mailDir 14 $shellEnv
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ($r.Out -match 'unknown-field') 'unknown field rejected'
Assert ($r.Out -notmatch 'powershell') 'shell text is not printed'
$sneaky = New-Envelope 14 'GIT_STATUS;calc' '77777777-7777-7777-7777-777777777777'
Set-RemoteTask $mailDir 14 $sneaky
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ($r.Out -match 'unknown-action') 'action text with a separator is rejected'
Assert ([int](Get-MailState $box).last_seq -eq 13) 'shell-looking action did not run'

Write-Host '[20] corrupt JSON is not executed'
Reset-Logs
$badBytes = [System.Text.Encoding]::UTF8.GetBytes('{')
$badB64 = [Convert]::ToBase64String($badBytes)
Write-Utf8 (Join-Path $mailDir 'content-14.json') ('{"type":"file","encoding":"base64","size":1,"path":"inbox/14.json","sha":"bad","content":"' + $badB64 + '"}')
Write-Utf8 (Join-Path $mailDir 'commit-14.json') '[{"sha":"bad","author":{"login":"dvikt33-ux","id":1},"committer":{"login":"dvikt33-ux","id":2}}]'
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ($r.Out -match 'bad-json') 'corrupt JSON rejected'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'corrupt JSON did not run git'

Write-Host '[31] expired task is not executed'
Reset-Logs
$expired = New-Envelope 14 'GIT_STATUS' '88888888-8888-8888-8888-888888888888' -120 -1
Set-RemoteTask $mailDir 14 $expired
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ($r.Out -match 'expired') 'expired task rejected'

Write-Host '[17] replay of the same task_id is not executed'
$replayRoot = New-MailRoot 12
$replayEnv = New-Envelope 13 'GIT_STATUS' $task13
Set-RemoteTask $mailDir 13 $replayEnv
Set-Index $mailDir @('13.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $replayRoot
Assert ($r.Out -match 'COMPLETED \[13\]: GIT_STATUS') 'replay setup executed once'
$replay2 = New-Envelope 14 'GIT_STATUS' $task13
Set-RemoteTask $mailDir 14 $replay2
Set-Index $mailDir @('13.json', '14.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $replayRoot
Assert ($r.Out -match 'duplicate-task') 'same task_id rejected'
Assert ([int](Get-MailState $replayRoot).last_seq -eq 13) 'replay did not advance seq'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'replay did not run git'

Write-Host '[18] old seq is not executed again'
Reset-Logs
Set-Index $mailDir @('13.json')
$r = Invoke-Bridge -NoGithub -ArenaRoot $box
Assert ([int](Get-MailState $box).last_seq -eq 13) 'old seq left last_seq unchanged'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'old seq did not run git again'

Write-Host '[19] a rejected remote task does not block the next valid task'
$gapRoot = New-MailRoot 12
$badId = '99999999-9999-9999-9999-999999999999'
$goodId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
$created19 = (Get-Date).ToUniversalTime().AddMinutes(-1).ToString('yyyy-MM-ddTHH:mm:ssZ')
$expires19 = (Get-Date).ToUniversalTime().AddMinutes(60).ToString('yyyy-MM-ddTHH:mm:ssZ')
$bad19 = '{"schema":1,"seq":14,"task_id":"' + $badId + '","action":"GIT_STATUS","args":{},"author":"dvikt33-ux","shell":"powershell -Command calc","created_at":"' + $created19 + '","expires_at":"' + $expires19 + '"}'
$good19 = New-Envelope 15 'GIT_VERSION' $goodId
Set-RemoteTask $mailDir 14 $bad19
Set-RemoteTask $mailDir 15 $good19
Set-Index $mailDir @('14.json', '15.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $gapRoot
Assert ($r.Out -match 'MAILBOX rejected \[14\] unknown-field') 'bad remote seq rejected'
Assert ($r.Out -notmatch 'powershell') 'shell text is not printed'
Assert ($r.Out -notmatch 'calc') 'shell payload is not printed'
Assert ($r.Out -match 'COMPLETED \[13\]: GIT_VERSION') 'valid next remote task executed'
Assert ([int](Get-MailState $gapRoot).last_seq -eq 13) 'queue advanced only for the valid task'
$gapGit = Read-Log $env:FAKE_GIT_LOG
Assert ($gapGit -match '--version') 'valid action ran'
Assert ($gapGit -notmatch 'status') 'rejected task did not run git status'
$gapSeen = (Get-MailState $gapRoot).mailbox.seen.PSObject.Properties[$badId].Value
Assert ([string]$gapSeen.disposition -eq 'rejected') 'rejected task is terminal'
Assert ([string]$gapSeen.reason -eq 'unknown-field') 'rejected reason recorded'
$gapAuditPath = Join-Path $gapRoot ('audit-' + (Get-Date -Format 'yyyy-MM-dd') + '.jsonl')
$gapAudit = ''
if (Test-Path -LiteralPath $gapAuditPath) { $gapAudit = [System.IO.File]::ReadAllText($gapAuditPath) }
Assert ($gapAudit -notmatch 'calc') 'audit does not contain the shell payload'
Assert ($gapAudit -notmatch 'powershell') 'audit does not contain the shell text'

Write-Host '[19b] replay of a rejected task does not change the result'
$mutated = New-Envelope 14 'GIT_STATUS' $badId
Set-RemoteTask $mailDir 14 $mutated
Set-Index $mailDir @('14.json', '15.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $gapRoot
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'replay did not run git'
Assert ([int](Get-MailState $gapRoot).last_seq -eq 13) 'replay did not advance seq'
$gapSeen2 = (Get-MailState $gapRoot).mailbox.seen.PSObject.Properties[$badId].Value
Assert ([string]$gapSeen2.reason -eq 'unknown-field') 'replay did not change the reason'
Assert ([string]$gapSeen2.disposition -eq 'rejected') 'replay stayed rejected'
Set-Index $mailDir @('13.json')

Write-Host '[24] publish after execution does not run the action again'
Reset-Logs
$before = Read-Log $env:FAKE_GIT_LOG
$r = Invoke-Bridge -ArenaRoot $box
Assert ($r.Code -eq 0) 'republish exit 0'
Assert ($r.Out -match 'PUBLISHED \[13\]') 'pending result was published'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq $before) 'publish did not run git'
$pub = Get-MailState $box
Assert ([string]$pub.tasks.'13'.state -eq 'PUBLISHED') 'task 13 published'
Reset-Logs
$r = Invoke-Bridge -ArenaRoot $box
Assert ($r.Out -notmatch 'PUBLISH RETRY') 'second delivery did not retry a new post blindly'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'second delivery did not run git'

Write-Host '[25] GitHub down does not execute; recovery executes once'
$down = New-MailRoot 20
$env21 = New-Envelope 21 'GIT_STATUS' 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
Set-RemoteTask $mailDir 21 $env21
Set-Index $mailDir @('21.json')
$env:FAKE_GH_FAIL = '1'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $down
Remove-Item Env:FAKE_GH_FAIL -ErrorAction SilentlyContinue
Assert ($r.Out -match 'mailbox-unavailable') 'GitHub failure is reported'
Assert ([int](Get-MailState $down).last_seq -eq 20) 'unavailable GitHub did not execute'
$ghLines = @(Read-Log $env:FAKE_GH_LOG -split "`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
Assert ($ghLines.Count -eq 1) "unavailable GitHub was not polled in a loop (calls=$($ghLines.Count))"
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $down
Assert ($r.Out -match 'COMPLETED \[21\]: GIT_STATUS') 'task ran after GitHub returned'
$ran = Read-Log $env:FAKE_GIT_LOG
Assert ($ran -match 'status') 'git ran after recovery'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $down
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'recovered task was not executed again'

Write-Host '[26] a public issue comment is not a command'
$quiet = New-MailRoot 30
Set-Index $mailDir @()
$commentFile = Join-Path $tmp 'issue-command.json'
Write-Utf8 $commentFile '[{"id":1,"user":{"login":"attacker","id":2},"body":"GIT_STATUS calc.exe"}]'
$env:FAKE_GH_GET_FILE = $commentFile
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $quiet
Remove-Item Env:FAKE_GH_GET_FILE -ErrorAction SilentlyContinue
Assert ([int](Get-MailState $quiet).last_seq -eq 30) 'issue text did not create a task'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'issue text did not run git'
Assert ($r.Out -notmatch 'calc') 'issue text was not echoed as a command'

Write-Host '[27] a public mailbox repo is refused'
Set-RepoFixture $mailDir $false $mailRepo
Set-Index $mailDir @('21.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $quiet
Assert ($r.Out -match 'MAILBOX refused not-private') 'public repo refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'public repo did not run git'
Set-RepoFixture $mailDir $true $mailRepo

Write-Host '[28] the public project repo cannot be the mailbox'
$blockedCfg = Join-Path $tmp 'mailbox-blocked.json'
Set-MailConfig $blockedCfg $true 'dvikt33-ux/arena-archicad-project'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $quiet
Assert ($r.Out -match 'Mailbox:  disabled') 'results repo is not a command source'
Assert ((Read-Log $env:FAKE_GH_LOG) -eq '') 'blocked config did not call gh'
Set-MailConfig $cfg $true $mailRepo

Write-Host '[32] an unprocessed local task is not overwritten'
$keep = New-MailRoot 40
$local = '{"seq":41,"action":"GIT_VERSION","ts":"2026-09-22T12:00:00Z","request":"local"}'
Write-Utf8 (Join-Path $keep 'inbox/41.json') $local
$remote41 = New-Envelope 41 'GIT_STATUS' 'cccccccc-cccc-cccc-cccc-cccccccccccc'
Set-RemoteTask $mailDir 41 $remote41
Set-Index $mailDir @('41.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $keep
Assert ($r.Out -match 'COMPLETED \[41\]: GIT_VERSION') 'local task kept its action'
$res41 = Get-Content -LiteralPath (Join-Path $keep 'results/result-41.txt') -Raw
Assert ($res41 -match 'git version') 'local task output was not replaced'
Assert ($res41 -notmatch 'On branch fake') 'remote status did not overwrite the local file'

Write-Host '[23] crash after receive and before execution runs once'
$crash = New-MailRoot 50
$crashId = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
$crashEnv = New-Envelope 51 'GIT_STATUS' $crashId
Write-Utf8 (Join-Path $crash 'inbox/51.json') $crashEnv
$crashState = '{"last_seq":50,"tasks":{},"mailbox":{"seen":{"' + $crashId + '":{"seq":51,"disposition":"accepted","reason":""}},"rejected_seqs":[]}}'
Write-Utf8 (Join-Path $crash 'state.json') $crashState
Set-RemoteTask $mailDir 51 $crashEnv
Set-Index $mailDir @('51.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $crash
Assert ($r.Out -match 'COMPLETED \[51\]: GIT_STATUS') 'received task ran after restart'
Assert ((Read-Log $env:FAKE_GIT_LOG) -match 'status') 'restart executed git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $crash
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'restart did not execute the task again'

Write-Host '[23b] crash during RUNNING is not executed again'
$mid = New-MailRoot 60
$midId = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
$midEnv = New-Envelope 61 'GIT_STATUS' $midId
Write-Utf8 (Join-Path $mid 'inbox/61.json') $midEnv
$midState = '{"last_seq":60,"tasks":{"61":{"action":"GIT_STATUS","state":"RUNNING","pid":9,"started":"2026-09-22T12:00:00Z"}},"mailbox":{"seen":{"' + $midId + '":{"seq":61,"disposition":"accepted","reason":""}},"rejected_seqs":[]}}'
Write-Utf8 (Join-Path $mid 'state.json') $midState
Set-RemoteTask $mailDir 61 $midEnv
Set-Index $mailDir @('61.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $mid
$midResPath = Join-Path (Join-Path $mid 'results') 'result-61.txt'
if (-not (Test-Path -LiteralPath $midResPath)) { throw "ASSERT FAILED: no recovery result out=$($r.Out)" }
$midRes = Get-Content -LiteralPath $midResPath -Raw
Assert ($midRes -match 'recovered') 'RUNNING crash was recovered'
$midObj = Get-MailState $mid
Assert ([int]$midObj.last_seq -eq 61) 'recovered seq was consumed'
Assert ([string]$midObj.tasks.'61'.status -eq 'FAILED') 'recovered task is FAILED'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'recovered task did not run git'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $mid
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'second start still did not run it'

Write-Host '[33] GIT_DIFF from the mailbox stays local-only'
$diffRoot = New-MailRoot 70
$diffEnv = New-Envelope 71 'GIT_DIFF' 'ffffffff-ffff-ffff-ffff-ffffffffffff'
Set-RemoteTask $mailDir 71 $diffEnv
Set-Index $mailDir @('71.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $diffRoot
Assert ($r.Out -match 'COMPLETED \[71\]: GIT_DIFF') 'GIT_DIFF ran'
$diffOut = Get-Content -LiteralPath (Join-Path $diffRoot 'outbox/71.json') -Raw | ConvertFrom-Json
Assert ($diffOut.public -eq $false) 'GIT_DIFF remains private'
Assert ($diffOut.public_body -match 'local-only') 'GIT_DIFF body omits the diff'
Assert ($diffOut.public_body -notmatch 'fake-diff-line') 'diff text is not in the public body'

Write-Host '[34] a hung gh does not block the bridge or run a task'
$hung = New-MailRoot 80
$hungEnv = New-Envelope 81 'GIT_STATUS' '12121212-1212-1212-1212-121212121212'
Set-RemoteTask $mailDir 81 $hungEnv
Set-Index $mailDir @('81.json')
$env:FAKE_GH_SLEEP_SEC = '8'
$env:ARENA_MAILBOX_GH_TIMEOUT_MS = '1500'
Reset-Logs
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$r = Invoke-Bridge -NoGithub -ArenaRoot $hung
$sw.Stop()
Remove-Item Env:FAKE_GH_SLEEP_SEC -ErrorAction SilentlyContinue
Remove-Item Env:ARENA_MAILBOX_GH_TIMEOUT_MS -ErrorAction SilentlyContinue
Assert ($sw.Elapsed.TotalSeconds -lt 6) "hung gh returned in $($sw.Elapsed.TotalSeconds)s"
Assert ($r.Out -match 'mailbox-timeout') 'timeout is reported'
Assert ([int](Get-MailState $hung).last_seq -eq 80) 'timed-out poll did not execute'

Write-Host '[37] a bad mailbox config does not block a local task'
$localRoot = New-MailRoot 0
Write-Utf8 (Join-Path $localRoot 'inbox/1.json') '{"seq":1,"action":"GIT_STATUS","ts":"2026-09-22T12:00:00Z","request":"local"}'
$badCfg = Join-Path $tmp 'mailbox-bad.json'
Write-Utf8 $badCfg 'this is not json'
$env:ARENA_MAILBOX_CONFIG = $badCfg
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $localRoot
Assert ($r.Out -match 'COMPLETED \[1\]: GIT_STATUS') 'local inbox still runs when mailbox config is bad'
Assert ($r.Out -match 'Mailbox:  disabled') 'bad config fails closed'
Set-MailConfig $cfg $false $mailRepo

Write-Host '[29] critical actions are held; current actions are not'
. (Join-Path $root 'arena-common.ps1')
. (Join-Path $root 'actions.ps1')
. (Join-Path $root 'mailbox.ps1')
$policy = Get-ActionPolicyFromTable
foreach ($id in @($script:ActionIds)) {
    Assert (-not [bool]$policy[$id].Critical) "$id auto-runs"
}
$now = [datetime]::UtcNow
$live = $env13 | ConvertFrom-Json
$decision = Get-RemoteDecision $live $policy $now $env13
Assert ($decision.Ok -and -not $decision.Hold) 'current GIT_STATUS is not held'
$criticalPolicy = @{ GIT_STATUS = @{ Critical = $true; ArgNames = @() } }
$heldDecision = Get-RemoteDecision $live $criticalPolicy $now $env13
Assert ($heldDecision.Ok -and $heldDecision.Hold) 'critical policy holds without a prompt'
Assert (Resolve-MailboxHold $true $false) 'unapproved critical stays held'
Assert (-not (Resolve-MailboxHold $true $true)) 'approved critical can be released'
Assert (-not (Resolve-MailboxHold $false $false)) 'non-critical is never held'
$approveDir = Join-Path $tmp 'approve-unit'
New-Item -ItemType Directory -Path $approveDir -Force | Out-Null
Assert (-not (Test-MailboxApproved $task13 $approveDir)) 'missing approve file does not approve'
Write-Utf8 (Join-Path $approveDir $task13) 'not-the-id'
Assert (-not (Test-MailboxApproved $task13 $approveDir)) 'wrong approve text does not approve'
Write-Utf8 (Join-Path $approveDir $task13) $task13
Assert (Test-MailboxApproved $task13 $approveDir) 'exact approve file releases a critical task'

Write-Host '[30] producer accepts an action id and refuses a shell string'
$put = Join-Path $root 'arena-mailbox-put.ps1'
$prod = New-MailRoot 12
Write-Utf8 (Join-Path $prod 'inbox/14.json') '{"seq":14,"action":"GIT_STATUS"}'
$putOut = & $runner -NoProfile -File $put -Action 'GIT_STATUS' -DryRun -ArenaRoot $prod 2>&1
$putCode = $LASTEXITCODE
$putText = @($putOut | ForEach-Object { "$_" }) -join "`n"
Assert ($putCode -eq 0) "producer dry-run exit 0 (actual=$putCode text=$putText)"
Assert ($putText -match 'MAILBOX_QUEUED seq=15 ') 'producer continued numbering and did not overwrite seq 14'
$staged = Get-Content -LiteralPath (Join-Path $prod 'mailbox-staging/15.json') -Raw | ConvertFrom-Json
Assert ([string]$staged.action -eq 'GIT_STATUS') 'staged action is the allowlist id'
Assert (@($staged.args.PSObject.Properties).Count -eq 0) 'staged args are empty'
Reset-Logs
$denyOut = & $runner -NoProfile -File $put -Action 'powershell -Command calc' -DryRun -ArenaRoot $prod 2>&1
$denyCode = $LASTEXITCODE
Assert ($denyCode -eq 3) "producer refuses a shell string (actual=$denyCode)"
Assert ((Read-Log $env:FAKE_GH_LOG) -eq '') 'refused producer did not call gh'
$pushOut = & $runner -NoProfile -File $put -Action 'GIT_STATUS' -Push -MailboxRepo 'dvikt33-ux/arena-archicad-project' -ArenaRoot $prod -Seq 16 2>&1
$pushCode = $LASTEXITCODE
Assert ($pushCode -eq 9) "producer refuses the public project repo (actual=$pushCode)"
Assert ((Read-Log $env:FAKE_GH_LOG) -eq '') 'refused push did not call gh'

Write-Host '[35] bridge scripts do not invoke a remote command string'
$names = @('arena-bridge-v2.ps1', 'arena-common.ps1', 'actions.ps1', 'mailbox.ps1', 'arena-mailbox-put.ps1', 'arena-qwen-router-v2.ps1')
foreach ($name in $names) {
    $text = [System.IO.File]::ReadAllText((Join-Path $root $name))
    if ($text -match 'Invoke-Expression') { throw "ASSERT FAILED: Invoke-Expression in $name" }
    if ($text -match 'powershell(\.exe)?\s+-Command') { throw "ASSERT FAILED: powershell -Command in $name" }
}
Write-Host '  ok: no remote command execution in scripts'


Write-Host '[36] commit author is not the allow decision'
Set-MailConfig $cfg $true $mailRepo
Set-RepoFixture $mailDir $true $mailRepo
Remove-Item -LiteralPath (Join-Path $mailDir 'collaborators.json') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $mailDir 'keys.json') -Force -ErrorAction SilentlyContinue
$authorRoot = New-MailRoot 90
$authorEnv = New-Envelope 91 'GIT_STATUS' 'abababab-abab-abab-abab-abababababab'
Set-RemoteTask $mailDir 91 $authorEnv 'attacker' 'attacker'
Set-Index $mailDir @('91.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $authorRoot
Assert ($r.Out -match 'COMPLETED \[91\]: GIT_STATUS') 'clean permissions run the task even if commit author is spoofed'
Assert ((Read-Log $env:FAKE_GIT_LOG) -match 'status') 'git ran without consulting commit author'

Write-Host '[41] unreadable collaborators refuse the poll'
$unread = New-MailRoot 12
$env41 = New-Envelope 13 'GIT_STATUS' 'cdcdcdcd-cdcd-cdcd-cdcd-cdcdcdcdcdcd'
Set-RemoteTask $mailDir 13 $env41
Set-Index $mailDir @('13.json')
$env:FAKE_GH_COLLAB_FAIL = '1'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $unread
Remove-Item Env:FAKE_GH_COLLAB_FAIL -ErrorAction SilentlyContinue
Assert ($r.Out -match 'MAILBOX refused collaborators-unreadable') 'unreadable collaborators refuse'
Assert ([int](Get-MailState $unread).last_seq -eq 12) 'unreadable collaborators did not execute'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'unreadable collaborators did not run git'

Write-Host '[44] unreadable deploy keys refuse the poll'
$env:FAKE_GH_KEYS_FAIL = '1'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $unread
Remove-Item Env:FAKE_GH_KEYS_FAIL -ErrorAction SilentlyContinue
Assert ($r.Out -match 'MAILBOX refused keys-unreadable') 'unreadable keys refuse'
Assert ([int](Get-MailState $unread).last_seq -eq 12) 'unreadable keys did not execute'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'unreadable keys did not run git'

Write-Host '[43] a fork is not a mailbox'
Set-RepoFixture $mailDir $true $mailRepo -Fork $true
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $unread
Set-RepoFixture $mailDir $true $mailRepo
Assert ($r.Out -match 'MAILBOX refused fork') 'fork refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'fork did not run git'

Write-Host '[46] owner must be the expected account'
Set-RepoFixture $mailDir $true $mailRepo -Owner 'attacker'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $unread
Set-RepoFixture $mailDir $true $mailRepo
Assert ($r.Out -match 'MAILBOX refused owner-mismatch') 'wrong owner refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'wrong owner did not run git'

Write-Host '[47] a missing fork field fails closed'
Write-Utf8 (Join-Path $mailDir 'repo.json') ('{"full_name":"' + $mailRepo + '","private":true,"owner":{"login":"dvikt33-ux"}}')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $unread
Set-RepoFixture $mailDir $true $mailRepo
Assert ($r.Out -match 'MAILBOX refused fork-unknown') 'missing fork field refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'missing fork field did not run git'

Write-Host '[45] a pull-only collaborator is not an extra writer'
$pull = '[{"login":"dvikt33-ux","permissions":{"admin":true,"maintain":true,"push":true,"triage":true,"pull":true}},{"login":"reviewer","permissions":{"admin":false,"maintain":false,"push":false,"triage":true,"pull":true}}]'
Write-Utf8 (Join-Path $mailDir 'collaborators.json') $pull
$pullRoot = New-MailRoot 92
$pullEnv = New-Envelope 93 'GIT_VERSION' 'bcbcbcbc-bcbc-bcbc-bcbc-bcbcbcbcbcbc'
Set-RemoteTask $mailDir 93 $pullEnv
Set-Index $mailDir @('93.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $pullRoot
Remove-Item -LiteralPath (Join-Path $mailDir 'collaborators.json') -Force -ErrorAction SilentlyContinue
Assert ($r.Out -match 'COMPLETED \[93\]: GIT_VERSION') 'pull-only collaborator does not block the owner'
Assert ((Read-Log $env:FAKE_GIT_LOG) -match '--version') 'pull-only case still ran the allowlisted action'

Write-Host '[38] two producers cannot take the same seq'
Set-MailConfig $cfg $false $mailRepo
$raceRoot = New-MailRoot 12
$commonPath = Join-Path $root 'arena-common.ps1'
$raceScript = {
    param($CommonPath, $RootDir, $Producer)
    . $CommonPath
    $seq = Reserve-TaskSeq -ArenaRoot $RootDir -ProducerId $Producer
    $dir = Join-Path $RootDir 'inbox'
    $path = Join-Path $dir ($seq.ToString() + '.json')
    $fs = $null
    try {
        $fs = New-Object System.IO.FileStream($path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(('{"seq":' + $seq + ',"producer":"' + $Producer + '"}'))
        $fs.Write($bytes, 0, $bytes.Length)
        $fs.Close()
        $fs = $null
    }
    catch {
        if ($null -ne $fs) { try { $fs.Dispose() } catch { } }
        throw
    }
    Complete-TaskReservation -ArenaRoot $RootDir -Seq $seq
    return $seq
}
$jobA = Start-Job -ScriptBlock $raceScript -ArgumentList $commonPath, $raceRoot, 'prod-a'
$jobB = Start-Job -ScriptBlock $raceScript -ArgumentList $commonPath, $raceRoot, 'prod-b'
Wait-Job -Job $jobA, $jobB -Timeout 60 | Out-Null
if ($jobA.State -ne 'Completed' -or $jobB.State -ne 'Completed') {
    $errA = ''
    $errB = ''
    try { $errA = (Receive-Job $jobA -ErrorAction SilentlyContinue | Out-String) } catch { $errA = "$_" }
    try { $errB = (Receive-Job $jobB -ErrorAction SilentlyContinue | Out-String) } catch { $errB = "$_" }
    throw "ASSERT FAILED: reserve jobs a=$($jobA.State) b=$($jobB.State) ea=$errA eb=$errB"
}
$seqA = [int](Receive-Job $jobA)
$seqB = [int](Receive-Job $jobB)
Remove-Job -Job $jobA, $jobB -Force
Assert ($seqA -ne $seqB) "two producers got different seqs ($seqA,$seqB)"
Assert ($seqA -gt 12 -and $seqB -gt 12) 'reserved seqs continue from last_seq'
$fileA = Get-Content -LiteralPath (Join-Path $raceRoot ("inbox/" + $seqA + ".json")) -Raw
$fileB = Get-Content -LiteralPath (Join-Path $raceRoot ("inbox/" + $seqB + ".json")) -Raw
Assert ($fileA -match 'prod-a' -and $fileB -match 'prod-b') 'each producer wrote only its own seq'
Assert (-not (Test-Path -LiteralPath (Join-Path $raceRoot 'reservations/13.json'))) 'completed reservations do not linger on seq 13'

Write-Host '[39] an expired reservation is not executed and does not block the next task'
$crashRoot = New-MailRoot 12
$crashRes = Join-Path $crashRoot 'reservations'
New-Item -ItemType Directory -Path $crashRes -Force | Out-Null
Write-Utf8 (Join-Path $crashRes '13.json') '{"seq":13,"producer":"crashed","created":"2020-01-01T00:00:00Z"}'
Write-Utf8 (Join-Path $crashRoot 'inbox/14.json') '{"seq":14,"action":"GIT_VERSION","ts":"2026-09-22T12:00:00Z","request":"local"}'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $crashRoot
$crashState = Get-MailState $crashRoot
Assert ([string]$crashState.tasks.'13'.status -eq 'REJECTED') 'abandoned reservation is terminal'
Assert ([string]$crashState.tasks.'13'.reason -eq 'reservation-abandoned') 'abandoned reason'
Assert ([int]$crashState.last_seq -eq 14) 'next task was not blocked'
Assert ((Read-Log $env:FAKE_GIT_LOG) -match '--version') 'next task ran'
Assert ((Read-Log $env:FAKE_GIT_LOG) -notmatch 'status') 'abandoned slot did not run a command'
Assert (-not (Test-Path -LiteralPath (Join-Path $crashRoot 'results/result-13.txt'))) 'abandoned slot has no result body'

Write-Host '[40] a live reservation holds the slot'
$liveRoot = New-MailRoot 12
$liveRes = Join-Path $liveRoot 'reservations'
New-Item -ItemType Directory -Path $liveRes -Force | Out-Null
$liveStamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
Write-Utf8 (Join-Path $liveRes '13.json') ('{"seq":13,"producer":"live","created":"' + $liveStamp + '"}')
Write-Utf8 (Join-Path $liveRoot 'inbox/14.json') '{"seq":14,"action":"GIT_VERSION","ts":"2026-09-22T12:00:00Z","request":"local"}'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $liveRoot
Assert ([int](Get-MailState $liveRoot).last_seq -eq 12) 'live reservation did not skip ahead'
Assert (Test-Path -LiteralPath (Join-Path $liveRoot 'inbox/14.json')) 'later local file still waiting'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'live reservation did not execute the later file'
Assert ($r.Out -notmatch 'reservation-abandoned') 'live reservation was not abandoned'

Write-Host '[42] public GIT_STATUS is a summary; GIT_DIFF stays unpublished'
$pubRoot = New-MailRoot 0
$statusFile = Join-Path $tmp 'dirty-status.txt'
$secret = ('gh' + 'p_') + ('a' * 36)
$statusText = "On branch main`r`nChanges not staged for commit:`r`n`tmodified:   C:\Users\secret\repo\token.txt`r`npassword=hunter2`r`n" + $secret + "`r`n"
Write-Utf8 $statusFile $statusText
$env:FAKE_GIT_STATUS_FILE = $statusFile
Write-Utf8 (Join-Path $pubRoot 'inbox/1.json') '{"seq":1,"action":"GIT_STATUS","ts":"2026-09-22T12:00:00Z","request":"local"}'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $pubRoot
Remove-Item Env:FAKE_GIT_STATUS_FILE -ErrorAction SilentlyContinue
$pubRaw = [System.IO.File]::ReadAllText((Join-Path $pubRoot 'outbox/1.json'))
$pubObj = $pubRaw | ConvertFrom-Json
Assert ($pubObj.public_body -match 'working tree: dirty') 'status public body is a summary'
Assert ($pubObj.public_body -match 'branch: main') 'safe branch name is kept'
Assert ($pubObj.public_body -notmatch 'On branch') 'raw status stdout is not published'
Assert ($pubObj.public_body -notmatch 'C:\\Users') 'absolute path is not published'
Assert ($pubObj.public_body -notmatch 'token\.txt') 'sensitive file name is not published'
Assert ($pubObj.public_body -notmatch 'hunter2') 'secret assignment is not published'
Assert ($pubObj.public_body -notmatch 'password') 'secret assignment label is not published'
Assert ($pubObj.public_body -notmatch ([regex]::Escape($secret))) 'token-shaped text is not published'
Assert ($pubRaw -notmatch 'C:\\\\Users') 'absolute path is not in the outbox file'
$localPub = [System.IO.File]::ReadAllText((Join-Path $pubRoot 'results/result-1.txt'))
Assert ($localPub -match 'token\.txt') 'local result still has the raw status'
Write-Utf8 (Join-Path $pubRoot 'inbox/2.json') '{"seq":2,"action":"GIT_DIFF","ts":"2026-09-22T12:00:00Z","request":"local"}'
$r = Invoke-Bridge -NoGithub -ArenaRoot $pubRoot
$diffObj = Get-Content -LiteralPath (Join-Path $pubRoot 'outbox/2.json') -Raw | ConvertFrom-Json
Assert ($diffObj.public -eq $false) 'GIT_DIFF remains unpublished'
Assert ($diffObj.public_body -match 'local-only') 'GIT_DIFF public body omits the diff'
Assert ($diffObj.public_body -notmatch 'fake-diff-line') 'diff text is not published'
. (Join-Path $root 'arena-common.ps1')
$logSummary = Get-PublicResultText -Mode 'log-summary' -Text ("abc1234 ok subject`n0123abcd see C:\Users\secret\x")
Assert ($logSummary -match 'abc1234 ok subject') 'safe log line can be summarized'
Assert ($logSummary -notmatch 'C:') 'log summary drops a path line'
Assert ($logSummary -notmatch 'secret') 'log summary drops a sensitive name'

Write-Host '[48] producers share the reservation function'
$routerText = [System.IO.File]::ReadAllText((Join-Path $root 'arena-qwen-router-v2.ps1'))
$putText = [System.IO.File]::ReadAllText((Join-Path $root 'arena-mailbox-put.ps1'))
$mailText = [System.IO.File]::ReadAllText((Join-Path $root 'mailbox.ps1'))
Assert ($routerText -match 'Reserve-TaskSeq') 'router reserves a seq'
Assert ($putText -match 'Reserve-TaskSeq') 'mailbox producer reserves a seq'
Assert ($mailText -match 'Reserve-TaskSeq') 'mailbox import reserves a seq'
Assert ($mailText -notmatch 'Test-MailboxTrust') 'commit author is not the allow function'
Assert ($routerText -notmatch 'maxInbox') 'router no longer allocates a seq on its own'

Set-Index $mailDir @()
Set-MailConfig $cfg $false $mailRepo
Remove-Item Env:FAKE_GH_COLLAB_FAIL -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_KEYS_FAIL -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GIT_STATUS_FILE -ErrorAction SilentlyContinue

Remove-Item Env:ARENA_MAILBOX_CONFIG -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_FAIL -ErrorAction SilentlyContinue
Remove-Item Env:FAKE_GH_SLEEP_SEC -ErrorAction SilentlyContinue
