# phase0-checks.ps1 — starvation, seq split, pagination, crash faults.
# Dot-sourced by mailbox-checks.ps1. No network. No live mailbox.

function New-PhaseTaskId {
    param([int]$N)
    $head = '{0:x8}' -f (0x10000000 + $N)
    $tail = '{0:x12}' -f $N
    return ($head + '-1111-2222-3333-' + $tail)
}

function Count-LogLines {
    param([string]$Path, [string]$Pattern)
    $text = Read-Log $Path
    $n = 0
    foreach ($line in ($text -split "`n")) {
        if ($line -match $Pattern) { $n++ }
    }
    return $n
}

function Get-SeenProp {
    param([string]$Root, [string]$TaskId)
    $st = Get-MailState $Root
    if ($null -eq $st.mailbox -or $null -eq $st.mailbox.seen) { return $null }
    $prop = $st.mailbox.seen.PSObject.Properties[$TaskId]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Clear-PhaseEnv {
    foreach ($name in @(
        'ARENA_MAILBOX_FAULT', 'ARENA_MAILBOX_LIST_WARN_AT', 'ARENA_MAILBOX_HOLD_ACTIONS', 'ARENA_MAILBOX_NOW',
        'FAKE_GH_COLLAB_FULL', 'FAKE_GH_COLLAB_ALL_FULL', 'FAKE_GH_COLLAB_PAGE2_FAIL',
        'FAKE_GH_KEYS_FULL', 'FAKE_GH_KEYS_ALL_FULL', 'FAKE_GH_KEYS_PAGE2_FAIL',
        'FAKE_GH_DELETE_FAIL', 'FAKE_GH_FAIL'
    )) {
        Remove-Item -Path ("Env:" + $name) -ErrorAction SilentlyContinue
    }
}

Set-MailConfig $cfg $true $mailRepo
Set-RepoFixture $mailDir $true $mailRepo
Remove-Item -LiteralPath (Join-Path $mailDir 'collaborators.json') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $mailDir 'keys.json') -Force -ErrorAction SilentlyContinue
Clear-PhaseEnv

Write-Host '[49] numeric staging is not an execution slot'
$wedge = New-MailRoot 12
$wedgeStage = Join-Path $wedge 'mailbox-staging'
New-Item -ItemType Directory -Path $wedgeStage -Force | Out-Null
Write-Utf8 (Join-Path $wedgeStage '13.json') '{"seq":13}'
Write-Utf8 (Join-Path $wedgeStage '99.json') '{"seq":99}'
$wedgeSeq = Reserve-TaskSeq -ArenaRoot $wedge -ProducerId 'wedge'
Assert ($wedgeSeq -eq 13) "leftover staging did not consume 13 (actual=$wedgeSeq)"
Complete-TaskReservation -ArenaRoot $wedge -Seq $wedgeSeq
Write-Utf8 (Join-Path $wedge 'inbox/14.json') '{"seq":14,"action":"GIT_VERSION","ts":"2026-09-22T12:00:00Z","request":"local"}'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $wedge
Assert ($r.Out -match 'GAP') 'missing inbox 13 still waits'
Assert ([int](Get-MailState $wedge).last_seq -eq 12) 'staging did not fill the gap'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'later file did not run across the gap'

Write-Host '[50] terminal remote files do not hide a newer task'
$starve = New-MailRoot 0
$starveNames = @()
for ($i = 1; $i -le 25; $i++) {
    $sid = New-PhaseTaskId $i
    Set-RemoteTask $mailDir $i (New-Envelope $i 'GIT_STATUS' $sid)
    $starveNames += ("$i.json")
}
Set-Index $mailDir $starveNames
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $starve
Assert ([int](Get-MailState $starve).last_seq -eq 20) "first poll executed 20 (actual=$((Get-MailState $starve).last_seq))"
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 20) 'first poll ran 20 tasks'
Assert ((Count-LogLines $env:FAKE_GH_LOG '/contents/inbox/21\.json') -eq 0) 'task 21 was outside the new-work window'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $starve
Assert ([int](Get-MailState $starve).last_seq -eq 25) 'second poll found the remaining tasks'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 5) 'second poll ran only the remaining 5'
$fetch1 = 0
foreach ($line in ((Read-Log $env:FAKE_GH_LOG) -split "`n")) {
    if ($line -match '/contents/inbox/1\.json' -and $line -notmatch 'DELETE') { $fetch1++ }
}
Assert ($fetch1 -eq 0) 'settled file 1 was not fetched again'
$id26 = New-PhaseTaskId 26
Set-RemoteTask $mailDir 26 (New-Envelope 26 'GIT_STATUS' $id26)
$starveNames += '26.json'
Set-Index $mailDir $starveNames
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $starve
Assert ($r.Out -match 'COMPLETED \[26\]: GIT_STATUS') 'new task after the old window ran'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'new task ran once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $starve
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'restart did not run it again'
Assert ([int](Get-MailState $starve).last_seq -eq 26) 'restart did not advance seq'

