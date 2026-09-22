# mailbox.ps1 — remote intake for Arena Bridge v2.
#
# Transport and trust are separate. A private GitHub repository is only the
# drop box. The JSON file is not trusted: the bridge asks GitHub who committed
# it, and accepts the task only when that account is dvikt33-ux. There is no
# HMAC field, because ChatGPT cannot hold the local secret.
#
# Current allowlisted actions are not critical, so a trusted task runs with no
# PowerShell prompt. A critical action is held and is not executed. Polling is
# off unless a local mailbox.json (never committed) enables it.
#
# Dot-source after arena-common.ps1 and actions.ps1. This file defines
# functions only; it does not poll and it does not start the bridge.

$script:MailboxExpectedOwner = 'dvikt33-ux'
$script:MailboxForbiddenRepos = @('dvikt33-ux/arena-archicad-project')
$script:MailboxAllowedFields = @('schema', 'seq', 'task_id', 'action', 'args', 'created_at', 'expires_at')
$script:MailboxTaskIdPattern = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
$script:MailboxTimePattern = '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
$script:MailboxEnabled = $false
$script:MailboxRepo = ''
$script:MailboxOwner = $script:MailboxExpectedOwner
$script:MailboxPollSec = 15
$script:MailboxBackoffSec = 15
$script:MailboxNextPoll = [datetime]::MinValue
$script:MailboxGapLogged = @{}

function Test-JsonWholeNumber {
    param($Value)
    if ($null -eq $Value) { return $false }
    if ($Value -is [string] -or $Value -is [bool] -or $Value -is [double] -or $Value -is [float]) { return $false }
    $n = $null
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [decimal]) {
        $n = [decimal]$Value
    }
    else { return $false }
    if ($n -ne [decimal]::Truncate($n)) { return $false }
    if ($n -lt 1 -or $n -gt 999999999) { return $false }
    return $true
}

function ConvertTo-WholeNumber {
    param($Value)
    if (-not (Test-JsonWholeNumber $Value)) { return $null }
    return [int]$Value
}

function ConvertFrom-MailboxTime {
    param([string]$Text)
    if ($Text -notmatch $script:MailboxTimePattern) { return $null }
    $parsed = [datetime]::MinValue
    $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor [System.Globalization.DateTimeStyles]::AssumeUniversal
    $ok = [datetime]::TryParseExact(
        $Text,
        'yyyy-MM-ddTHH:mm:ssZ',
        [System.Globalization.CultureInfo]::InvariantCulture,
        $styles,
        [ref]$parsed)
    if (-not $ok) { return $null }
    return $parsed
}

function Format-MailboxTime {
    param([datetime]$Value)
    return $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

function New-MailboxEnvelopeJson {
    # Builds a canonical envelope. Returns $null if any piece is not strict.
    # Callers must not pass a shell string: action is an allowlist id.
    param([int]$Seq, [string]$Action, [string]$TaskId, [string]$Created, [string]$Expires)
    if ($Seq -lt 1 -or $Seq -gt 999999999) { return $null }
    if ($Action -notmatch '^[A-Z0-9_]+$') { return $null }
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -notmatch $script:MailboxTaskIdPattern) { return $null }
    if ($Created -notmatch $script:MailboxTimePattern) { return $null }
    if ($Expires -notmatch $script:MailboxTimePattern) { return $null }
    return ('{"schema":1,"seq":' + $Seq + ',"task_id":"' + $id + '","action":"' + $Action + '","args":{},"created_at":"' + $Created + '","expires_at":"' + $Expires + '"}')
}

function Get-ActionPolicyFromTable {
    # Missing Critical fails closed (held, not auto-run). Only ActionIds are offered.
    $policy = @{}
    foreach ($id in @($script:ActionIds)) {
        if (-not $script:Actions.ContainsKey($id)) { continue }
        $a = $script:Actions[$id]
        $names = @()
        if ($a.ContainsKey('ArgNames') -and $null -ne $a.ArgNames) { $names = @($a.ArgNames) }
        $critical = $true
        if ($a.ContainsKey('Critical')) { $critical = [bool]$a.Critical }
        $policy[$id] = @{ Critical = $critical; ArgNames = $names }
    }
    return $policy
}

function Resolve-MailboxHold {
    # Critical tasks do not run unless a local approve file already exists.
    # There is no Read-Host prompt. Non-critical tasks are never held.
    param([bool]$Critical, [bool]$Approved)
    if (-not $Critical) { return $false }
    if ($Approved) { return $false }
    return $true
}

