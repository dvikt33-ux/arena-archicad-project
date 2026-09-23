# mailbox.ps1 — remote intake for Arena Bridge v2.
#
# Transport and trust are separate. A private GitHub repository is only the
# drop box. The JSON file is not trusted, and neither is the commit object.
# The allow decision is the repository permission model: private, not a fork,
# exact name, owner dvikt33-ux, no extra push/admin/maintain writer, no deploy
# keys. If that proof cannot be read, the poll is refused and nothing runs.
# There is no signature field, because the model must not hold a local secret.
# Limit: a compromised owner account can still enqueue the four read-only actions.
# Paging collaborators and deploy keys does not prove an exclusive writer.
# GitHub Apps, installation tokens, and Actions credentials are not in those lists.
# Current permissions do not prove who wrote an already-present file.
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
    $forcedHold = @{}
    $holdRaw = [Environment]::GetEnvironmentVariable('ARENA_MAILBOX_HOLD_ACTIONS')
    if (-not [string]::IsNullOrWhiteSpace($holdRaw)) {
        foreach ($part in ($holdRaw -split ',')) {
            $token = $part.Trim().ToUpperInvariant()
            if ($token -match '^[A-Z0-9_]+$') { $forcedHold[$token] = $true }
        }
    }
    $policy = @{}
    foreach ($id in @($script:ActionIds)) {
        if (-not $script:Actions.ContainsKey($id)) { continue }
        $a = $script:Actions[$id]
        $names = @()
        if ($a.ContainsKey('ArgNames') -and $null -ne $a.ArgNames) { $names = @($a.ArgNames) }
        $critical = $true
        if ($a.ContainsKey('Critical')) { $critical = [bool]$a.Critical }
        # Test hook only. Empty unless a smoke sets it. Does not add an action.
        if ($forcedHold.ContainsKey($id)) { $critical = $true }
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
        if (-not (Test-MailboxRemoteName $name)) { continue }
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

function ConvertFrom-ApiList {
    # GitHub list endpoints. A one-element array is unwrapped by ConvertFrom-Json.
    # Empty text is unreadable. "[]" is a real empty list.
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return @{ Ok = $false; Items = @() } }
    $trim = $Text.Trim()
    if ($trim -eq '[]') { return @{ Ok = $true; Items = @() } }
    $obj = $null
    try { $obj = $trim | ConvertFrom-Json -ErrorAction Stop }
    catch { return @{ Ok = $false; Items = @() } }
    if ($null -eq $obj) { return @{ Ok = $false; Items = @() } }
    if ($obj -is [string] -or $obj -is [bool] -or $obj -is [int] -or $obj -is [long] -or $obj -is [double] -or $obj -is [decimal]) {
        return @{ Ok = $false; Items = @() }
    }
    if ($obj -is [System.Array]) { return @{ Ok = $true; Items = @($obj) } }
    return @{ Ok = $true; Items = @($obj) }
}

function Write-MailboxRefuse {
    param([string]$Reason)
    Write-Audit @{ ev = 'MAILBOX_REFUSED'; reason = $Reason }
    Write-Host ("MAILBOX refused " + $Reason)
    Set-MailboxNextPoll $script:MailboxPollSec
}