Write-Host '[51] producer remote id is not the execution slot'
$prodRoot = New-MailRoot 12
$prodStage = Join-Path $prodRoot 'mailbox-staging'
New-Item -ItemType Directory -Path $prodStage -Force | Out-Null
Write-Utf8 (Join-Path $prodStage '13.json') '{"seq":13}'
$put = Join-Path $root 'arena-mailbox-put.ps1'
$putOut = & $runner -NoProfile -File $put -Action 'GIT_VERSION' -DryRun -ArenaRoot $prodRoot 2>&1
$putCode = $LASTEXITCODE
$putText = @($putOut | ForEach-Object { "$_" }) -join "`n"
Assert ($putCode -eq 0) "producer exit 0 ($putText)"
$tidMatch = [regex]::Match($putText, 'task_id=([0-9a-f-]{36})')
Assert ($tidMatch.Success) 'producer printed a task id'
$tid = $tidMatch.Groups[1].Value
Assert ($putText -match ('remote=inbox/' + [regex]::Escape($tid) + '\.json')) 'remote name is the task id'
Assert ($putText -notmatch 'seq=') 'producer did not allocate an exec seq'
$stagedPath = Join-Path $prodRoot ("mailbox-staging/" + $tid + ".json")
Assert (Test-Path -LiteralPath $stagedPath) 'staged by task id'
Assert (-not (Test-Path -LiteralPath (Join-Path $prodRoot 'mailbox-staging/15.json'))) 'producer did not write numeric staging'
Assert (-not (Test-Path -LiteralPath (Join-Path $prodRoot 'reservations/13.json'))) 'producer left no reservation'
Set-RemoteNamed $mailDir $tid ([System.IO.File]::ReadAllText($stagedPath))
Set-Index $mailDir @($tid + '.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $prodRoot
Assert ($r.Out -notmatch 'GAP') 'import did not open a gap'
Assert ($r.Out -match 'COMPLETED \[13\]: GIT_VERSION') 'imported as the next local seq'
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 1) 'first imported task ran once'
$putOut2 = & $runner -NoProfile -File $put -Action 'GIT_STATUS' -DryRun -ArenaRoot $prodRoot 2>&1
$putText2 = @($putOut2 | ForEach-Object { "$_" }) -join "`n"
$tid2 = ([regex]::Match($putText2, 'task_id=([0-9a-f-]{36})')).Groups[1].Value
Assert (-not [string]::IsNullOrWhiteSpace($tid2)) 'second producer printed a task id'
$staged2 = Join-Path $prodRoot ("mailbox-staging/" + $tid2 + ".json")
Set-RemoteNamed $mailDir $tid2 ([System.IO.File]::ReadAllText($staged2))
Set-Index $mailDir @(($tid + '.json'), ($tid2 + '.json'))
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $prodRoot
Assert ($r.Out -notmatch 'GAP') 'second producer did not wedge the queue'
Assert ($r.Out -match 'COMPLETED \[14\]: GIT_STATUS') 'second task took the next seq'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'second task ran once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 0) 'first task did not run again'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $prodRoot
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'restart did not run either task'

Write-Host '[52] a truncated listing is not an empty inbox'
$env:ARENA_MAILBOX_LIST_WARN_AT = '3'
$trunc = New-MailRoot 300
$visible = @()
for ($i = 1; $i -le 3; $i++) {
    $vid = New-PhaseTaskId (300 + $i)
    Set-RemoteTask $mailDir (300 + $i) (New-Envelope (300 + $i) 'GIT_VERSION' $vid)
    $visible += ((300 + $i).ToString() + '.json')
}
$hiddenId = New-PhaseTaskId 399
Set-RemoteTask $mailDir 399 (New-Envelope 399 'GIT_STATUS' $hiddenId)
Set-Index $mailDir $visible
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $trunc
Remove-Item Env:ARENA_MAILBOX_LIST_WARN_AT -ErrorAction SilentlyContinue
Assert ($r.Out -match 'MAILBOX inbox-truncated') 'truncated listing is reported'
Assert ($r.Out -match 'COMPLETED \[301\]: GIT_VERSION') 'a visible task still ran'
Assert ($r.Out -notmatch 'GIT_STATUS') 'hidden task was not executed'
$truncState = Get-MailState $trunc
Assert ([int]$truncState.last_seq -eq 303) 'only the three visible tasks advanced seq'
Assert ($null -eq (Get-SeenProp $trunc $hiddenId)) 'hidden task was not accepted'