function Test-MailboxApproved {
    param([string]$TaskId, [string]$ApproveDir)
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -notmatch $script:MailboxTaskIdPattern) { return $false }
    if ([string]::IsNullOrWhiteSpace($ApproveDir)) { return $false }
    $path = Join-Path $ApproveDir $id
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $raw = ''
    try { $raw = "$(Get-Content -LiteralPath $path -Raw -ErrorAction Stop)".Trim().ToLowerInvariant() }
    catch { return $false }
    return ($raw -eq $id)
}

function Test-MailboxRepoName {
    param([string]$Repo, [string]$ResultsRepo)
    if ([string]::IsNullOrWhiteSpace($Repo)) { return 'missing-repo' }
    if ($Repo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { return 'bad-repo' }
    $owner = $Repo.Split('/')[0]
    if (-not $owner.Equals($script:MailboxExpectedOwner, [System.StringComparison]::OrdinalIgnoreCase)) {
        return 'bad-owner'
    }
    $blocked = @($script:MailboxForbiddenRepos)
    if (-not [string]::IsNullOrWhiteSpace($ResultsRepo)) { $blocked += $ResultsRepo }
    foreach ($b in $blocked) {
        if ($Repo.Equals([string]$b, [System.StringComparison]::OrdinalIgnoreCase)) { return 'repo-is-results' }
    }
    return $null
}

function ConvertTo-MailboxConfig {
    # Fail closed. Unknown keys (token, secret, hmac, command) disable the mailbox.
    param([string]$Json, [string]$ResultsRepo)
    if ([string]::IsNullOrWhiteSpace($Json)) { return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false } }
    $obj = $null
    try { $obj = $Json | ConvertFrom-Json -ErrorAction Stop }
    catch { return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false } }
    if ($null -eq $obj -or $obj -is [System.Array]) {
        return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false }
    }
    $allowed = @('enabled', 'repo', 'owner', 'poll_sec')
    foreach ($p in @($obj.PSObject.Properties)) {
        if ($allowed -notcontains $p.Name) {
            return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false }
        }
    }
    if (@($obj.PSObject.Properties.Name) -notcontains 'enabled') {
        return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false }
    }
    if ($obj.enabled -isnot [bool]) {
        return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false }
    }
    if (-not $obj.enabled) {
        return @{ Ok = $true; Reason = ''; Enabled = $false; Repo = ''; Owner = $script:MailboxExpectedOwner; PollSec = 15 }
    }
    $names = @($obj.PSObject.Properties.Name)
    if ($names -notcontains 'repo') { return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false } }
    $repo = [string]$obj.repo
    $repoErr = Test-MailboxRepoName $repo $ResultsRepo
    if ($repoErr) { return @{ Ok = $false; Reason = $repoErr; Enabled = $false } }
    if ($names -contains 'owner') {
        $owner = [string]$obj.owner
        if (-not $owner.Equals($script:MailboxExpectedOwner, [System.StringComparison]::OrdinalIgnoreCase)) {
            return @{ Ok = $false; Reason = 'bad-owner'; Enabled = $false }
        }
    }
    $poll = 15
    if ($names -contains 'poll_sec') {
        $pollN = ConvertTo-WholeNumber $obj.poll_sec
        if ($null -eq $pollN -or $pollN -lt 5 -or $pollN -gt 300) {
            return @{ Ok = $false; Reason = 'config-invalid'; Enabled = $false }
        }
        $poll = $pollN
    }
    return @{ Ok = $true; Reason = ''; Enabled = $true; Repo = $repo; Owner = $script:MailboxExpectedOwner; PollSec = $poll }
}

function Get-MailboxConfigPath {
    $envPath = [Environment]::GetEnvironmentVariable('ARENA_MAILBOX_CONFIG')
    if (-not [string]::IsNullOrWhiteSpace($envPath)) { return $envPath }
    if ([string]::IsNullOrWhiteSpace($script:ArenaRoot)) { return '' }
    return (Join-Path $script:ArenaRoot 'mailbox.json')
}