function Test-MailboxPermission {
    # GitHub is transport. This is the allow decision, and it fails closed.
    # Commit metadata is not an input. A missing or unreadable proof refuses.
    # Limit: a compromised owner account can still enqueue the four read-only
    # actions. This function does not pretend otherwise.
    # The caller must pass every collaborator and key page. A complete page
    # list is still not an exclusive-writer proof and does not prove provenance.
    param($RepoMeta, $Collaborators, $Keys, [string]$ExpectedRepo, [string]$ExpectedOwner)
    if ($null -eq $RepoMeta -or $RepoMeta -is [System.Array]) { return 'not-private' }
    $names = @($RepoMeta.PSObject.Properties.Name)
    if ($names -notcontains 'private' -or $RepoMeta.private -isnot [bool] -or $RepoMeta.private -ne $true) {
        return 'not-private'
    }
    if ($names -notcontains 'fork' -or $RepoMeta.fork -isnot [bool]) { return 'fork-unknown' }
    if ($RepoMeta.fork -eq $true) { return 'fork' }
    if ($names -notcontains 'full_name') { return 'repo-mismatch' }
    if (-not ([string]$RepoMeta.full_name).Equals($ExpectedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
        return 'repo-mismatch'
    }
    if ($names -notcontains 'owner' -or $null -eq $RepoMeta.owner -or $RepoMeta.owner -is [System.Array]) {
        return 'owner-mismatch'
    }
    $on = @($RepoMeta.owner.PSObject.Properties.Name)
    if ($on -notcontains 'login') { return 'owner-mismatch' }
    $ownerLogin = [string]$RepoMeta.owner.login
    if (-not $ownerLogin.Equals($ExpectedOwner, [System.StringComparison]::OrdinalIgnoreCase)) {
        return 'owner-mismatch'
    }
    if ($null -eq $Collaborators) { return 'collaborators-unreadable' }
    foreach ($person in @($Collaborators)) {
        if ($null -eq $person) { return 'collaborators-unreadable' }
        $pn = @($person.PSObject.Properties.Name)
        if ($pn -notcontains 'login') { return 'collaborators-unreadable' }
        $login = [string]$person.login
        $isOwner = $login.Equals($ExpectedOwner, [System.StringComparison]::OrdinalIgnoreCase)
        if ($pn -notcontains 'permissions' -or $null -eq $person.permissions) {
            return 'collaborators-unreadable'
        }
        $perms = $person.permissions
        if ($perms -is [System.Array] -or $perms -is [string]) { return 'collaborators-unreadable' }
        $pp = @($perms.PSObject.Properties.Name)
        foreach ($level in @('admin', 'maintain', 'push')) {
            if ($pp -notcontains $level) { return 'collaborators-unreadable' }
            $flag = $perms.$level
            if ($flag -isnot [bool]) { return 'collaborators-unreadable' }
            if ($flag -and -not $isOwner) { return 'extra-writer' }
        }
    }
    if ($null -eq $Keys) { return 'keys-unreadable' }
    $keyCount = 0
    foreach ($k in @($Keys)) {
        if ($null -ne $k) { $keyCount++ }
    }
    if ($keyCount -gt 0) { return 'deploy-key' }
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
        $script:State.mailbox = @{ seen = @{}; rejected_seqs = @(); remote_files = @{} }
    }
    if ($null -eq $script:State.mailbox.seen) { $script:State.mailbox.seen = @{} }
    if ($null -eq $script:State.mailbox.rejected_seqs) { $script:State.mailbox.rejected_seqs = @() }
    if ($null -eq $script:State.mailbox.remote_files) { $script:State.mailbox.remote_files = @{} }
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
    param(
        [string]$TaskId,
        [int]$Seq,
        [string]$Disposition,
        [string]$Reason,
        [string]$Action = '',
        [string]$ContentSha = '',
        [string]$BodySha = ''
    )
    Ensure-MailboxState
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -match $script:MailboxTaskIdPattern) {
        $prev = $null
        if ($script:State.mailbox.seen.ContainsKey($id)) { $prev = $script:State.mailbox.seen[$id] }
        $keepAction = $Action
        $keepContent = ''
        $keepBody = ''
        if (-not [string]::IsNullOrWhiteSpace($ContentSha)) { $keepContent = $ContentSha.ToLowerInvariant() }
        if (-not [string]::IsNullOrWhiteSpace($BodySha)) { $keepBody = $BodySha.ToLowerInvariant() }
        if ($null -ne $prev) {
            if ([string]::IsNullOrWhiteSpace($keepAction) -and $prev.ContainsKey('action')) { $keepAction = [string]$prev.action }
            if ([string]::IsNullOrWhiteSpace($keepContent) -and $prev.ContainsKey('content_sha')) { $keepContent = [string]$prev.content_sha }
            if ([string]::IsNullOrWhiteSpace($keepBody) -and $prev.ContainsKey('body_sha')) { $keepBody = [string]$prev.body_sha }
        }
        $script:State.mailbox.seen[$id] = @{
            seq         = $Seq
            disposition = $Disposition
            reason      = $Reason
            action      = $keepAction
            content_sha = $keepContent
            body_sha    = $keepBody
        }
    }
    # A non-numeric remote name has no execution slot. Do not record seq 0 as rejected.
    if ($Disposition -eq 'rejected' -and $Seq -ge 1) {
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
    param([int]$Seq, [string]$TaskId, [string]$Reason, [string]$Label = '')
    if (-not $script:MailboxRejectLogged) { $script:MailboxRejectLogged = @{} }
    $shown = "$Seq"
    if ($Seq -lt 1 -and -not [string]::IsNullOrWhiteSpace($Label)) { $shown = $Label }
    $key = "$shown|$Reason"
    if (-not [string]::IsNullOrWhiteSpace($Label)) { $key = "$Label|$Reason" }
    $first = -not $script:MailboxRejectLogged.ContainsKey($key)
    if ($first) { $script:MailboxRejectLogged[$key] = $true }
    $already = $false
    if ($Seq -ge 1) { $already = Test-MailboxSeqRejected $Seq }
    if (-not $already) {
        Remember-Mailbox $TaskId $Seq 'rejected' $Reason
        Write-Audit @{ ev = 'MAILBOX_REJECTED'; seq = $Seq; reason = $Reason }
        $first = $true
    }
    if ($first) { Write-Host ("MAILBOX rejected [" + $shown + "] " + $Reason) }
}

function Read-MailboxCandidate {
    # Fetches one file. Does not ask who committed it and does not execute.
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
    return @{ Ok = $true; Reason = ''; Fatal = $false; Envelope = $parsed.Value; Text = $decoded.Text }
}