Write-Host '[53] a writer on collaborator page 2 is refused'
$env:FAKE_GH_COLLAB_FULL = '1'
Write-Utf8 (Join-Path $mailDir 'collaborators-page2.json') '[{"login":"attacker","permissions":{"admin":false,"maintain":false,"push":true,"triage":false,"pull":true}}]'
$pageRoot = New-MailRoot 12
Set-RemoteTask $mailDir 13 (New-Envelope 13 'GIT_STATUS' (New-PhaseTaskId 530))
Set-Index $mailDir @('13.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $pageRoot
Clear-PhaseEnv
Remove-Item -LiteralPath (Join-Path $mailDir 'collaborators-page2.json') -Force -ErrorAction SilentlyContinue
Assert ($r.Out -match 'MAILBOX refused extra-writer') 'page 2 writer refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'page 2 writer did not run git'
$gh53 = Read-Log $env:FAKE_GH_LOG
Assert ($gh53 -match 'per_page=100') 'page size is explicit'
Assert ($gh53 -match '(?:^|[^A-Za-z0-9_])page=2') 'second page was requested'
Assert ($gh53 -notmatch '&') 'gh arguments do not use ampersand'

Write-Host '[54] a failed collaborator page refuses the poll'
$env:FAKE_GH_COLLAB_FULL = '1'
$env:FAKE_GH_COLLAB_PAGE2_FAIL = '1'
$failRoot = New-MailRoot 12
Set-Index $mailDir @('13.json')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $failRoot
Clear-PhaseEnv
Assert ($r.Out -match 'MAILBOX refused collaborators-unreadable') 'failed page is not a complete scan'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'failed page did not run git'
Assert ([int](Get-MailState $failRoot).last_seq -eq 12) 'failed page did not execute'

Write-Host '[55] twenty full collaborator pages refuse the poll'
$env:FAKE_GH_COLLAB_ALL_FULL = '1'
$fullRoot = New-MailRoot 12
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $fullRoot
$gh55 = Read-Log $env:FAKE_GH_LOG
Clear-PhaseEnv
Assert ($r.Out -match 'MAILBOX refused collaborators-unreadable') 'incomplete collaborator scan refused'
Assert ($gh55 -match '(?:^|[^A-Za-z0-9_])page=20') 'scan reached the page cap'
Assert ($gh55 -notmatch '(?:^|[^A-Za-z0-9_])page=21') 'scan did not continue past the cap'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'incomplete scan did not run git'

Write-Host '[56] a failed deploy-key page refuses the poll'
$env:FAKE_GH_KEYS_FULL = '1'
$env:FAKE_GH_KEYS_PAGE2_FAIL = '1'
$keyRoot = New-MailRoot 12
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $keyRoot
Clear-PhaseEnv
Assert ($r.Out -match 'MAILBOX refused keys-unreadable') 'failed key page refused'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'failed key page did not run git'

Write-Host '[57] twenty full deploy-key pages refuse the poll'
$env:FAKE_GH_KEYS_ALL_FULL = '1'
$keyFull = New-MailRoot 12
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $keyFull
$gh57 = Read-Log $env:FAKE_GH_LOG
Clear-PhaseEnv
Assert ($r.Out -match 'MAILBOX refused keys-unreadable') 'incomplete key scan refused'
Assert ($gh57 -match '(?:^|[^A-Za-z0-9_])page=20') 'key scan reached the page cap'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'incomplete key scan did not run git'

Write-Host '[58] a uuid remote name is not the local seq'
$uuid = '12121212-3434-5656-7878-909090909090'
Set-RemoteNamed $mailDir $uuid (New-Envelope 7 'GIT_VERSION' $uuid)
Set-Index $mailDir @($uuid + '.json')
$uuidRoot = New-MailRoot 400
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $uuidRoot
Assert ($r.Out -match 'MAILBOX accepted \[401\] GIT_VERSION') 'local seq is not the remote id'
Assert ($r.Out -match 'COMPLETED \[401\]: GIT_VERSION') 'uuid task executed'
Assert ($r.Out -notmatch 'seq-filename-mismatch') 'uuid name is not compared as a numeric seq'
Assert ([int](Get-MailState $uuidRoot).last_seq -eq 401) 'seq advanced by one'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $uuidRoot
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'uuid task did not run again'
$refetch = 0
foreach ($line in ((Read-Log $env:FAKE_GH_LOG) -split "`n")) {
    if ($line -match [regex]::Escape($uuid) -and $line -match 'contents/inbox/' -and $line -notmatch 'DELETE') { $refetch++ }
}
Assert ($refetch -eq 0) 'settled uuid file was not fetched again'

Write-Host '[59] crash before accept does not execute twice'
$beforeId = '15151515-1515-1515-1515-151515151515'
Set-RemoteNamed $mailDir $beforeId (New-Envelope 1 'GIT_STATUS' $beforeId)
Set-Index $mailDir @($beforeId + '.json')
$beforeRoot = New-MailRoot 500
$env:ARENA_MAILBOX_FAULT = 'before-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $beforeRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:before-accept') 'fault stopped before accept'
Assert ([int](Get-MailState $beforeRoot).last_seq -eq 500) 'before-accept did not advance seq'
Assert ($null -eq (Get-SeenProp $beforeRoot $beforeId)) 'before-accept wrote no disposition'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'before-accept did not run git'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch 'DELETE') 'before-accept did not clean up'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $beforeRoot
Assert ($r.Out -match 'COMPLETED \[501\]: GIT_STATUS') 'restart after before-accept ran once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'restart ran git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $beforeRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'second restart did not run it'