function Initialize-MailboxFromConfig {
    $script:MailboxEnabled = $false
    $script:MailboxRepo = ''
    $script:MailboxOwner = $script:MailboxExpectedOwner
    $script:MailboxPollSec = 15
    $script:MailboxBackoffSec = 15
    $script:MailboxGapLogged = @{}
    $path = Get-MailboxConfigPath
    if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return
    }
    $raw = ''
    try { $raw = Get-Content -LiteralPath $path -Raw -ErrorAction Stop }
    catch {
        Write-Audit @{ ev = 'MAILBOX_CONFIG'; reason = 'config-invalid' }
        return
    }
    $cfg = ConvertTo-MailboxConfig $raw $script:Repo
    if (-not $cfg.Ok) {
        Write-Audit @{ ev = 'MAILBOX_CONFIG'; reason = $cfg.Reason }
        Write-Host ("Mailbox:  disabled (" + $cfg.Reason + ")")
        return
    }
    if (-not $cfg.Enabled) { return }
    $script:MailboxEnabled = $true
    $script:MailboxRepo = [string]$cfg.Repo
    $script:MailboxOwner = $script:MailboxExpectedOwner
    $script:MailboxPollSec = [int]$cfg.PollSec
    $script:MailboxBackoffSec = [int]$cfg.PollSec
}

function ConvertFrom-MailboxJson {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return @{ Ok = $false; Reason = 'bad-json' } }
    if ($Text.Length -gt 8192) { return @{ Ok = $false; Reason = 'too-large' } }
    $obj = $null
    try { $obj = $Text | ConvertFrom-Json -ErrorAction Stop }
    catch { return @{ Ok = $false; Reason = 'bad-json' } }
    if ($null -eq $obj -or $obj -is [System.Array]) { return @{ Ok = $false; Reason = 'bad-json' } }
    return @{ Ok = $true; Value = $obj }
}

function ConvertFrom-MailboxFilePayload {
    param($ApiObject)
    if ($null -eq $ApiObject -or $ApiObject -is [System.Array]) { return @{ Ok = $false; Reason = 'bad-payload' } }
    $names = @($ApiObject.PSObject.Properties.Name)
    if ($names -notcontains 'encoding' -or [string]$ApiObject.encoding -ne 'base64') {
        return @{ Ok = $false; Reason = 'bad-payload' }
    }
    if ($names -notcontains 'content') { return @{ Ok = $false; Reason = 'bad-payload' } }
    if ($names -contains 'size') {
        $sz = $ApiObject.size
        if ($sz -is [string] -or $sz -is [double] -or $sz -is [bool]) { return @{ Ok = $false; Reason = 'too-large' } }
        if (($sz -is [int] -or $sz -is [long] -or $sz -is [decimal]) -and [decimal]$sz -gt 8192) {
            return @{ Ok = $false; Reason = 'too-large' }
        }
    }
    $b64 = ([string]$ApiObject.content) -replace '\s', ''
    if ($b64.Length -eq 0 -or $b64.Length -gt 12000) { return @{ Ok = $false; Reason = 'too-large' } }
    if ($b64 -notmatch '^[A-Za-z0-9+/=]+$') { return @{ Ok = $false; Reason = 'bad-payload' } }
    $bytes = $null
    try { $bytes = [Convert]::FromBase64String($b64) }
    catch { return @{ Ok = $false; Reason = 'bad-payload' } }
    if ($null -eq $bytes -or $bytes.Length -gt 8192) { return @{ Ok = $false; Reason = 'too-large' } }
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    if ($text.Length -gt 0 -and [int][char]$text[0] -eq 0xFEFF) { $text = $text.Substring(1) }
    return @{ Ok = $true; Text = $text }
}

function Get-MailboxFileNames {
    # Only inbox/<digits>.json. Never use the API path field (it can contain ..).
    param($Parsed)
    if ($null -eq $Parsed) { return @() }
    $items = @()
    if ($Parsed -is [System.Array]) { $items = @($Parsed) }
    else {
        $n = @($Parsed.PSObject.Properties.Name)
        if ($n -contains 'message' -and $n -notcontains 'name') { return @() }
        if ($n -contains 'name') { $items = @($Parsed) }
        else { return @() }
    }
    $names = @()
    foreach ($it in $items) {
        if ($null -eq $it) { continue }
        $pn = @($it.PSObject.Properties.Name)
        if ($pn -notcontains 'name' -or $pn -notcontains 'type') { continue }
        if ([string]$it.type -ne 'file') { continue }
        $name = [string]$it.name
        if ($name -notmatch '^[1-9][0-9]{0,8}\.json$') { continue }
        $names += $name
    }
    return $names
}