function Test-MailboxRemoteName {
    # Allowlist for inbox names only. Never a path from the API, never archive/.
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name -match '^[1-9][0-9]{0,8}\.json$') { return $true }
    if ($Name -match '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$') { return $true }
    return $false
}

function Test-MailboxBlobSha {
    param([string]$Sha)
    if ([string]::IsNullOrWhiteSpace($Sha)) { return $false }
    return ($Sha -match '^[0-9a-f]{40}$')
}

function Get-MailboxListWarnAt {
    # GitHub contents listings stop at 1000. A lower test threshold cannot raise that cap.
    $raw = [Environment]::GetEnvironmentVariable('ARENA_MAILBOX_LIST_WARN_AT')
    if ($raw -match '^[0-9]+$') {
        $n = [int]$raw
        if ($n -lt 1) { return 1 }
        if ($n -gt 1000) { return 1000 }
        return $n
    }
    return 1000
}

function Invoke-MailboxFault {
    # Local process hook only. A task field is never read here.
    param([string]$Point)
    $raw = [Environment]::GetEnvironmentVariable('ARENA_MAILBOX_FAULT')
    if ([string]::IsNullOrWhiteSpace($raw)) { return }
    if ($raw -eq $Point) { throw ("mailbox-fault:" + $Point) }
}

function Get-MailboxInboxEntries {
    # Names and listing shas only. The API path field is ignored.
    param($Parsed)
    $list = New-Object System.Collections.Generic.List[object]
    if ($null -eq $Parsed) { return @($list.ToArray()) }
    $items = @()
    if ($Parsed -is [System.Array]) { $items = @($Parsed) }
    else {
        $n = @($Parsed.PSObject.Properties.Name)
        if ($n -contains 'message' -and $n -notcontains 'name') { return @($list.ToArray()) }
        if ($n -contains 'name') { $items = @($Parsed) }
        else { return @($list.ToArray()) }
    }
    foreach ($it in $items) {
        if ($null -eq $it) { continue }
        $pn = @($it.PSObject.Properties.Name)
        if ($pn -notcontains 'name' -or $pn -notcontains 'type') { continue }
        if ([string]$it.type -ne 'file') { continue }
        $name = [string]$it.name
        if (-not (Test-MailboxRemoteName $name)) { continue }
        $sha = ''
        if ($pn -contains 'sha') { $sha = ([string]$it.sha).ToLowerInvariant() }
        $list.Add([pscustomobject]@{ Name = $name; Sha = $sha }) | Out-Null
    }
    return @($list.ToArray())
}

function Get-MailboxSortedEntries {
    param($Entries)
    $numeric = New-Object System.Collections.Generic.List[object]
    $other = New-Object System.Collections.Generic.List[object]
    foreach ($e in @($Entries)) {
        if ($null -eq $e) { continue }
        $name = [string]$e.Name
        if ($name -match '^[1-9][0-9]{0,8}\.json$') { $numeric.Add($e) | Out-Null }
        else { $other.Add($e) | Out-Null }
    }
    $numericSorted = @($numeric.ToArray() | Sort-Object { [int]([string]$_.Name).Split('.')[0] })
    $otherSorted = @($other.ToArray() | Sort-Object { [string]$_.Name })
    $result = New-Object System.Collections.Generic.List[object]
    foreach ($e in @($numericSorted)) { if ($null -ne $e) { $result.Add($e) | Out-Null } }
    foreach ($e in @($otherSorted)) { if ($null -ne $e) { $result.Add($e) | Out-Null } }
    return @($result.ToArray())
}

function Invoke-MailboxPagedList {
    # Complete pages or refuse. Twenty full pages is an incomplete scan.
    # This is not a proof that no other writer exists.
    param([string]$Kind)
    $reason = 'collaborators-unreadable'
    $endpoint = 'collaborators'
    if ($Kind -eq 'keys') {
        $reason = 'keys-unreadable'
        $endpoint = 'keys'
    }
    elseif ($Kind -ne 'collaborators') {
        return @{ Ok = $false; Reason = 'collaborators-unreadable'; Items = @(); Timeout = $false }
    }
    $all = New-Object System.Collections.Generic.List[object]
    $page = 1
    while ($page -le 20) {
        $resp = Invoke-MailboxGh @(
            'api', '-X', 'GET',
            ('repos/' + $script:MailboxRepo + '/' + $endpoint),
            '-f', 'per_page=100',
            '-f', ('page=' + $page)
        )
        if ($null -eq $resp) { return @{ Ok = $false; Reason = $reason; Items = @(); Timeout = $false } }
        if ($resp.Code -eq 124) { return @{ Ok = $false; Reason = 'mailbox-timeout'; Items = @(); Timeout = $true } }
        if ($resp.Code -ne 0) { return @{ Ok = $false; Reason = $reason; Items = @(); Timeout = $false } }
        $parsed = ConvertFrom-ApiList $resp.Text
        if (-not $parsed.Ok) { return @{ Ok = $false; Reason = $reason; Items = @(); Timeout = $false } }
        $count = 0
        foreach ($it in @($parsed.Items)) {
            if ($null -eq $it) { continue }
            $all.Add($it) | Out-Null
            $count++
        }
        if ($count -lt 100) {
            return @{ Ok = $true; Reason = ''; Items = @($all.ToArray()); Timeout = $false }
        }
        $page++
    }
    return @{ Ok = $false; Reason = $reason; Items = @(); Timeout = $false }
}