Write-Host '[60] crash after accept and before local write does not execute twice'
$acceptId = '16161616-1616-1616-1616-161616161616'
Set-RemoteNamed $mailDir $acceptId (New-Envelope 1 'GIT_STATUS' $acceptId)
Set-Index $mailDir @($acceptId + '.json')
$acceptRoot = New-MailRoot 600
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $acceptRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'fault stopped after accept'
$acceptSeen = Get-SeenProp $acceptRoot $acceptId
Assert ($null -ne $acceptSeen -and [string]$acceptSeen.disposition -eq 'accepted') 'disposition is durable'
Assert ([int]$acceptSeen.seq -eq 0) 'exec seq was not allocated yet'
Assert (-not (Test-Path -LiteralPath (Join-Path $acceptRoot 'inbox/601.json'))) 'local inbox was not written'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'after-accept did not run git'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch 'DELETE') 'after-accept did not clean up'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $acceptRoot
Assert ($r.Out -match 'COMPLETED \[601\]: GIT_STATUS') 'restart allocated and ran once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'after-accept restart ran git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $acceptRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'second restart did not run it'
Assert ([int](Get-MailState $acceptRoot).last_seq -eq 601) 'second restart did not advance seq'

Write-Host '[61] crash after local write and before cleanup does not execute twice'
$writeId = '17171717-1717-1717-1717-171717171717'
Set-RemoteNamed $mailDir $writeId (New-Envelope 1 'GIT_STATUS' $writeId)
Set-Index $mailDir @($writeId + '.json')
$writeRoot = New-MailRoot 700
$env:ARENA_MAILBOX_FAULT = 'after-write'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $writeRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-write') 'fault stopped after local write'
Assert ($r.Out -match 'MAILBOX accepted \[701\] GIT_STATUS') 'accept was durable before the fault'
Assert (Test-Path -LiteralPath (Join-Path $writeRoot 'inbox/701.json')) 'local inbox exists'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'after-write did not run git'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch 'DELETE') 'cleanup had not run yet'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $writeRoot
Assert ($r.Out -match 'COMPLETED \[701\]: GIT_STATUS') 'restart executed the written task once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'after-write restart ran git once'
$deleted = $false
foreach ($line in ((Read-Log $env:FAKE_GH_LOG) -split "`n")) {
    if ($line -match 'DELETE' -and $line -match [regex]::Escape($writeId)) { $deleted = $true }
}
Assert ($deleted) 'cleanup was retried after the local write'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $writeRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'second restart did not run it'

Write-Host '[62] crash after cleanup does not execute twice'
$cleanId = '18181818-1818-1818-1818-181818181818'
Set-RemoteNamed $mailDir $cleanId (New-Envelope 1 'GIT_STATUS' $cleanId)
Set-Index $mailDir @($cleanId + '.json')
$cleanRoot = New-MailRoot 800
$env:ARENA_MAILBOX_FAULT = 'after-cleanup'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $cleanRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-cleanup') 'fault stopped after cleanup'
Assert (Test-Path -LiteralPath (Join-Path $cleanRoot 'inbox/801.json')) 'local inbox survived cleanup'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'after-cleanup did not run git'
$cleaned = $false
foreach ($line in ((Read-Log $env:FAKE_GH_LOG) -split "`n")) {
    if ($line -match 'DELETE' -and $line -match [regex]::Escape($cleanId)) { $cleaned = $true }
}
Assert ($cleaned) 'cleanup ran before the fault'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $cleanRoot
Assert ($r.Out -match 'COMPLETED \[801\]: GIT_STATUS') 'restart after cleanup ran once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'after-cleanup restart ran git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $cleanRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'second restart did not run it'