function Get-FirstObject {
    param($Parsed)
    if ($null -eq $Parsed) { return $null }
    if ($Parsed -is [System.Array]) {
        if ($Parsed.Count -lt 1) { return $null }
        return $Parsed[0]
    }
    return $Parsed
}

function Test-MailboxTrust {
    # Author login comes from the GitHub API commit object, never from the task JSON.
    param($RepoMeta, $Commit, [string]$ExpectedRepo, [string]$ExpectedOwner)
    if ($null -eq $RepoMeta -or $RepoMeta -is [System.Array]) { return 'not-private' }
    $names = @($RepoMeta.PSObject.Properties.Name)
    if ($names -notcontains 'private' -or $RepoMeta.private -isnot [bool] -or $RepoMeta.private -ne $true) {
        return 'not-private'
    }
    if ($names -notcontains 'full_name') { return 'repo-mismatch' }
    if (-not ([string]$RepoMeta.full_name).Equals($ExpectedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
        return 'repo-mismatch'
    }
    if ($null -eq $Commit -or $Commit -is [System.Array]) { return 'forged-author' }
    $cn = @($Commit.PSObject.Properties.Name)
    if ($cn -notcontains 'author' -or $null -eq $Commit.author) { return 'forged-author' }
    $an = @($Commit.author.PSObject.Properties.Name)
    if ($an -notcontains 'login') { return 'forged-author' }
    $login = [string]$Commit.author.login
    if (-not $login.Equals($ExpectedOwner, [System.StringComparison]::OrdinalIgnoreCase)) { return 'forged-author' }
    if ($cn -notcontains 'committer' -or $null -eq $Commit.committer) { return 'untrusted-committer' }
    $ctn = @($Commit.committer.PSObject.Properties.Name)
    if ($ctn -notcontains 'login') { return 'untrusted-committer' }
    $ct = [string]$Commit.committer.login
    $trusted = $false
    foreach ($allowed in @($ExpectedOwner, 'web-flow')) {
        if ($ct.Equals($allowed, [System.StringComparison]::OrdinalIgnoreCase)) { $trusted = $true }
    }
    if (-not $trusted) { return 'untrusted-committer' }
    return $null
}

function Test-MailboxArgs {
    param($ArgsObj, [string[]]$AllowedNames)
    if ($null -eq $ArgsObj) { return 'bad-args' }
    if ($ArgsObj -is [System.Array] -or $ArgsObj -is [string] -or $ArgsObj -is [bool] -or $ArgsObj -is [int] -or $ArgsObj -is [long] -or $ArgsObj -is [double] -or $ArgsObj -is [decimal]) {
        return 'bad-args'
    }
    $allowed = @($AllowedNames)
    foreach ($p in @($ArgsObj.PSObject.Properties)) {
        if ($allowed -notcontains $p.Name) { return 'bad-args' }
    }
    return $null
}

function Get-MailboxRawField {
    # ConvertFrom-Json turns ISO timestamps into DateTime and then stringifies
    # them in the local culture. The strict clock check must use the raw JSON.
    param([string]$Text, [string]$Name)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $pattern = '"' + [regex]::Escape($Name) + '"\s*:\s*"([^"]*)"'
    $m = [regex]::Match($Text, $pattern)
    if (-not $m.Success) { return '' }
    return $m.Groups[1].Value
}

function Get-RemoteDecision {
    # Returns @{ Ok; Hold; Reason; Action; TaskId; Seq }. Does not execute anything.
    param($Envelope, $Policy, [datetime]$Now, [string]$RawText = '')
    $fail = { param($Reason) return @{ Ok = $false; Hold = $false; Reason = $Reason; Action = ''; TaskId = ''; Seq = 0 } }
    if ($null -eq $Envelope -or $Envelope -is [System.Array]) { return (& $fail 'bad-json') }
    $names = @($Envelope.PSObject.Properties.Name)
    foreach ($n in $names) {
        if ($script:MailboxAllowedFields -notcontains $n) { return (& $fail 'unknown-field') }
    }
    foreach ($req in $script:MailboxAllowedFields) {
        if ($names -notcontains $req) { return (& $fail 'missing-field') }
    }
    if (-not (Test-JsonWholeNumber $Envelope.schema) -or [int]$Envelope.schema -ne 1) { return (& $fail 'bad-schema') }
    if (-not (Test-JsonWholeNumber $Envelope.seq)) { return (& $fail 'bad-seq') }
    $seq = [int]$Envelope.seq
    $taskId = ([string]$Envelope.task_id).Trim().ToLowerInvariant()
    if ($taskId -notmatch $script:MailboxTaskIdPattern) { return (& $fail 'bad-task-id') }
    $actionRaw = ([string]$Envelope.action).Trim()
    if ($actionRaw -notmatch '^[A-Za-z0-9_]+$') { return (& $fail 'unknown-action') }
    $action = $actionRaw.ToUpperInvariant()
    if (-not $Policy.ContainsKey($action)) { return (& $fail 'unknown-action') }
    $argErr = Test-MailboxArgs $Envelope.args @($Policy[$action].ArgNames)
    if ($argErr) { return (& $fail $argErr) }
    $createdText = Get-MailboxRawField $RawText 'created_at'
    $expiresText = Get-MailboxRawField $RawText 'expires_at'
    $created = ConvertFrom-MailboxTime $createdText
    $expires = ConvertFrom-MailboxTime $expiresText
    if ($null -eq $created -or $null -eq $expires) { return (& $fail 'bad-time') }
    if ($created -gt $Now.AddMinutes(5)) { return (& $fail 'not-yet-valid') }
    if ($expires -le $Now) { return (& $fail 'expired') }
    if ($expires -le $created) { return (& $fail 'bad-time') }
    if (($expires - $created).TotalHours -gt 24) { return (& $fail 'lifetime') }
    $hold = Resolve-MailboxHold ([bool]$Policy[$action].Critical) $false
    return @{ Ok = $true; Hold = $hold; Reason = ''; Action = $action; TaskId = $taskId; Seq = $seq; Critical = [bool]$Policy[$action].Critical }
}

function Ensure-MailboxState {
    if ($null -eq $script:State.mailbox) {
        $script:State.mailbox = @{ seen = @{}; rejected_seqs = @() }
    }
    if ($null -eq $script:State.mailbox.seen) { $script:State.mailbox.seen = @{} }
    if ($null -eq $script:State.mailbox.rejected_seqs) { $script:State.mailbox.rejected_seqs = @() }
}

function Test-MailboxSeqRejected {
    param([int]$Seq)
    Ensure-MailboxState
    foreach ($n in @($script:State.mailbox.rejected_seqs)) {
        if (("$n") -eq "$Seq") { return $true }
    }
    return $false
}

function Test-MailboxTaskSeen {
    param([string]$TaskId)
    Ensure-MailboxState
    $id = ('' + $TaskId).ToLowerInvariant()
    return $script:State.mailbox.seen.ContainsKey($id)
}

function Remember-Mailbox {
    param([string]$TaskId, [int]$Seq, [string]$Disposition, [string]$Reason)
    Ensure-MailboxState
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -match $script:MailboxTaskIdPattern) {
        $script:State.mailbox.seen[$id] = @{ seq = $Seq; disposition = $Disposition; reason = $Reason }
    }
    if ($Disposition -eq 'rejected') {
        $have = $false
        foreach ($n in @($script:State.mailbox.rejected_seqs)) {
            if (("$n") -eq "$Seq") { $have = $true }
        }
        if (-not $have) {
            $script:State.mailbox.rejected_seqs = @($script:State.mailbox.rejected_seqs) + $Seq
        }
    }
    Save-State $script:StatePath $script:State
}

