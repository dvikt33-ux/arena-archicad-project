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
        'ARENA_MAILBOX_FAULT', 'ARENA_MAILBOX_LIST_WARN_AT',
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

Clear-PhaseEnv
Set-Index $mailDir @()
Set-MailConfig $cfg $false $mailRepo