Write-Host '[63] archive is never polled or executed'
$archiveIndex = '[{"name":"archive","path":"archive","type":"dir"},{"name":"../1.json","path":"inbox/../1.json","type":"file"},{"name":"notes.txt","path":"archive/notes.txt","type":"file"},{"name":"evil.ps1","path":"inbox/evil.ps1","type":"file"}]'
Write-Utf8 (Join-Path $mailDir 'index.json') $archiveIndex
$archiveRoot = New-MailRoot 900
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $archiveRoot
Assert ([int](Get-MailState $archiveRoot).last_seq -eq 900) 'archive listing created no task'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'archive listing did not run git'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch 'contents/archive') 'archive endpoint was not requested'
foreach ($name in @('mailbox.ps1', 'arena-mailbox-put.ps1', 'arena-bridge-v2.ps1')) {
    $src = [System.IO.File]::ReadAllText((Join-Path $root $name))
    if ($src -match 'contents/archive') { throw "ASSERT FAILED: archive endpoint in $name" }
}
Write-Host '  ok: archive endpoint is absent from the implementation'

Write-Host '[64] producer push uses the task id, not an exec seq'
$pushRoot = New-MailRoot 12
Reset-Logs
$pushOut = & $runner -NoProfile -File $put -Action 'GIT_STATUS' -Push -MailboxRepo $mailRepo -ArenaRoot $pushRoot 2>&1
$pushCode = $LASTEXITCODE
$pushText = @($pushOut | ForEach-Object { "$_" }) -join "`n"
Assert ($pushCode -eq 0) "producer push exit 0 ($pushText)"
Assert ($pushText -match 'MAILBOX_PUSHED task_id=[0-9a-f-]{36}') 'push reported the task id'
$pushLog = Read-Log $env:FAKE_GH_LOG
Assert ($pushLog -match '/contents/inbox/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json') 'push URL is the task id'
Assert ($pushLog -notmatch '/contents/inbox/13\.json') 'push did not use an exec seq'
Assert (-not (Test-Path -LiteralPath (Join-Path $pushRoot 'reservations/13.json'))) 'push left no reservation'
$left = @(Get-ChildItem -LiteralPath (Join-Path $pushRoot 'mailbox-staging') -Filter '*.json' -File -ErrorAction SilentlyContinue)
Assert ($left.Count -eq 0) 'successful push removed its staging file'

Write-Host '[65] a fault field in the task is not the fault hook'
$fieldId = '19191919-1919-1919-1919-191919191919'
$fieldEnv = (New-Envelope 1 'GIT_STATUS' $fieldId).TrimEnd('}') + ',"fault":"before-accept"}'
Set-RemoteNamed $mailDir $fieldId $fieldEnv
Set-Index $mailDir @($fieldId + '.json')
$fieldRoot = New-MailRoot 12
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $fieldRoot
Assert ($r.Out -match 'unknown-field') 'fault field is an unknown field'
Assert ($r.Out -notmatch 'mailbox-fault:') 'task field did not trip the local hook'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'fault field did not run git'
Assert ([int](Get-MailState $fieldRoot).last_seq -eq 12) 'fault field did not execute'

Write-Host '[66] accepted task survives an expired transport envelope'
$expId = '21212121-2121-2121-2121-212121212121'
$expEnv = New-Envelope 1 'GIT_STATUS' $expId -ExpiresOffsetMin 30
Set-RemoteNamed $mailDir $expId $expEnv
Set-Index $mailDir @($expId + '.json')
$expRoot = New-MailRoot 700
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $expRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'expiry setup stopped after accept'
$storedPath = Join-Path $expRoot ('mailbox-accepted/' + $expId + '.json')
Assert (Test-Path -LiteralPath $storedPath) 'accepted envelope was stored'
$storedBefore = [System.IO.File]::ReadAllText($storedPath)
$expiredRemote = New-Envelope 1 'GIT_STATUS' $expId -CreatedOffsetMin -180 -ExpiresOffsetMin -60
Set-RemoteNamed $mailDir $expId $expiredRemote
$env:ARENA_MAILBOX_NOW = (Get-Date).ToUniversalTime().AddHours(48).ToString('yyyy-MM-ddTHH:mm:ssZ')
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $expRoot
Clear-PhaseEnv
Assert ([System.IO.File]::ReadAllText($storedPath) -eq $storedBefore) 'accepted file was not rewritten'
Assert ($r.Out -match 'COMPLETED \[701\]: GIT_STATUS') 'expired accepted task still ran'
Assert ($r.Out -notmatch 'MAILBOX rejected \[.*\] expired') 'expired transport envelope did not reject'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'expired accepted task ran git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $expRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'expired accepted task did not run again'

