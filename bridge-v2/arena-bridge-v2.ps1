# arena-bridge-v2.ps1 — Arena Local Bridge v2.
#
# Reliable executor: action IDs (no shell strings), monotonic sequence,
# state machine RECEIVED->RUNNING->COMPLETED->PENDING_PUBLISH->PUBLISHED,
# atomic writes, repo identity guard, durable outbox, single instance.
#
# Usage:
#   .\arena-bridge-v2.ps1
#   .\arena-bridge-v2.ps1 -WorkDir C:\path\to\repo -Repo owner/name -Issue 1
#   .\arena-bridge-v2.ps1 -Once -NoGithub            # one pass, no network (tests)

[CmdletBinding()]
param(
    # Empty means "not passed". Resolved after dot-source: explicit arg, then
    # env var, then the Windows default. Env vars exist so Windows PowerShell 5.1
    # tests do not have to put paths-with-spaces on the powershell.exe command line.
    [string]$WorkDir,
    [string]$Repo,
    [string]$Issue,
    [string]$ArenaRoot,
    [int]   $PollMs = 1000,
    [switch]$Once,
    [switch]$NoGithub,
    [string]$LegacyStateFile,
    [string]$LegacyTaskFile
)

$ErrorActionPreference = 'Continue'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'arena-common.ps1')
. (Join-Path $here 'actions.ps1')
. (Join-Path $here 'mailbox.ps1')

function Get-BridgeSetting {
    param($Bound, [string]$Name, [string]$EnvName, [scriptblock]$Default)
    if ($null -ne $Bound -and $Bound.ContainsKey($Name)) {
        $v = [string]$Bound[$Name]
        if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    }
    $ev = [Environment]::GetEnvironmentVariable($EnvName)
    if (-not [string]::IsNullOrWhiteSpace($ev)) { return $ev }
    if ($null -ne $Default) { return [string](& $Default) }
    return ''
}

$script:WorkDir = Get-BridgeSetting $PSBoundParameters 'WorkDir' 'ARENA_BRIDGE_WORKDIR' {
    Join-Path (Join-Path $script:UserProfile 'Documents') 'arena-archicad-project'
}
$script:Repo = Get-BridgeSetting $PSBoundParameters 'Repo' 'ARENA_BRIDGE_REPO' { 'dvikt33-ux/arena-archicad-project' }
$script:Issue = Get-BridgeSetting $PSBoundParameters 'Issue' 'ARENA_BRIDGE_ISSUE' { '1' }
$script:ArenaRoot = Get-BridgeSetting $PSBoundParameters 'ArenaRoot' 'ARENA_BRIDGE_ROOT' {
    $base = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { $base = $script:UserProfile }
    Join-Path $base 'ArenaBridge'
}
$script:LegacyStateFile = Get-BridgeSetting $PSBoundParameters 'LegacyStateFile' 'ARENA_BRIDGE_LEGACY_STATE_FILE' { $script:LegacyStateFile }
$script:LegacyTaskFile = Get-BridgeSetting $PSBoundParameters 'LegacyTaskFile' 'ARENA_BRIDGE_LEGACY_TASK_FILE' { $script:LegacyTaskFile }
$script:PollMs    = $PollMs
$script:Once      = [bool]$Once
$script:NoGithub  = [bool]$NoGithub

$script:InboxDir   = Join-Path $script:ArenaRoot 'inbox'
$script:OutboxDir  = Join-Path $script:ArenaRoot 'outbox'
$script:ResultsDir = Join-Path $script:ArenaRoot 'results'
$script:DoneDir    = Join-Path $script:InboxDir '.done'
$script:DeadDir    = Join-Path $script:OutboxDir '.dead'
$script:HeldDir    = Join-Path $script:ArenaRoot 'held'
$script:ApproveDir = Join-Path $script:ArenaRoot 'approve'
$script:StatePath  = Join-Path $script:ArenaRoot 'state.json'
$script:AuditPath  = Join-Path $script:ArenaRoot ('audit-' + (Get-Date -Format 'yyyy-MM-dd') + '.jsonl')