function Get-MailboxSeen {
    param([string]$TaskId)
    Ensure-MailboxState
    $id = ('' + $TaskId).ToLowerInvariant()
    if (-not $script:State.mailbox.seen.ContainsKey($id)) { return $null }
    return $script:State.mailbox.seen[$id]
}

function Set-MailboxNextPoll {
    param([int]$Seconds)
    if ($Seconds -lt 5) { $Seconds = 5 }
    $script:MailboxNextPoll = [datetime]::UtcNow.AddSeconds($Seconds)
}

function Register-MailboxBackoff {
    param([string]$Reason)
    $sec = [int]$script:MailboxBackoffSec
    if ($sec -lt 5) { $sec = 5 }
    if ($sec -gt 60) { $sec = 60 }
    Write-Audit @{ ev = 'MAILBOX_BACKOFF'; reason = $Reason; wait_sec = $sec }
    Write-Host ("MAILBOX " + $Reason + " (next poll in " + $sec + "s)")
    Set-MailboxNextPoll $sec
    $next = $sec * 2
    if ($next -gt 60) { $next = 60 }
    $script:MailboxBackoffSec = $next
}

function Get-MailboxTimeoutMs {
    $raw = [Environment]::GetEnvironmentVariable('ARENA_MAILBOX_GH_TIMEOUT_MS')
    if ($raw -match '^[0-9]+$') {
        $n = [int]$raw
        if ($n -lt 1000) { return 1000 }
        if ($n -gt 60000) { return 60000 }
        return $n
    }
    return 30000
}

