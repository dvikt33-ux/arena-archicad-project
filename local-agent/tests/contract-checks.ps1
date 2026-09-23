# contract-checks.ps1 — phrase and source scan for the Phase 1 contract.
# It does not execute agent steps and does not replace dotnet test.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$agent = Split-Path -Parent $here
$contract = Join-Path $agent 'CONTRACT.md'
$src = Join-Path $agent 'src'
if (-not (Test-Path -LiteralPath $contract)) { throw 'CONTRACT.md missing' }
$text = [System.IO.File]::ReadAllText($contract)
$needles = @(
    'step_id',
    'request_id',
    'job_id',
    'remote-deny',
    'FILE_APPLY_PATCH',
    'expected_sha256',
    'NEEDS_REVIEW',
    'dependency-cycle',
    'ui.control',
    'archicad.write',
    'system.admin',
    'package.user_install',
    'workspace.exec',
    'mailbox.poll',
    'issue.publish',
    'git.commit',
    'git.push',
    'ARENA-PATCH/1',
    'test-profile',
    'SQLite',
    '1048576',
    'read-limit',
    'bad-encoding',
    'exit-code',
    'journal_mode=WAL'
)
foreach ($needle in $needles) {
    if ($text.IndexOf($needle) -lt 0) { throw ('contract missing ' + $needle) }
}
if ($text.IndexOf('listener') -lt 0) { throw 'contract missing listener absence' }
$forbidden = @('HttpListener', 'TcpListener', 'NamedPipeServerStream', 'Socket(', 'Invoke-Expression')
$files = @(Get-ChildItem -LiteralPath $src -Recurse -Filter '*.cs' -File)
if ($files.Count -lt 1) { throw 'agent source missing' }
foreach ($file in $files) {
    $code = [System.IO.File]::ReadAllText($file.FullName)
    foreach ($name in $forbidden) {
        if ($code.IndexOf($name) -ge 0) { throw ('forbidden API ' + $name + ' in ' + $file.Name) }
    }
}
$program = [System.IO.File]::ReadAllText((Join-Path $src 'Arena.LocalAgent/Program.cs'))
if ($program.IndexOf('jobs are not accepted from the command line') -lt 0) { throw 'command line is not refused' }
$mail = Join-Path $agent 'mailbox.json'
if (Test-Path -LiteralPath $mail) { throw 'mailbox.json must not be in the agent tree' }
Write-Host 'CONTRACT CHECKS PASSED'