New-Dirs $script:ArenaRoot

# ---- single instance ----
$script:Mutex = [System.Threading.Mutex]::new($false, 'Local\ArenaBridge.v2')
try {
    if (-not $script:Mutex.WaitOne(0)) {
        Write-Host 'Another Arena Bridge instance is already running. Exiting.'
        exit 5
    }
}
catch {
    Write-Host "Mutex init failed: $($_.Exception.Message)"
    exit 5
}

# ---- audit log (append-only, no result bodies, no secrets) ----
function Write-Audit {
    param($Entry)
    try {
        if ($Entry -is [hashtable]) { $Entry['ts'] = (Get-Date -Format o) }
        $line = $Entry | ConvertTo-Json -Compress -Depth 6
        Add-Content -LiteralPath $script:AuditPath -Value $line -Encoding UTF8
    }
    catch { }
}

# ---- state helper (persists on every transition) ----
function Set-TaskState {
    param([int]$Seq, [hashtable]$Fields)
    $t = $script:State.tasks["$Seq"]
    if (-not $t) { $t = @{}; $script:State.tasks["$Seq"] = $t }
    foreach ($k in $Fields.Keys) { $t[$k] = $Fields[$k] }
    $t['updated'] = (Get-Date -Format o)
    Save-State $script:StatePath $script:State
}

# ---- result bodies ----
function Build-ResultBody {
    param([int]$Seq, [string]$Action, [string]$Status, $Res, [string]$Reason)
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $head = "[LOCAL RESULT $Seq]"
    if ($null -ne $Res) {
        $out = [string]$Res.Output
        if ($out.Length -gt 60000) { $out = $out.Substring(0, 60000) + "`r`n[truncated]" }
        return "$head`r`n`r`nTASK ID:`r`n$Seq`r`n`r`nACTION:`r`n$Action`r`n`r`nTIME:`r`n$now`r`n`r`nSTATUS:`r`n$Status`r`n`r`nEXIT CODE:`r`n$($Res.ExitCode)`r`n`r`nRESULT:`r`n$out"
    }
    return "$head`r`n`r`nTASK ID:`r`n$Seq`r`n`r`nACTION:`r`n$Action`r`n`r`nTIME:`r`n$now`r`n`r`nSTATUS:`r`n$Status`r`n`r`nREASON:`r`n$Reason"
}

function Build-PublicBody {
    param([int]$Seq, [string]$Action, [string]$Status, $Res, [string]$Reason, [switch]$OmitResult)
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $marker = "<!-- arena-task:$Seq -->"
    $head = "[LOCAL RESULT $Seq] $marker"
    $text = ''
    if ($null -ne $Res -and -not $OmitResult) {
        $out = [string]$Res.Output
        if ($out.Length -gt 60000) { $out = $out.Substring(0, 60000) + "`r`n[truncated]" }
        $text = "$head`r`n`r`nTASK ID:`r`n$Seq`r`n`r`nACTION:`r`n$Action`r`n`r`nTIME:`r`n$now`r`n`r`nSTATUS:`r`n$Status`r`n`r`nEXIT CODE:`r`n$($Res.ExitCode)`r`n`r`nRESULT:`r`n$out"
    }
    elseif ($OmitResult) {
        $text = "$head`r`n`r`nTASK ID:`r`n$Seq`r`n`r`nACTION:`r`n$Action`r`n`r`nTIME:`r`n$now`r`n`r`nSTATUS:`r`n$Status`r`n`r`nRESULT:`r`n(result not published: action is local-only)"
    }
    else {
        $text = "$head`r`n`r`nTASK ID:`r`n$Seq`r`n`r`nACTION:`r`n$Action`r`n`r`nTIME:`r`n$now`r`n`r`nSTATUS:`r`n$Status`r`n`r`nREASON:`r`n$Reason"
    }
    return (Protect-PublicText $text)
}