function Invoke-MailboxGh {
    param([string[]]$GhArgs)
    $timeout = Get-MailboxTimeoutMs
    $resp = Invoke-NativeTimed -Command 'gh' -ArgumentList $GhArgs -TimeoutMs $timeout
    if ($null -eq $resp) { return [pscustomobject]@{ Code = 1; Text = '' } }
    if ($resp.Text -and $resp.Text.Length -gt 1000000) {
        return [pscustomobject]@{ Code = 1; Text = '' }
    }
    return $resp
}

function Reject-MailboxTask {
    param([int]$Seq, [string]$TaskId, [string]$Reason)
    if (-not $script:MailboxRejectLogged) { $script:MailboxRejectLogged = @{} }
    $key = "$Seq|$Reason"
    $first = -not $script:MailboxRejectLogged.ContainsKey($key)
    if ($first) { $script:MailboxRejectLogged[$key] = $true }
    if (-not (Test-MailboxSeqRejected $Seq)) {
        Remember-Mailbox $TaskId $Seq 'rejected' $Reason
        Write-Audit @{ ev = 'MAILBOX_REJECTED'; seq = $Seq; reason = $Reason }
        $first = $true
    }
    if ($first) { Write-Host ("MAILBOX rejected [" + $Seq + "] " + $Reason) }
}

function Read-MailboxCandidate {
    # Fetches one file and its commit. Returns a hashtable; never executes.
    param([string]$Repo, [string]$Name, [int]$Seq)
    $fileResp = Invoke-MailboxGh @('api', ("repos/" + $Repo + "/contents/inbox/" + $Name))
    if ($fileResp.Code -eq 124) { return @{ Ok = $false; Reason = 'mailbox-timeout'; Fatal = $true } }
    if ($fileResp.Code -ne 0) { return @{ Ok = $false; Reason = 'mailbox-unavailable'; Fatal = $true } }
    $payload = $null
    try { $payload = $fileResp.Text | ConvertFrom-Json -ErrorAction Stop }
    catch { return @{ Ok = $false; Reason = 'bad-payload'; Fatal = $false } }
    $decoded = ConvertFrom-MailboxFilePayload $payload
    if (-not $decoded.Ok) { return @{ Ok = $false; Reason = $decoded.Reason; Fatal = $false } }
    $parsed = ConvertFrom-MailboxJson $decoded.Text
    if (-not $parsed.Ok) { return @{ Ok = $false; Reason = $parsed.Reason; Fatal = $false } }
    $commitResp = Invoke-MailboxGh @('api', ("repos/" + $Repo + "/commits"), '-f', ("path=inbox/" + $Name), '-f', 'per_page=1')
    if ($commitResp.Code -eq 124) { return @{ Ok = $false; Reason = 'mailbox-timeout'; Fatal = $true } }
    if ($commitResp.Code -ne 0) { return @{ Ok = $false; Reason = 'mailbox-unavailable'; Fatal = $true } }
    $commitParsed = $null
    try { $commitParsed = $commitResp.Text | ConvertFrom-Json -ErrorAction Stop }
    catch { return @{ Ok = $false; Reason = 'forged-author'; Fatal = $false } }
    $commit = Get-FirstObject $commitParsed
    $trustErr = Test-MailboxTrust $script:MailboxRepoMeta $commit $script:MailboxRepo $script:MailboxOwner
    if ($trustErr) { return @{ Ok = $false; Reason = $trustErr; Fatal = $false; Envelope = $parsed.Value } }
    return @{ Ok = $true; Reason = ''; Fatal = $false; Envelope = $parsed.Value; Text = $decoded.Text }
}