function Remember-MailboxRemote {
    param([string]$Name, [string]$Sha, [string]$Disposition, [string]$TaskId, [int]$ExecSeq)
    Ensure-MailboxState
    if (-not (Test-MailboxRemoteName $Name)) { return }
    # $Sha is the parameter. PowerShell variables are case-insensitive, so a
    # local $sha would wipe the parameter before it is copied.
    $blob = ''
    if (-not [string]::IsNullOrWhiteSpace($Sha)) { $blob = $Sha.ToLowerInvariant() }
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -notmatch $script:MailboxTaskIdPattern) { $id = '' }
    $script:State.mailbox.remote_files[$Name] = @{
        sha         = $blob
        disposition = $Disposition
        task_id     = $id
        exec_seq    = $ExecSeq
    }
    Save-State $script:StatePath $script:State
}

function Test-MailboxRemoteSettled {
    # Same listing sha plus a durable terminal disposition. Missing sha is not settled.
    param([string]$Name, [string]$Sha)
    Ensure-MailboxState
    if (-not (Test-MailboxRemoteName $Name)) { return $false }
    if (-not $script:State.mailbox.remote_files.ContainsKey($Name)) { return $false }
    $rec = $script:State.mailbox.remote_files[$Name]
    $stored = ''
    if ($null -ne $rec -and $rec.ContainsKey('sha')) { $stored = [string]$rec.sha }
    $listed = ''
    if (-not [string]::IsNullOrWhiteSpace($Sha)) { $listed = $Sha.ToLowerInvariant() }
    if ([string]::IsNullOrWhiteSpace($listed) -or [string]::IsNullOrWhiteSpace($stored)) { return $false }
    if ($listed -ne $stored) { return $false }
    $disp = [string]$rec.disposition
    if ($disp -eq 'rejected' -or $disp -eq 'duplicate') { return $true }
    if ($disp -eq 'held') {
        # Held is not terminal. Do not offer it to remote cleanup, approved or not.
        return $false
    }
    if ($disp -eq 'accepted') {
        $seq = 0
        if ($rec.ContainsKey('exec_seq') -and ("$($rec.exec_seq)" -match '^[0-9]+$')) { $seq = [int]$rec.exec_seq }
        if ($seq -lt 1) { return $false }
        $dest = Join-Path $script:InboxDir ("$seq.json")
        if (Test-Path -LiteralPath $dest) { return $true }
        $task = $script:State.tasks["$seq"]
        if ($task) {
            $st = [string]$task['state']
            foreach ($x in @('RUNNING', 'COMPLETED', 'PENDING_PUBLISH', 'PUBLISHED', 'FAILED', 'BLOCKED', 'REJECTED')) {
                if ($st -eq $x) { return $true }
            }
        }
        return $false
    }
    return $false
}

function Invoke-MailboxRemoteCleanup {
    # Best-effort. Never archive/. Never a path taken from the task or the API.
    param([string]$Name, [string]$Sha)
    if (-not (Test-MailboxRemoteName $Name)) { return $false }
    if ($Name -match '\.\.' -or $Name -match '[\\/]') { return $false }
    $blob = ''
    if (-not [string]::IsNullOrWhiteSpace($Sha)) { $blob = $Sha.ToLowerInvariant() }
    if (-not (Test-MailboxBlobSha $blob)) { return $false }
    $endpoint = 'repos/' + $script:MailboxRepo + '/contents/inbox/' + $Name
    if ($endpoint -notmatch '^repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/contents/inbox/[0-9a-z.-]+\.json$') { return $false }
    $resp = Invoke-MailboxGh @(
        'api', '--method', 'DELETE',
        $endpoint,
        '-f', 'message=retire mailbox task',
        '-f', ('sha=' + $blob)
    )
    if ($null -eq $resp -or $resp.Code -ne 0) {
        Write-Audit @{ ev = 'MAILBOX_CLEANUP_FAILED'; name = $Name }
        return $false
    }
    Write-Audit @{ ev = 'MAILBOX_CLEANUP'; name = $Name }
    return $true
}

function Get-MailboxBodySha {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $hasher.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
    }
    finally { $hasher.Dispose() }
}

function Get-MailboxNameTaskId {
    param([string]$Name)
    if ($Name -match '^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.json$') {
        return $Matches[1]
    }
    return ''
}