function Move-InboxFileAside {
    param($File, [string]$Tag)
    $name = $File.BaseName + '.' + $Tag + '.' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.json'
    try {
        Move-Item -LiteralPath $File.FullName -Destination (Join-Path $script:DoneDir $name) -Force
    }
    catch { }
}

# ---- publish ----
# gh is invoked with simple arguments only. Windows PowerShell 5.1 re-parses
# the command line of a native/.cmd process, so a jq program containing "|" or
# a body containing "<!-- -->" and newlines is not safe to pass as an argument.
# The body goes to a JSON file; the response is parsed in PowerShell.
function Invoke-GhApi {
    param([string[]]$GhArgs)
    $out = @(& gh @GhArgs 2>$null)
    $code = $LASTEXITCODE
    $text = (@($out) | ForEach-Object { "$_" }) -join "`n"
    return [pscustomobject]@{ Code = $code; Text = $text.Trim() }
}

function Test-CommentId {
    # GitHub comment ids no longer fit in Int32 (Issue #1 ids are ~5.7e9).
    # Keep them as digit strings so Windows PowerShell 5.1 cannot overflow them.
    param([string]$Id)
    if ([string]::IsNullOrWhiteSpace($Id)) { return $false }
    return ($Id -match '^\d+$' -and $Id -ne '0')
}

function Get-CommentIdFromText {
    # Accept either a bare id (`gh` --jq .id) or a comment object.
    # The comment id is the first "id" field; user.id comes later.
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $trim = $Text.Trim()
    if ($trim -match '^\d+$' -and $trim -ne '0') { return $trim }
    $m = [regex]::Match($Text, '"id"\s*:\s*"?(\d+)"?')
    if ($m.Success -and $m.Groups[1].Value -ne '0') { return $m.Groups[1].Value }
    return ''
}

function Get-CommentIdByMarker {
    # Returns the comment id as a digit string, or '' if none.
    # Do not ConvertFrom-Json the id: on Windows PowerShell 5.1 a number above
    # Int32.MaxValue becomes a Double, and [int]::TryParse then fails even
    # though gh exited 0. That failure used to POST a duplicate comment.
    param([int]$Seq)
    $marker = "<!-- arena-task:$Seq -->"
    $r = Invoke-GhApi @('api', "repos/$script:Repo/issues/$script:Issue/comments?per_page=100")
    if ($r.Code -ne 0 -or [string]::IsNullOrWhiteSpace($r.Text) -or $r.Text.Trim() -eq '[]') { return '' }
    $idx = $r.Text.IndexOf($marker)
    if ($idx -lt 0) { return '' }
    $before = $r.Text.Substring(0, $idx)
    # Comment shape is "id", then "user": { "id": ... }, then "body" with the marker.
    # The id immediately before "user" is the comment id, not the nested user id.
    $userIdx = $before.LastIndexOf('"user"')
    $head = $before
    if ($userIdx -ge 0) { $head = $before.Substring(0, $userIdx) }
    $found = [regex]::Matches($head, '"id"\s*:\s*"?(\d+)"?')
    if ($found.Count -eq 0) { return '' }
    $id = $found[$found.Count - 1].Groups[1].Value
    if (-not (Test-CommentId $id)) { return '' }
    return $id
}