function Import-MailboxEnvelope {
    param($Envelope, [int]$FileSeq, [bool]$IsNext, [string]$RawText)
    $decision = Get-RemoteDecision $Envelope $script:ActionPolicy ([datetime]::UtcNow) $RawText
    $taskId = ''
    if ($null -ne $Envelope -and -not ($Envelope -is [System.Array])) {
        $en = @($Envelope.PSObject.Properties.Name)
        if ($en -contains 'task_id') { $taskId = ([string]$Envelope.task_id).ToLowerInvariant() }
    }
    if (-not $decision.Ok) {
        Reject-MailboxTask $FileSeq $taskId $decision.Reason
        return
    }
    if ($decision.Seq -ne $FileSeq) {
        Reject-MailboxTask $FileSeq $decision.TaskId 'seq-filename-mismatch'
        return
    }
    $approved = Test-MailboxApproved $decision.TaskId $script:ApproveDir
    $seen = Get-MailboxSeen $decision.TaskId
    if ($seen) {
        $disp = [string]$seen.disposition
        $seenSeq = 0
        if ($null -ne $seen.seq -and ("$($seen.seq)" -match '^[0-9]+$')) { $seenSeq = [int]$seen.seq }
        if ($seenSeq -ne $FileSeq) {
            Reject-MailboxTask $FileSeq $decision.TaskId 'duplicate-task'
            return
        }
        if ($disp -eq 'accepted') {
            $task = $script:State.tasks["$FileSeq"]
            $st = ''
            if ($task) { $st = [string]$task['state'] }
            $terminal = @('RUNNING', 'COMPLETED', 'PENDING_PUBLISH', 'PUBLISHED', 'FAILED', 'BLOCKED')
            $isTerminal = $false
            foreach ($x in $terminal) { if ($st -eq $x) { $isTerminal = $true } }
            if ($isTerminal) { return }
            $destSeen = Join-Path $script:InboxDir ("$FileSeq.json")
            if (Test-Path -LiteralPath $destSeen) { return }
            # Same seq, accepted, not started, file missing: crash before the inbox write.
        }
        elseif ($disp -eq 'held') {
            if (-not $approved -or -not $IsNext) { return }
        }
        else {
            return
        }
    }
    if (-not $IsNext) {
        Reject-MailboxTask $FileSeq $decision.TaskId 'old-seq'
        return
    }
    $dest = Join-Path $script:InboxDir ("$FileSeq.json")
    if (Test-Path -LiteralPath $dest) {
        Reject-MailboxTask $FileSeq $decision.TaskId 'duplicate-file'
        return
    }
    if (-not $approved) { $approved = Test-MailboxApproved $decision.TaskId $script:ApproveDir }
    $hold = Resolve-MailboxHold ([bool]$decision.Critical) $approved
    $created = Get-MailboxRawField $RawText 'created_at'
    $expires = Get-MailboxRawField $RawText 'expires_at'
    $json = New-MailboxEnvelopeJson -Seq $FileSeq -Action $decision.Action -TaskId $decision.TaskId -Created $created -Expires $expires
    if ([string]::IsNullOrWhiteSpace($json)) {
        Reject-MailboxTask $FileSeq $decision.TaskId 'bad-json'
        return
    }
    if ($hold) {
        if (-not (Test-Path -LiteralPath $script:HeldDir)) {
            New-Item -ItemType Directory -Path $script:HeldDir -Force | Out-Null
        }
        $held = Join-Path $script:HeldDir ($decision.TaskId + '.json')
        if (-not (Test-Path -LiteralPath $held)) { Write-FileAtomic $held $json }
        Remember-Mailbox $decision.TaskId $FileSeq 'held' 'critical-held'
        Write-Audit @{ ev = 'MAILBOX_HELD'; seq = $FileSeq; action = $decision.Action; reason = 'critical-held' }
        Write-Host ("MAILBOX held [" + $FileSeq + "] " + $decision.Action)
        return
    }
    Remember-Mailbox $decision.TaskId $FileSeq 'accepted' ''
    if (-not (Test-Path -LiteralPath $dest)) { Write-FileAtomic $dest $json }
    Write-Audit @{ ev = 'MAILBOX_ACCEPTED'; seq = $FileSeq; action = $decision.Action }
    Write-Host ("MAILBOX accepted [" + $FileSeq + "] " + $decision.Action)
}