function Save-MailboxAcceptedBody {
    # Freeze the envelope that was accepted. A later remote edit must not replace it.
    param([string]$TaskId, [string]$RawText)
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -notmatch $script:MailboxTaskIdPattern) { return $false }
    if ([string]::IsNullOrWhiteSpace($RawText)) { return $false }
    if ([string]::IsNullOrWhiteSpace($script:ArenaRoot)) { return $false }
    $dir = Join-Path $script:ArenaRoot 'mailbox-accepted'
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $path = Join-Path $dir ($id + '.json')
    if (Test-Path -LiteralPath $path) {
        $seen = Get-MailboxSeen $id
        if ($seen -and [string]$seen.disposition -eq 'accepted') { return $true }
    }
    Write-FileAtomic $path $RawText
    return (Test-Path -LiteralPath $path)
}

function Read-MailboxAcceptedBody {
    param([string]$TaskId)
    $fail = @{ Ok = $false; Text = ''; Envelope = $null }
    $id = ('' + $TaskId).ToLowerInvariant()
    if ($id -notmatch $script:MailboxTaskIdPattern) { return $fail }
    if ([string]::IsNullOrWhiteSpace($script:ArenaRoot)) { return $fail }
    $path = Join-Path (Join-Path $script:ArenaRoot 'mailbox-accepted') ($id + '.json')
    if (-not (Test-Path -LiteralPath $path)) { return $fail }
    $text = ''
    try { $text = [System.IO.File]::ReadAllText($path) } catch { return $fail }
    $parsed = ConvertFrom-MailboxJson $text
    if (-not $parsed.Ok) { return $fail }
    return @{ Ok = $true; Text = $text; Envelope = $parsed.Value }
}

function Find-MailboxOwnedReservation {
    # The next gap, only if this process reserved it and the lease is still live.
    param([string]$ArenaRoot, [int]$ExpectedSeq)
    if ($ExpectedSeq -lt 1 -or [string]::IsNullOrWhiteSpace($ArenaRoot)) { return 0 }
    $path = Join-Path (Join-Path $ArenaRoot 'reservations') ("$ExpectedSeq.json")
    if (-not (Test-Path -LiteralPath $path)) { return 0 }
    $raw = ''
    try { $raw = [System.IO.File]::ReadAllText($path) } catch { return 0 }
    if ($raw -notmatch '"producer"\s*:\s*"mailbox"') { return 0 }
    if (Test-ReservationExpired -Path $path -LeaseSeconds (Get-SeqLeaseSeconds)) { return 0 }
    return $ExpectedSeq
}