function Publish-Comment {
    param([int]$Seq, [string]$Body)
    $payloadPath = Join-Path $script:ArenaRoot ('publish-' + [guid]::NewGuid().ToString('N') + '.json')
    $payload = @{ body = $Body } | ConvertTo-Json -Depth 5 -Compress
    Write-FileAtomic $payloadPath $payload
    try {
        $existing = Get-CommentIdByMarker $Seq
        if (Test-CommentId $existing) {
            $r = Invoke-GhApi @('api', '-X', 'PATCH', "repos/$script:Repo/issues/comments/$existing", '--input', $payloadPath)
            if ($r.Code -eq 0) { return [pscustomobject]@{ Ok = $true; Id = [string]$existing; Via = 'PATCH' } }
            # The marker is already on the issue. A failed PATCH must not fall
            # through to POST, or every retry adds another identical comment.
            return [pscustomobject]@{ Ok = $false; Code = $r.Code }
        }
        $r = Invoke-GhApi @('api', '-X', 'POST', "repos/$script:Repo/issues/$script:Issue/comments", '--input', $payloadPath)
        if ($r.Code -eq 0) {
            $id = Get-CommentIdFromText $r.Text
            if (-not (Test-CommentId $id)) {
                # gh exited 0 but the body was not recognized. The comment may
                # already exist; look it up before any retry creates a duplicate.
                $id = Get-CommentIdByMarker $Seq
            }
            if (Test-CommentId $id) { return [pscustomobject]@{ Ok = $true; Id = [string]$id; Via = 'POST' } }
            return [pscustomobject]@{ Ok = $false; Code = 0 }
        }
        return [pscustomobject]@{ Ok = $false; Code = $r.Code }
    }
    finally {
        Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
    }
}

function Publish-Outbox {
    $files = @(Get-ChildItem -LiteralPath $script:OutboxDir -Filter '*.json' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.BaseName -match '^\d+$' } |
            Sort-Object { [int]$_.BaseName })
    foreach ($f in $files) {
        $m = $null
        try { $m = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json }
        catch { continue }
        $seq = [int]$m.seq

        if ($script:NoGithub) {
            Write-Audit @{ ev = 'PUBLISH_DRYRUN'; seq = $seq; action = $m.action }
            continue
        }

        $r = Publish-Comment $seq ("$($m.public_body)")
        if ($r.Ok) {
            $t = $script:State.tasks["$seq"]
            if ($t) {
                $t['state'] = 'PUBLISHED'
                $t['comment_id'] = [string]$r.Id
                $t['updated'] = (Get-Date -Format o)
                Save-State $script:StatePath $script:State
            }
            Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
            Write-Audit @{ ev = 'PUBLISHED'; seq = $seq; via = $r.Via; comment_id = $r.Id }
            Write-Host "PUBLISHED [$seq] via $($r.Via) id=$($r.Id)"
        }
        else {
            $attempts = [int]$m.attempts + 1
            $m.attempts = $attempts
            Write-FileAtomic $f.FullName ($m | ConvertTo-Json -Depth 6 -Compress)
            if ($attempts -ge 10) {
                Move-Item -LiteralPath $f.FullName -Destination (Join-Path $script:DeadDir ($f.BaseName + '.dead.json')) -Force -ErrorAction SilentlyContinue
                Write-Audit @{ ev = 'PUBLISH_DEAD'; seq = $seq; code = $r.Code }
                Write-Host "PUBLISH DEAD-LETTER [$seq] (code $($r.Code))"
            }
            else {
                $backoffMs = [int][Math]::Min(60000, 2000 * [Math]::Pow(2, $attempts))
                Write-Audit @{ ev = 'PUBLISH_RETRY'; seq = $seq; code = $r.Code; attempt = $attempts; backoff_ms = $backoffMs }
                $why = "code $($r.Code)"
                if ([string]$r.Code -eq '0') { $why = 'code 0, comment id not recognized' }
                Write-Host "PUBLISH RETRY [$seq] attempt $attempts ($why)"
                Start-Sleep -Milliseconds $backoffMs
            }
        }
    }
}