Write-Host '[67] a changed remote body does not replace the accepted task'
$chgId = '22222222-2222-2222-2222-222222222222'
Set-RemoteNamed $mailDir $chgId (New-Envelope 1 'GIT_VERSION' $chgId)
Set-Index $mailDir @($chgId + '.json')
$chgRoot = New-MailRoot 710
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $chgRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'content setup stopped after accept'
Set-RemoteNamed $mailDir $chgId (New-Envelope 1 'GIT_DIFF' $chgId)
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $chgRoot
Assert ($r.Out -match 'MAILBOX accepted-content-changed') 'changed remote body was noticed'
Assert ($r.Out -match 'COMPLETED \[711\]: GIT_VERSION') 'stored GIT_VERSION still ran'
Assert ($r.Out -notmatch 'COMPLETED \[.*\]: GIT_DIFF') 'replacement GIT_DIFF did not run'
Assert ($r.Out -notmatch 'GIT_DIFF') 'replacement action was not echoed'
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 1) 'stored action ran once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'diff') -eq 0) 'replacement action did not run git'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $chgRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 0) 'stored action did not run again'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'diff') -eq 0) 'replacement still did not run'

Write-Host '[68] a held task is not deleted before approval'
$heldId = '23232323-2323-2323-2323-232323232323'
Set-RemoteNamed $mailDir $heldId (New-Envelope 1 'GIT_STATUS' $heldId)
Set-Index $mailDir @($heldId + '.json')
$heldRoot = New-MailRoot 720
$env:ARENA_MAILBOX_HOLD_ACTIONS = 'GIT_STATUS'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $heldRoot
Assert ($r.Out -match 'MAILBOX held \[') 'critical test hook held the task'
Assert ($r.Out -notmatch 'COMPLETED') 'held task did not run'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'held task did not run git'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch 'DELETE') 'first held poll did not clean up'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $heldRoot
Assert ($r.Out -notmatch 'COMPLETED') 'second held poll did not run'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'second held poll did not run git'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch 'DELETE') 'held remote was not deleted'
$approveDir = Join-Path $heldRoot 'approve'
New-Item -ItemType Directory -Path $approveDir -Force | Out-Null
Write-Utf8 (Join-Path $approveDir $heldId) $heldId
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $heldRoot
Clear-PhaseEnv
Assert ($r.Out -match 'COMPLETED \[721\]: GIT_STATUS') 'approved held task continued'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'approved held task ran once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $heldRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'approved held task did not run again'

Write-Host '[69] crash after reserve reuses that reservation'
$resId = '24242424-2424-2424-2424-242424242424'
Set-RemoteNamed $mailDir $resId (New-Envelope 1 'GIT_STATUS' $resId)
Set-Index $mailDir @($resId + '.json')
$resRoot = New-MailRoot 800
$env:ARENA_MAILBOX_FAULT = 'after-reserve-before-seq-persist'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $resRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-reserve-before-seq-persist') 'fault stopped after reserve'
$resSeen = Get-SeenProp $resRoot $resId
Assert ($null -ne $resSeen -and [string]$resSeen.disposition -eq 'accepted') 'reserve fault kept accepted'
Assert ([int]$resSeen.seq -eq 0) 'reserve fault did not persist exec seq'
Assert (Test-Path -LiteralPath (Join-Path $resRoot 'reservations/801.json')) 'reservation 801 was left open'
Assert ([System.IO.File]::ReadAllText((Join-Path $resRoot 'reservations/801.json')) -match [regex]::Escape($resId)) 'reservation is bound to the task id'
Assert (-not (Test-Path -LiteralPath (Join-Path $resRoot 'inbox/801.json'))) 'reserve fault wrote no inbox'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'reserve fault did not run git'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $resRoot
Assert ($r.Out -match 'COMPLETED \[801\]: GIT_STATUS') 'restart reused reservation 801'
Assert ($r.Out -notmatch 'reservation-abandoned') 'live reservation was not abandoned'
Assert ($r.Out -notmatch 'COMPLETED \[802\]') 'restart did not skip to 802'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'reused reservation ran once'
Assert (-not (Test-Path -LiteralPath (Join-Path $resRoot 'reservations/801.json'))) 'reused reservation was closed'
Assert ([int](Get-MailState $resRoot).last_seq -eq 801) 'queue did not skip the reserved slot'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $resRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'reused reservation did not run again'