function Import-MailboxEnvelope {
    # Remote filename is not the execution slot. Disposition is durable before
    # any remote delete. A reappearing task_id does not allocate a second slot.
    # Once accepted, the stored envelope is the task. Current time and a later
    # remote body do not reopen that decision.
    param($Envelope, [int]$FileSeq, [string]$RawText, [string]$RemoteName = '', [string]$RemoteSha = '')
    $earlyId = ''
    if ($null -ne $Envelope -and -not ($Envelope -is [System.Array])) {
        $earlyNames = @($Envelope.PSObject.Properties.Name)
        if ($earlyNames -contains 'task_id') {
            $earlyId = ([string]$Envelope.task_id).Trim().ToLowerInvariant()
        }
    }
    $nameId = Get-MailboxNameTaskId $RemoteName
    if ($nameId -ne '') {
        $seenByName = Get-MailboxSeen $nameId
        if ($seenByName -and [string]$seenByName.disposition -eq 'accepted') {
            $earlyId = $nameId
        }
    }
    if ($earlyId -match $script:MailboxTaskIdPattern) {
        $seenEarly = Get-MailboxSeen $earlyId
        if ($seenEarly -and [string]$seenEarly.disposition -eq 'rejected') {
            Remember-MailboxRemote $RemoteName $RemoteSha 'rejected' $earlyId 0
            Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
            return
        }
    }
    $recoverAccepted = $false
    $decision = $null
    $seenForAccept = $null
    if ($earlyId -match $script:MailboxTaskIdPattern) {
        $seenForAccept = Get-MailboxSeen $earlyId
    }
    if ($seenForAccept -and [string]$seenForAccept.disposition -eq 'accepted') {
        $recoverAccepted = $true
        $stored = Read-MailboxAcceptedBody $earlyId
        if (-not $stored.Ok) {
            Write-Audit @{ ev = 'MAILBOX_RETRY'; reason = 'missing-accepted-body' }
            Write-Host ("MAILBOX retry [" + $RemoteName + "] missing-accepted-body")
            return
        }
        $createdBound = ConvertFrom-MailboxTime (Get-MailboxRawField $stored.Text 'created_at')
        $when = [datetime]::UtcNow
        if ($null -ne $createdBound) { $when = $createdBound }
        $decision = Get-RemoteDecision $stored.Envelope $script:ActionPolicy $when $stored.Text
        if (-not $decision.Ok) {
            Write-Audit @{ ev = 'MAILBOX_RETRY'; reason = 'accepted-body-invalid' }
            Write-Host ("MAILBOX retry [" + $RemoteName + "] accepted-body-invalid")
            return
        }
        $listed = ''
        if (-not [string]::IsNullOrWhiteSpace($RemoteSha)) { $listed = $RemoteSha.ToLowerInvariant() }
        $pinned = ''
        if ($seenForAccept.ContainsKey('content_sha')) { $pinned = ([string]$seenForAccept.content_sha).ToLowerInvariant() }
        $pinnedBody = ''
        if ($seenForAccept.ContainsKey('body_sha')) { $pinnedBody = ([string]$seenForAccept.body_sha).ToLowerInvariant() }
        $remoteBody = ''
        if (-not [string]::IsNullOrWhiteSpace($RawText)) { $remoteBody = Get-MailboxBodySha $RawText }
        $changed = $false
        if ($listed -ne '' -and $pinned -ne '' -and $listed -ne $pinned) { $changed = $true }
        if ($remoteBody -ne '' -and $pinnedBody -ne '' -and $remoteBody -ne $pinnedBody) { $changed = $true }
        if ($changed) {
            Write-Audit @{ ev = 'MAILBOX_CONTENT_CHANGED'; task_id = $earlyId }
            Write-Host ("MAILBOX accepted-content-changed [" + $RemoteName + "]")
        }
        $RawText = $stored.Text
    }
    else {
        $decision = Get-RemoteDecision $Envelope $script:ActionPolicy ([datetime]::UtcNow) $RawText
        if (-not $decision.Ok) {
            Reject-MailboxTask -Seq $FileSeq -TaskId $earlyId -Reason $decision.Reason -Label $RemoteName
            Remember-MailboxRemote $RemoteName $RemoteSha 'rejected' $earlyId 0
            Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
            return
        }
    }
    $taskId = $earlyId
    if ($taskId -notmatch $script:MailboxTaskIdPattern) { $taskId = $decision.TaskId }
    $numericName = $RemoteName -match '^[1-9][0-9]{0,8}\.json$'
    if (-not $recoverAccepted -and $numericName -and $decision.Seq -ne $FileSeq) {
        Reject-MailboxTask -Seq $FileSeq -TaskId $decision.TaskId -Reason 'seq-filename-mismatch' -Label $RemoteName
        Remember-MailboxRemote $RemoteName $RemoteSha 'rejected' $decision.TaskId 0
        Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
        return
    }
    $approved = Test-MailboxApproved $decision.TaskId $script:ApproveDir
    $seen = Get-MailboxSeen $decision.TaskId
    $resumeAlloc = $false
    if ($seen) {
        $disp = [string]$seen.disposition
        $seenSeq = 0
        if ($null -ne $seen.seq -and ("$($seen.seq)" -match '^[0-9]+$')) { $seenSeq = [int]$seen.seq }
        if ($disp -eq 'rejected') {
            Remember-MailboxRemote $RemoteName $RemoteSha 'rejected' $decision.TaskId 0
            Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
            return
        }
        if ($disp -eq 'accepted') {
            $task = $null
            if ($seenSeq -gt 0) { $task = $script:State.tasks["$seenSeq"] }
            $st = ''
            if ($task) { $st = [string]$task['state'] }
            $terminal = @('RUNNING', 'COMPLETED', 'PENDING_PUBLISH', 'PUBLISHED', 'FAILED', 'BLOCKED', 'REJECTED')
            $isTerminal = $false
            foreach ($x in $terminal) { if ($st -eq $x) { $isTerminal = $true } }
            $destSeen = ''
            if ($seenSeq -gt 0) { $destSeen = Join-Path $script:InboxDir ("$seenSeq.json") }
            $haveFile = ($destSeen -ne '' -and (Test-Path -LiteralPath $destSeen))
            if ($isTerminal -or $haveFile) {
                if ($numericName -and $seenSeq -ne $FileSeq) {
                    if (-not $script:MailboxRejectLogged) { $script:MailboxRejectLogged = @{} }
                    $key = "$FileSeq|duplicate-task"
                    if (-not $script:MailboxRejectLogged.ContainsKey($key)) {
                        $script:MailboxRejectLogged[$key] = $true
                        Write-Host ("MAILBOX rejected [" + $FileSeq + "] duplicate-task")
                    }
                }
                elseif (-not $numericName) {
                    if (-not $script:MailboxRejectLogged) { $script:MailboxRejectLogged = @{} }
                    $key = "$RemoteName|duplicate-task"
                    if (-not $script:MailboxRejectLogged.ContainsKey($key)) {
                        $script:MailboxRejectLogged[$key] = $true
                        Write-Host ("MAILBOX rejected [" + $RemoteName + "] duplicate-task")
                    }
                }
                Remember-MailboxRemote $RemoteName $RemoteSha 'duplicate' $decision.TaskId $seenSeq
                Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
                return
            }
            if ($seenSeq -gt 0) {
                $createdRestore = Get-MailboxRawField $RawText 'created_at'
                $expiresRestore = Get-MailboxRawField $RawText 'expires_at'
                $jsonRestore = New-MailboxEnvelopeJson -Seq $seenSeq -Action $decision.Action -TaskId $decision.TaskId -Created $createdRestore -Expires $expiresRestore
                if (-not [string]::IsNullOrWhiteSpace($jsonRestore)) {
                    Write-FileAtomic $destSeen $jsonRestore
                    Invoke-MailboxFault 'after-write'
                    Complete-TaskReservation -ArenaRoot $script:ArenaRoot -Seq $seenSeq
                    Remember-MailboxRemote $RemoteName $RemoteSha 'accepted' $decision.TaskId $seenSeq
                    Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
                    Invoke-MailboxFault 'after-cleanup'
                }
                return
            }
            $resumeAlloc = $true
        }
        elseif ($disp -eq 'held') {
            if (-not $approved) {
                Remember-MailboxRemote $RemoteName $RemoteSha 'held' $decision.TaskId 0
                return
            }
        }
        else {
            return
        }
    }
    if (-not $approved) { $approved = Test-MailboxApproved $decision.TaskId $script:ApproveDir }
    $hold = Resolve-MailboxHold ([bool]$decision.Critical) $approved
    $created = Get-MailboxRawField $RawText 'created_at'
    $expires = Get-MailboxRawField $RawText 'expires_at'
    if ($hold) {
        if (-not (Test-Path -LiteralPath $script:HeldDir)) {
            New-Item -ItemType Directory -Path $script:HeldDir -Force | Out-Null
        }
        $heldSeq = [int]$decision.Seq
        if ($heldSeq -lt 1) { $heldSeq = 1 }
        $heldJson = New-MailboxEnvelopeJson -Seq $heldSeq -Action $decision.Action -TaskId $decision.TaskId -Created $created -Expires $expires
        if ([string]::IsNullOrWhiteSpace($heldJson)) {
            Reject-MailboxTask -Seq $FileSeq -TaskId $decision.TaskId -Reason 'bad-json' -Label $RemoteName
            Remember-MailboxRemote $RemoteName $RemoteSha 'rejected' $decision.TaskId 0
            Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
            return
        }
        $held = Join-Path $script:HeldDir ($decision.TaskId + '.json')
        if (-not (Test-Path -LiteralPath $held)) { Write-FileAtomic $held $heldJson }
        $heldSlot = $FileSeq
        if ($heldSlot -lt 1) { $heldSlot = $heldSeq }
        Remember-Mailbox $decision.TaskId $heldSlot 'held' 'critical-held'
        Remember-MailboxRemote $RemoteName $RemoteSha 'held' $decision.TaskId $heldSlot
        Write-Audit @{ ev = 'MAILBOX_HELD'; seq = $heldSlot; action = $decision.Action; reason = 'critical-held' }
        Write-Host ("MAILBOX held [" + $heldSlot + "] " + $decision.Action)
        return
    }
    if (-not $resumeAlloc) {
        Invoke-MailboxFault 'before-accept'
        $bound = Save-MailboxAcceptedBody $decision.TaskId $RawText
        if (-not $bound) {
            Write-Audit @{ ev = 'MAILBOX_RETRY'; seq = $FileSeq; reason = 'accepted-body' }
            Write-Host ("MAILBOX retry [" + $FileSeq + "] accepted-body")
            return
        }
        $bodySha = Get-MailboxBodySha $RawText
        Remember-Mailbox $decision.TaskId 0 'accepted' '' $decision.Action $RemoteSha $bodySha
        Remember-MailboxRemote $RemoteName $RemoteSha 'accepted' $decision.TaskId 0
        Invoke-MailboxFault 'after-accept'
    }
    else {
        Invoke-MailboxFault 'after-accept'
    }
    $execSeq = 0
    $adopted = $false
    if ($resumeAlloc) {
        $gap = [int]$script:State.last_seq + 1
        $owned = Find-MailboxOwnedReservation $script:ArenaRoot $gap
        if ($owned -ge 1) {
            $execSeq = $owned
            $adopted = $true
        }
    }
    if (-not $adopted) {
        try {
            $execSeq = Reserve-TaskSeq -ArenaRoot $script:ArenaRoot -ProducerId 'mailbox'
        }
        catch {
            Write-Audit @{ ev = 'MAILBOX_RETRY'; seq = $FileSeq; reason = 'reserve-failed' }
            Write-Host ("MAILBOX retry [" + $FileSeq + "] reserve-failed")
            return
        }
        Invoke-MailboxFault 'after-reserve-before-seq-persist'
    }
    Remember-Mailbox $decision.TaskId $execSeq 'accepted' ''
    Remember-MailboxRemote $RemoteName $RemoteSha 'accepted' $decision.TaskId $execSeq
    $dest = Join-Path $script:InboxDir ("$execSeq.json")
    if (Test-Path -LiteralPath $dest) {
        Complete-TaskReservation -ArenaRoot $script:ArenaRoot -Seq $execSeq
        Write-Host ("MAILBOX retry [" + $FileSeq + "] reserve-failed")
        return
    }
    $json = New-MailboxEnvelopeJson -Seq $execSeq -Action $decision.Action -TaskId $decision.TaskId -Created $created -Expires $expires
    if ([string]::IsNullOrWhiteSpace($json)) {
        Complete-TaskReservation -ArenaRoot $script:ArenaRoot -Seq $execSeq
        Write-Host ("MAILBOX retry [" + $FileSeq + "] reserve-failed")
        return
    }
    if (-not (Test-Path -LiteralPath $dest)) { Write-FileAtomic $dest $json }
    Write-Audit @{ ev = 'MAILBOX_ACCEPTED'; seq = $execSeq; action = $decision.Action; remote_seq = $FileSeq }
    Write-Host ("MAILBOX accepted [" + $execSeq + "] " + $decision.Action)
    Invoke-MailboxFault 'after-write'
    Complete-TaskReservation -ArenaRoot $script:ArenaRoot -Seq $execSeq
    Invoke-MailboxRemoteCleanup $RemoteName $RemoteSha
    Invoke-MailboxFault 'after-cleanup'
}

