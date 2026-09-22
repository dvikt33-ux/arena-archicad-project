# arena-mailbox-put.ps1 — local producer for the private mailbox.
#
# This script accepts an action ID only. It does not accept a command string,
# and it does not prompt. A trusted local writer (or a later one-time setup)
# uses it to queue a task. ChatGPT is not given a secret by this script.
#
#   .\arena-mailbox-put.ps1 -Action GIT_STATUS -DryRun
#   .\arena-mailbox-put.ps1 -Action GIT_STATUS -MailboxRepo dvikt33-ux/arena-bridge-mailbox -Push
#
# -Push uses the gh login already on this machine. It refuses the public
# project repo. The token is never printed.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Action,
    [string]$ArenaRoot,
    [string]$MailboxRepo = '',
    [int]$Seq = 0,
    [switch]$Push,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'arena-common.ps1')
. (Join-Path $here 'actions.ps1')
. (Join-Path $here 'mailbox.ps1')

if ([string]::IsNullOrWhiteSpace($ArenaRoot)) {
    $base = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { $base = $script:UserProfile }
    $ArenaRoot = Join-Path $base 'ArenaBridge'
}

$canonical = ('' + $Action).Trim().ToUpperInvariant()
if ($canonical -notmatch '^[A-Z0-9_]+$') {
    Write-Host 'BLOCKED BY PRODUCER ALLOWLIST'
    exit 3
}
$known = $false
foreach ($id in @($script:ActionIds)) {
    if ($id -eq $canonical) { $known = $true }
}
if (-not $known) {
    Write-Host 'BLOCKED BY PRODUCER ALLOWLIST'
    exit 3
}

if ($Push -and -not $DryRun) {
    $repoErr = Test-MailboxRepoName $MailboxRepo 'dvikt33-ux/arena-archicad-project'
    if ($repoErr) {
        Write-Host ("REFUSED: " + $repoErr)
        exit 9
    }
}

New-Dirs $ArenaRoot
$statePath = Join-Path $ArenaRoot 'state.json'
$inboxDir = Join-Path $ArenaRoot 'inbox'
$stageDir = Join-Path $ArenaRoot 'mailbox-staging'
if (-not (Test-Path -LiteralPath $stageDir)) {
    New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
}

$heldReservation = $false
if ($Seq -lt 1) {
    try {
        $Seq = Reserve-TaskSeq -ArenaRoot $ArenaRoot -ProducerId 'mailbox-put'
    }
    catch {
        Write-Host 'REFUSED: seq'
        exit 8
    }
    $heldReservation = $true
}
if ($Seq -lt 1 -or $Seq -gt 999999999) {
    Write-Host 'REFUSED: seq'
    exit 8
}
$dest = Join-Path $stageDir ("$Seq.json")
if (Test-Path -LiteralPath $dest) {
    Write-Host 'REFUSED: seq file already exists'
    exit 8
}
if (Test-Path -LiteralPath (Join-Path $inboxDir ("$Seq.json"))) {
    Write-Host 'REFUSED: inbox seq already exists'
    exit 8
}

$taskId = [guid]::NewGuid().ToString('D')
$created = Format-MailboxTime ([datetime]::UtcNow)
$expires = Format-MailboxTime ([datetime]::UtcNow.AddHours(2))
$json = New-MailboxEnvelopeJson -Seq $Seq -Action $canonical -TaskId $taskId -Created $created -Expires $expires
if ([string]::IsNullOrWhiteSpace($json)) {
    Write-Host 'REFUSED: envelope'
    exit 8
}
Write-FileAtomic $dest $json
if ($heldReservation) { Complete-TaskReservation -ArenaRoot $ArenaRoot -Seq $Seq }
Write-Host ("MAILBOX_QUEUED seq=" + $Seq + " task_id=" + $taskId + " action=" + $canonical)

if ($DryRun -or -not $Push) { exit 0 }

$repoErr = Test-MailboxRepoName $MailboxRepo 'dvikt33-ux/arena-archicad-project'
if ($repoErr) {
    Write-Host ("REFUSED: " + $repoErr)
    exit 9
}

$meta = Invoke-NativeTimed -Command 'gh' -ArgumentList @('api', ("repos/" + $MailboxRepo)) -TimeoutMs 30000
if ($null -eq $meta -or $meta.Code -ne 0) {
    Write-Host 'REFUSED: mailbox repo not readable'
    exit 9
}
$repoObj = $null
try { $repoObj = $meta.Text | ConvertFrom-Json -ErrorAction Stop }
catch {
    Write-Host 'REFUSED: mailbox repo not readable'
    exit 9
}
if ($null -eq $repoObj -or $repoObj.private -ne $true) {
    Write-Host 'REFUSED: mailbox repo is not private'
    exit 9
}

$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
$b64 = [Convert]::ToBase64String($bytes)
$putObj = @{ message = ("queue task " + $Seq); content = $b64 }
$putPath = Join-Path $ArenaRoot ("put-" + [guid]::NewGuid().ToString('N') + '.json')
Write-FileAtomic $putPath ($putObj | ConvertTo-Json -Compress -Depth 4)
try {
    $put = Invoke-NativeTimed -Command 'gh' -ArgumentList @(
        'api', '--method', 'PUT',
        ("repos/" + $MailboxRepo + "/contents/inbox/" + $Seq + ".json"),
        '--input', $putPath
    ) -TimeoutMs 30000
    if ($null -eq $put -or $put.Code -ne 0) {
        Write-Host 'PUSH FAILED'
        exit 1
    }
}
finally {
    Remove-Item -LiteralPath $putPath -Force -ErrorAction SilentlyContinue
}
Write-Host ("MAILBOX_PUSHED seq=" + $Seq)
exit 0