# ---- task processing ----
function Finalize-Task {
    param($File, [int]$Seq, [string]$Action, [string]$Status, $Res,
        [string]$Body, [string]$Pub, [bool]$Public, [string]$Reason)
    $resultFile = Join-Path $script:ResultsDir "result-$Seq.txt"
    Write-FileAtomic $resultFile $Body
    $exit = $null
    if ($null -ne $Res) { $exit = $Res.ExitCode }
    Set-TaskState $Seq @{ action = $Action; state = $Status; status = $Status; exit = $exit; result_file = $resultFile; reason = $Reason }
    $msg = [ordered]@{ seq = $Seq; action = $Action; status = $Status; public = $Public; public_body = $Pub; attempts = 0 }
    Write-FileAtomic (Join-Path $script:OutboxDir "$Seq.json") ($msg | ConvertTo-Json -Depth 6 -Compress)
    $script:State.last_seq = $Seq
    Set-TaskState $Seq @{ state = 'PENDING_PUBLISH' }
    Move-InboxFileAside $File 'consumed'
    Write-Host "$Status [$Seq]: $Action ($Reason)"
}

function Process-Task {
    param($File, [int]$Seq)

    $envObj = $null
    try {
        $envObj = Get-Content -LiteralPath $File.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-Audit @{ ev = 'TASK_BADJSON'; seq = $Seq }
        $body = Build-ResultBody $Seq '(unreadable)' 'BLOCKED' $null 'bad-json'
        $pub = Build-PublicBody $Seq '(unreadable)' 'BLOCKED' $null 'bad-json'
        Finalize-Task $File $Seq '(unreadable)' 'BLOCKED' $null $body $pub $true 'bad-json'
        return
    }

    $action = ("$($envObj.action)").Trim().ToUpperInvariant()

    if (-not $script:Actions.ContainsKey($action)) {
        Write-Audit @{ ev = 'BLOCKED'; seq = $Seq; action = $action }
        $body = Build-ResultBody $Seq '(unknown-action)' 'BLOCKED' $null "unknown action: $action"
        $pub = Build-PublicBody $Seq '(unknown-action)' 'BLOCKED' $null 'unknown-action'
        Finalize-Task $File $Seq '(unknown-action)' 'BLOCKED' $null $body $pub $true 'unknown-action'
        return
    }

    # RECEIVED, then RUNNING fence BEFORE execution.
    Set-TaskState $Seq @{ action = $action; state = 'RECEIVED' }
    Set-TaskState $Seq @{ action = $action; state = 'RUNNING'; pid = $PID; started = (Get-Date -Format o) }

    $guardErr = $null
    try { $guardErr = Test-RepoGuard $script:WorkDir $script:Repo }
    catch { $guardErr = 'guard-error' }
    if ($guardErr) {
        Write-Audit @{ ev = 'FAILED'; seq = $Seq; action = $action; reason = "repo-guard:$guardErr" }
        $body = Build-ResultBody $Seq $action 'FAILED' $null "repo-guard: $guardErr"
        $pub = Build-PublicBody $Seq $action 'FAILED' $null "repo-guard: $guardErr"
        Finalize-Task $File $Seq $action 'FAILED' $null $body $pub $true "repo-guard:$guardErr"
        return
    }

    $res = $null
    try { $res = Invoke-Action $action $script:WorkDir }
    catch {
        Write-Audit @{ ev = 'FAILED'; seq = $Seq; action = $action; reason = 'exec-error' }
        $body = Build-ResultBody $Seq $action 'FAILED' $null 'exec-error'
        $pub = Build-PublicBody $Seq $action 'FAILED' $null 'exec-error'
        Finalize-Task $File $Seq $action 'FAILED' $null $body $pub $true 'exec-error'
        return
    }

    $okExit = $script:Actions[$action].OkExit
    $status = if (@($okExit) -contains $res.ExitCode) { 'COMPLETED' } else { 'FAILED' }
    $body = Build-ResultBody $Seq $action $status $res ''
    $resultFile = Join-Path $script:ResultsDir "result-$Seq.txt"
    Write-FileAtomic $resultFile $body

    # COMPLETED persisted AFTER execution.
    Set-TaskState $Seq @{ action = $action; state = 'COMPLETED'; status = $status; exit = $res.ExitCode; result_file = $resultFile }

    $mode = 'none'
    if ($script:Actions[$action].ContainsKey('PublicResult')) {
        $mode = [string]$script:Actions[$action].PublicResult
    }
    if (-not $script:Actions[$action].Public) { $mode = 'none' }
    $safeText = ''
    if ($mode -ne 'none') {
        $safeText = Get-PublicResultText -Mode $mode -Text ([string]$res.Output)
    }
    if ($mode -eq 'none' -or [string]::IsNullOrWhiteSpace($safeText)) {
        $pub = Build-PublicBody $Seq $action $status $res '' -OmitResult
    }
    else {
        $safeRes = [pscustomobject]@{ ExitCode = $res.ExitCode; Output = $safeText }
        $pub = Build-PublicBody $Seq $action $status $safeRes ''
    }

    $msg = [ordered]@{ seq = $Seq; action = $action; status = $status; public = [bool]$script:Actions[$action].Public; public_body = $pub; attempts = 0 }
    Write-FileAtomic (Join-Path $script:OutboxDir "$Seq.json") ($msg | ConvertTo-Json -Depth 6 -Compress)
    $script:State.last_seq = $Seq
    Set-TaskState $Seq @{ state = 'PENDING_PUBLISH' }

    Move-InboxFileAside $File 'consumed'
    Write-Audit @{ ev = $status; seq = $Seq; action = $action; exit = $res.ExitCode }
    Write-Host "$status [$Seq]: $action (exit $($res.ExitCode))"
}