Write-Host '[70] accepted task recovers without the remote file'
$goneId = '27272727-2727-2727-2727-272727272727'
Set-RemoteNamed $mailDir $goneId (New-Envelope 1 'GIT_STATUS' $goneId)
Set-Index $mailDir @($goneId + '.json')
$goneRoot = New-MailRoot 730
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $goneRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'remote-loss setup stopped after accept'
Remove-Item -LiteralPath (Join-Path $mailDir ('content-' + $goneId + '.json')) -Force -ErrorAction SilentlyContinue
Set-Index $mailDir @()
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $goneRoot
Assert ($r.Out -match 'MAILBOX recovered \[731\] GIT_STATUS') 'recovered from local accepted file'
Assert ($r.Out -match 'COMPLETED \[731\]: GIT_STATUS') 'local recovery executed once'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch [regex]::Escape($goneId)) 'restart did not fetch the removed remote task'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'local recovery ran git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $goneRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'local recovery did not run again'

Write-Host '[71] accepted task runs when GitHub is unavailable'
$downId = '28282828-2828-2828-2828-282828282828'
Set-RemoteNamed $mailDir $downId (New-Envelope 1 'GIT_VERSION' $downId)
Set-Index $mailDir @($downId + '.json')
$downRoot = New-MailRoot 740
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $downRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'github-down setup stopped after accept'
$env:FAKE_GH_FAIL = '1'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $downRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-unavailable') 'GitHub outage was reported'
Assert ($r.Out -match 'COMPLETED \[741\]: GIT_VERSION') 'outage did not lose the accepted task'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch [regex]::Escape($downId)) 'outage did not re-fetch the command'
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 1) 'outage recovery ran once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $downRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 0) 'outage recovery did not run again'

Write-Host '[72] a changed accepted file is not executed'
$badId = '29292929-2929-2929-2929-292929292929'
Set-RemoteNamed $mailDir $badId (New-Envelope 1 'GIT_STATUS' $badId)
Set-Index $mailDir @($badId + '.json')
$badRoot = New-MailRoot 750
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $badRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'integrity setup stopped after accept'
$badPath = Join-Path $badRoot ('mailbox-accepted/' + $badId + '.json')
Write-Utf8 $badPath (New-Envelope 1 'GIT_DIFF' $badId)
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $badRoot
Assert ($r.Out -match ('MAILBOX accepted-body-mismatch \[' + $badId + '\]')) 'integrity failure was recorded'
Assert ($r.Out -notmatch 'COMPLETED') 'tampered envelope did not run'
Assert ($r.Out -notmatch 'GIT_DIFF') 'tampered action was not substituted'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'tampered envelope did not run git'
Assert ([int](Get-MailState $badRoot).last_seq -eq 750) 'tampered envelope did not take a seq'
Assert (-not (Test-Path -LiteralPath (Join-Path $badRoot 'inbox/751.json'))) 'tampered envelope wrote no inbox'
Assert (Test-Path -LiteralPath $badPath) 'tampered evidence was not deleted'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $badRoot
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'tampered envelope still did not run'

Write-Host '[73] a reservation cannot be adopted by another task'
$ownId = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'
$otherId = 'a0a0a0a0-a0a0-a0a0-a0a0-a0a0a0a0a0a0'
Set-RemoteNamed $mailDir $ownId (New-Envelope 1 'GIT_STATUS' $ownId)
Set-Index $mailDir @($ownId + '.json')
$ownRoot = New-MailRoot 760
$env:ARENA_MAILBOX_FAULT = 'after-reserve-before-seq-persist'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $ownRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-reserve-before-seq-persist') 'owner fault stopped after reserve'
$ownRes = [System.IO.File]::ReadAllText((Join-Path $ownRoot 'reservations/761.json'))
Assert ($ownRes -match [regex]::Escape($ownId)) 'reservation names its task'
Assert ($ownRes -notmatch [regex]::Escape($otherId)) 'reservation does not name the other task'
$otherBody = New-Envelope 1 'GIT_VERSION' $otherId
Write-Utf8 (Join-Path $ownRoot ('mailbox-accepted/' + $otherId + '.json')) $otherBody
$otherSha = Get-MailboxBodySha $otherBody
$statePath = Join-Path $ownRoot 'state.json'
$stateRaw = [System.IO.File]::ReadAllText($statePath)
$insert = '"' + $otherId + '":{"seq":0,"disposition":"accepted","reason":"","action":"GIT_VERSION","content_sha":"","body_sha":"' + $otherSha + '"},'
if ($stateRaw -notmatch '"seen":\{') { throw 'seen object missing' }
$stateRaw = $stateRaw -replace '"seen":\{', ('"seen":{' + $insert)
Write-Utf8 $statePath $stateRaw
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $ownRoot
Assert ($r.Out -match 'COMPLETED \[761\]: GIT_STATUS') 'owner kept its reservation'
Assert ($r.Out -notmatch 'COMPLETED \[761\]: GIT_VERSION') 'other task did not take the reservation'
Assert ($r.Out -match 'COMPLETED \[762\]: GIT_VERSION') 'other task took the next seq'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'owner ran once'
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--version') -eq 1) 'other task ran once'
Assert ([int](Get-MailState $ownRoot).last_seq -eq 762) 'both slots completed without a cross-adoption gap'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $ownRoot
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'neither task ran again'