function Invoke-MailboxSync {
    # One poll. Never sleeps. Never executes an action. Local inbox keeps working
    # when GitHub is down.
    if (-not $script:MailboxEnabled) { return }
    $now = [datetime]::UtcNow
    if (-not $script:Once -and $script:MailboxNextPoll -gt $now) { return }
    Ensure-MailboxState
    if ($null -eq $script:ActionPolicy) { $script:ActionPolicy = Get-ActionPolicyFromTable }
    $repo = $script:MailboxRepo
    $repoResp = Invoke-MailboxGh @('api', ("repos/" + $repo))
    if ($repoResp.Code -eq 124) { Register-MailboxBackoff 'mailbox-timeout'; return }
    if ($repoResp.Code -ne 0) {
        Register-MailboxBackoff 'mailbox-unavailable'
        return
    }
    $repoMeta = $null
    try { $repoMeta = $repoResp.Text | ConvertFrom-Json -ErrorAction Stop }
    catch { Register-MailboxBackoff 'mailbox-unavailable'; return }
    $script:MailboxRepoMeta = $repoMeta
    if ($null -eq $repoMeta -or $repoMeta -is [System.Array] -or @($repoMeta.PSObject.Properties.Name) -notcontains 'private' -or $repoMeta.private -ne $true) {
        Write-Audit @{ ev = 'MAILBOX_REFUSED'; reason = 'not-private' }
        Write-Host 'MAILBOX refused not-private'
        Set-MailboxNextPoll $script:MailboxPollSec
        return
    }
    if (-not ([string]$repoMeta.full_name).Equals($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Audit @{ ev = 'MAILBOX_REFUSED'; reason = 'repo-mismatch' }
        Write-Host 'MAILBOX refused repo-mismatch'
        Set-MailboxNextPoll $script:MailboxPollSec
        return
    }
    $list = Invoke-MailboxGh @('api', ("repos/" + $repo + "/contents/inbox"))
    if ($list.Code -eq 124) { Register-MailboxBackoff 'mailbox-timeout'; return }
    if ($list.Code -ne 0) {
        if ($list.Text -match 'Not Found') {
            $script:MailboxBackoffSec = $script:MailboxPollSec
            Set-MailboxNextPoll $script:MailboxPollSec
            return
        }
        Register-MailboxBackoff 'mailbox-unavailable'
        return
    }
    $listObj = $null
    try { $listObj = $list.Text | ConvertFrom-Json -ErrorAction Stop }
    catch { Register-MailboxBackoff 'mailbox-unavailable'; return }
    $names = @(Get-MailboxFileNames $listObj | Sort-Object { [int]($_.Split('.')[0]) })
    $expected = [int]$script:State.last_seq + 1
    $inspected = 0
    foreach ($name in $names) {
        $seq = [int]($name.Split('.')[0])
        if ($seq -gt $expected) {
            if (-not $script:MailboxGapLogged.ContainsKey("$seq")) {
                $script:MailboxGapLogged["$seq"] = $true
                Write-Audit @{ ev = 'MAILBOX_GAP'; have = [int]$script:State.last_seq; saw = $seq }
                Write-Host ("MAILBOX GAP: expecting " + $expected + ", saw " + $seq)
            }
            break
        }
        if ($seq -lt $expected) {
            $doneTask = $script:State.tasks["$seq"]
            if ($doneTask) {
                $doneState = [string]$doneTask['state']
                $doneNames = @('RUNNING', 'COMPLETED', 'PENDING_PUBLISH', 'PUBLISHED', 'FAILED', 'BLOCKED')
                $done = $false
                foreach ($x in $doneNames) { if ($doneState -eq $x) { $done = $true } }
                if ($done) { continue }
            }
            if (Test-MailboxSeqRejected $seq) { continue }
            if ($inspected -ge 20) { continue }
        }
        $inspected++
        $cand = Read-MailboxCandidate $repo $name $seq
        if ($cand.Fatal) { Register-MailboxBackoff $cand.Reason; return }
        if (-not $cand.Ok) {
            $tid = ''
            if ($cand.Envelope) {
                $en = @($cand.Envelope.PSObject.Properties.Name)
                if ($en -contains 'task_id') { $tid = [string]$cand.Envelope.task_id }
            }
            Reject-MailboxTask $seq $tid $cand.Reason
            continue
        }
        $isNext = ($seq -eq $expected)
        Import-MailboxEnvelope $cand.Envelope $seq $isNext $cand.Text
        if ($isNext) { break }
    }
    $script:MailboxBackoffSec = $script:MailboxPollSec
    Set-MailboxNextPoll $script:MailboxPollSec
}