# ================= startup =================

$script:State = $null
if (Test-Path -LiteralPath $script:StatePath) {
    try { $script:State = Read-State $script:StatePath }
    catch {
        Write-Output "FATAL: $($_.Exception.Message)"
        Write-Host "FATAL: $($_.Exception.Message)"
        Write-Host "Fix or remove '$script:StatePath', then restart."
        exit 6
    }
}
else {
    $seed = Get-SeedLastSeq $script:LegacyStateFile
    $script:State = @{ last_seq = $seed; tasks = @{} }
    Save-State $script:StatePath $script:State
    if ($seed -gt 0) { Write-Host "Seeded last_seq=$seed from legacy v1 state file." }
}

if (Test-Path -LiteralPath $script:LegacyTaskFile) {
    $leg = "$(Get-Content -LiteralPath $script:LegacyTaskFile -Raw -ErrorAction SilentlyContinue)".Trim()
    if (-not [string]::IsNullOrWhiteSpace($leg)) {
        Write-Audit @{ ev = 'LEGACY_TASK_IGNORED'; note = 'v1 task.txt is not consumed by v2; use router v2' }
        Write-Host 'WARNING: v1 task.txt present but ignored by v2 (use arena-qwen-router-v2.ps1).'
    }
}

# Crash recovery: RUNNING -> FAILED(recovered). Never auto re-run.
$recoveredAny = $false
foreach ($k in @($script:State.tasks.Keys)) {
    $t = $script:State.tasks[$k]
    if ($t['state'] -eq 'RUNNING') {
        $seq = [int]$k
        $action = "$($t['action'])"
        $t['state'] = 'FAILED'
        $t['status'] = 'FAILED'
        $t['reason'] = 'recovered: crashed during execution (no auto re-run)'
        $t['updated'] = (Get-Date -Format o)
        $body = Build-ResultBody $seq $action 'FAILED' $null "$($t['reason'])"
        Write-FileAtomic (Join-Path $script:ResultsDir "result-$seq.txt") $body
        $pub = Build-PublicBody $seq $action 'FAILED' $null "$($t['reason'])"
        $msg = [ordered]@{ seq = $seq; action = $action; status = 'FAILED'; public = $true; public_body = $pub; attempts = 0 }
        Write-FileAtomic (Join-Path $script:OutboxDir "$seq.json") ($msg | ConvertTo-Json -Depth 6 -Compress)
        if ($seq -gt [int]$script:State.last_seq) { $script:State.last_seq = $seq }
        Write-Audit @{ ev = 'RECOVERED'; seq = $seq; action = $action }
        $recoveredAny = $true
    }
}
if ($recoveredAny) { Save-State $script:StatePath $script:State }

