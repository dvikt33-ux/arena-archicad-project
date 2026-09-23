# arena-mailbox-put.ps1 — local producer for the private mailbox.
#
# This script accepts an action ID only. It does not accept a command string,
# and it does not prompt. A trusted local writer uses it to queue a task.
# ChatGPT is not given a secret by this script.
#
# The remote file name is the task id. It is not an execution slot. This script
# does not allocate a local sequence. -Seq is accepted so older callers still
# parse, and then ignored. Staging is mailbox-staging/<task_id>.json.
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

# mailbox.ps1 assigns $script:MailboxRepo. That is the same variable as this
# parameter, so copy the argument before the scripts are dot-sourced.
$putMailboxRepo = $MailboxRepo

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
    $repoErr = Test-MailboxRepoName $putMailboxRepo 'dvikt33-ux/arena-archicad-project'
    if ($repoErr) {
        Write-Host ("REFUSED: " + $repoErr)
        exit 9
    }
}

New-Dirs $ArenaRoot
$stageDir = Join-Path $ArenaRoot 'mailbox-staging'
if (-not (Test-Path -LiteralPath $stageDir)) {
    New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
}

# Remote id is the task UUID. The envelope seq is only a schema placeholder.
$taskId = [guid]::NewGuid().ToString('D')
$remoteName = $taskId + '.json'
$dest = Join-Path $stageDir $remoteName
if (Test-Path -LiteralPath $dest) {
    Write-Host 'REFUSED: staging file already exists'
    exit 8
}

$created = Format-MailboxTime ([datetime]::UtcNow)
$expires = Format-MailboxTime ([datetime]::UtcNow.AddHours(2))
$json = New-MailboxEnvelopeJson -Seq 1 -Action $canonical -TaskId $taskId -Created $created -Expires $expires
if ([string]::IsNullOrWhiteSpace($json)) {
    Write-Host 'REFUSED: envelope'
    exit 8
}
Write-FileAtomic $dest $json
Write-Host ("MAILBOX_QUEUED task_id=" + $taskId + " action=" + $canonical + " remote=inbox/" + $remoteName)

if ($DryRun -or -not $Push) { exit 0 }

$repoErr = Test-MailboxRepoName $putMailboxRepo 'dvikt33-ux/arena-archicad-project'
if ($repoErr) {
    Write-Host ("REFUSED: " + $repoErr)
    exit 9
}

$meta = Invoke-NativeTimed -Command 'gh' -ArgumentList @('api', ("repos/" + $putMailboxRepo)) -TimeoutMs 30000
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
$putObj = @{ message = 'queue task'; content = $b64 }
$putPath = Join-Path $ArenaRoot ("put-" + [guid]::NewGuid().ToString('N') + '.json')
Write-FileAtomic $putPath ($putObj | ConvertTo-Json -Compress -Depth 4)
try {
    $put = Invoke-NativeTimed -Command 'gh' -ArgumentList @(
        'api', '--method', 'PUT',
        ("repos/" + $putMailboxRepo + "/contents/inbox/" + $remoteName),
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
Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
Write-Host ("MAILBOX_PUSHED task_id=" + $taskId)
exit 0