function Invoke-MailboxSync {
    # One poll. Never sleeps. Never executes an action. Local inbox keeps working
    # when GitHub is down. Already settled remote files do not spend the 20-item
    # new-work budget. archive/ is never requested.
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
    $colPage = Invoke-MailboxPagedList 'collaborators'
    if ($colPage.Timeout) { Register-MailboxBackoff 'mailbox-timeout'; return }
    if (-not $colPage.Ok) { Write-MailboxRefuse $colPage.Reason; return }
    $keyPage = Invoke-MailboxPagedList 'keys'
    if ($keyPage.Timeout) { Register-MailboxBackoff 'mailbox-timeout'; return }
    if (-not $keyPage.Ok) { Write-MailboxRefuse $keyPage.Reason; return }
    $permErr = Test-MailboxPermission $repoMeta $colPage.Items $keyPage.Items $repo $script:MailboxOwner
    if ($permErr) { Write-MailboxRefuse $permErr; return }
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
    $entries = New-Object System.Collections.Generic.List[object]
    foreach ($entry in @(Get-MailboxSortedEntries (Get-MailboxInboxEntries $listObj))) {
        if ($null -eq $entry) { continue }
        if ($entry -is [System.Array]) {
            foreach ($inner in @($entry)) {
                if ($null -ne $inner) { $entries.Add($inner) | Out-Null }
            }
        }
        else { $entries.Add($entry) | Out-Null }
    }
    $warnAt = Get-MailboxListWarnAt
    if ($entries.Count -ge $warnAt) {
        Write-Audit @{ ev = 'MAILBOX_INBOX_TRUNCATED'; count = $entries.Count; limit = $warnAt }
        Write-Host 'MAILBOX inbox-truncated'
    }
    $used = 0
    $cleanupQueue = New-Object System.Collections.Generic.List[object]
    foreach ($entry in @($entries.ToArray())) {
        if ($null -eq $entry) { continue }
        $name = [string]$entry.Name
        $sha = [string]$entry.Sha
        if (Test-MailboxRemoteSettled $name $sha) {
            $cleanupQueue.Add($entry) | Out-Null
            continue
        }
        if ($used -ge 20) { continue }
        $used++
        $fileSeq = 0
        if ($name -match '^([1-9][0-9]{0,8})\.json$') { $fileSeq = [int]$Matches[1] }
        $cand = Read-MailboxCandidate $repo $name $fileSeq
        if ($cand.Fatal) { Register-MailboxBackoff $cand.Reason; return }
        if (-not $cand.Ok) {
            $tid = ''
            if ($cand.Envelope) {
                $en = @($cand.Envelope.PSObject.Properties.Name)
                if ($en -contains 'task_id') { $tid = [string]$cand.Envelope.task_id }
            }
            if ([string]::IsNullOrWhiteSpace($tid)) { $tid = Get-MailboxNameTaskId $name }
            $prev = $null
            if (-not [string]::IsNullOrWhiteSpace($tid)) { $prev = Get-MailboxSeen $tid }
            if ($prev -and [string]$prev.disposition -eq 'accepted') {
                Import-MailboxEnvelope $cand.Envelope $fileSeq $cand.Text $name $sha
                continue
            }
            $skipReject = $false
            if ($prev -and [string]$prev.disposition -eq 'rejected') { $skipReject = $true }
            if (-not $skipReject) { Reject-MailboxTask -Seq $fileSeq -TaskId $tid -Reason $cand.Reason -Label $name }
            Remember-MailboxRemote $name $sha 'rejected' $tid 0
            Invoke-MailboxRemoteCleanup $name $sha
            continue
        }
        Import-MailboxEnvelope $cand.Envelope $fileSeq $cand.Text $name $sha
    }
    $cleaned = 0
    foreach ($entry in @($cleanupQueue.ToArray())) {
        if ($null -eq $entry) { continue }
        if ($cleaned -ge 20) { break }
        $cleaned++
        Invoke-MailboxRemoteCleanup ([string]$entry.Name) ([string]$entry.Sha)
    }
    $script:MailboxBackoffSec = $script:MailboxPollSec
    Set-MailboxNextPoll $script:MailboxPollSec
}