Initialize-MailboxFromConfig
if ($null -eq $script:State.mailbox) {
    $script:State.mailbox = @{ seen = @{}; rejected_seqs = @(); remote_files = @{} }
}
$script:ActionPolicy = Get-ActionPolicyFromTable
$script:State = Resolve-ExpiredReservations -ArenaRoot $script:ArenaRoot -State $script:State -StatePath $script:StatePath

Write-Output ("ARENA_BRIDGE_LAST_SEQ=" + $script:State.last_seq)
Write-Output ("ARENA_BRIDGE_LEGACY=" + $script:LegacyStateFile)
Write-Output ("ARENA_BRIDGE_STATE=" + $script:StatePath)
Write-Host 'Arena Bridge v2 is running.'
Write-Host "Repo:     $script:Repo"
Write-Host "WorkDir:  $script:WorkDir"
Write-Host "State:    $script:StatePath (last_seq=$($script:State.last_seq))"
Write-Host "Legacy:   $script:LegacyStateFile"
Write-Host "Inbox:    $script:InboxDir"
if ($script:MailboxEnabled) {
    Write-Host "Mailbox:  $script:MailboxRepo (poll $($script:MailboxPollSec)s, no prompt)"
}
else {
    Write-Host 'Mailbox:  disabled'
}
Write-Host 'Press Ctrl+C to stop.'

# ================= main loop =================
while ($true) {
    try {
        $script:State = Resolve-ExpiredReservations -ArenaRoot $script:ArenaRoot -State $script:State -StatePath $script:StatePath
        Publish-Outbox
        Invoke-MailboxSync

        $files = @(Get-ChildItem -LiteralPath $script:InboxDir -Filter '*.json' -File -ErrorAction SilentlyContinue |
                Where-Object { $_.BaseName -match '^\d+$' } |
                Sort-Object { [int]$_.BaseName })

        foreach ($f in $files) {
            $seq = [int]$f.BaseName
            if ($seq -le $script:State.last_seq) {
                Move-InboxFileAside $f 'duplicate'
                Write-Audit @{ ev = 'DUP'; seq = $seq }
                Write-Host "IGNORED [$seq]: duplicate/replay (last_seq=$($script:State.last_seq))"
                continue
            }
            if ($seq -gt $script:State.last_seq + 1) {
                # No inbox file and no expired reservation for the missing seq: wait.
                # Smoke checks [5] and [6] depend on this. A live reservation holds
                # the slot the same way. An expired one was already REJECTED above.
                Write-Audit @{ ev = 'GAP'; have = $script:State.last_seq; saw = $seq }
                Write-Host "GAP: expecting $($script:State.last_seq + 1), found $seq (waiting for missing tasks)"
                break
            }
            $existing = $script:State.tasks["$seq"]
            if ($existing) {
                $st = [string]$existing['state']
                $terminal = @('RUNNING', 'COMPLETED', 'PENDING_PUBLISH', 'PUBLISHED', 'FAILED', 'BLOCKED', 'REJECTED')
                $entered = $false
                foreach ($x in $terminal) { if ($st -eq $x) { $entered = $true } }
                if ($entered) {
                    Move-InboxFileAside $f 'already-ran'
                    Write-Audit @{ ev = 'DUP_STATE'; seq = $seq; state = $st }
                    continue
                }
            }
            Process-Task $f $seq
        }
    }
    catch {
        Write-Audit @{ ev = 'BRIDGE_ERROR'; err = "$($_.Exception.Message)" }
        Write-Host "BRIDGE ERROR: $($_.Exception.Message)"
    }

    if ($script:Once) { break }
    Start-Sleep -Milliseconds $script:PollMs
}