Write-Host '[74] a legacy numeric name recovers without the remote file'
$numId = '32323232-3232-3232-3232-323232323232'
Set-RemoteTask $mailDir 14 (New-Envelope 14 'GIT_LOG10' $numId)
Set-Index $mailDir @('14.json')
$numRoot = New-MailRoot 770
$env:ARENA_MAILBOX_FAULT = 'after-accept'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $numRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-accept') 'numeric setup stopped after accept'
Remove-Item -LiteralPath (Join-Path $mailDir 'content-14.json') -Force -ErrorAction SilentlyContinue
Set-Index $mailDir @()
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $numRoot
Assert ($r.Out -match 'MAILBOX recovered \[771\] GIT_LOG10') 'numeric task recovered from local state'
Assert ($r.Out -match 'COMPLETED \[771\]: GIT_LOG10') 'numeric task executed once'
Assert ((Read-Log $env:FAKE_GH_LOG) -notmatch '/contents/inbox/14\.json') 'numeric restart did not fetch the remote name'
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--oneline') -eq 1) 'numeric recovery ran git once'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $numRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG '--oneline') -eq 0) 'numeric recovery did not run again'

Write-Host '[75] expired reservation does not abandon a persisted accepted seq'
$lateId = '34343434-3434-3434-3434-343434343434'
Set-RemoteNamed $mailDir $lateId (New-Envelope 1 'GIT_STATUS' $lateId)
Set-Index $mailDir @($lateId + '.json')
$lateRoot = New-MailRoot 810
$env:ARENA_MAILBOX_FAULT = 'after-seq-persist-before-inbox-write'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $lateRoot
Clear-PhaseEnv
Assert ($r.Out -match 'mailbox-fault:after-seq-persist-before-inbox-write') 'seq persist fault stopped before inbox write'
$lateSeen = Get-SeenProp $lateRoot $lateId
Assert ($null -ne $lateSeen -and [string]$lateSeen.disposition -eq 'accepted') 'seq persist fault kept accepted'
Assert ([int]$lateSeen.seq -eq 811) 'seq persist fault stored 811'
$lateRes = Join-Path $lateRoot 'reservations/811.json'
Assert (Test-Path -LiteralPath $lateRes) 'reservation 811 was left open'
Assert (-not (Test-Path -LiteralPath (Join-Path $lateRoot 'inbox/811.json'))) 'seq persist fault wrote no inbox'
Assert ((Read-Log $env:FAKE_GIT_LOG) -eq '') 'seq persist fault did not run git'
$lateRaw = [System.IO.File]::ReadAllText($lateRes)
$lateRaw = [regex]::Replace($lateRaw, '"created":"[^"]*"', '"created":"2020-01-01T00:00:00Z"')
Write-Utf8 $lateRes $lateRaw
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $lateRoot
Assert ($r.Out -notmatch 'reservation-abandoned') 'expired reservation did not abandon the accepted seq'
Assert ($r.Out -match 'MAILBOX recovered \[811\] GIT_STATUS') 'expired reservation recovered the same seq'
Assert ($r.Out -match 'COMPLETED \[811\]: GIT_STATUS') 'expired reservation executed once'
Assert ($r.Out -notmatch 'COMPLETED \[812\]') 'expired reservation did not take the next seq'
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 1) 'expired reservation ran git once'
Assert ([int](Get-MailState $lateRoot).last_seq -eq 811) 'expired reservation kept the persisted slot'
$lateTask = (Get-MailState $lateRoot).tasks.'811'
Assert ($null -eq $lateTask -or [string]$lateTask.reason -ne 'reservation-abandoned') 'accepted seq was not marked abandoned'
Assert (-not (Test-Path -LiteralPath $lateRes)) 'recovered reservation was closed'
Reset-Logs
$r = Invoke-Bridge -NoGithub -ArenaRoot $lateRoot
Assert ((Count-LogLines $env:FAKE_GIT_LOG 'status') -eq 0) 'expired reservation did not run again'

Clear-PhaseEnv
Set-Index $mailDir @()
Set-MailConfig $cfg $false $mailRepo
