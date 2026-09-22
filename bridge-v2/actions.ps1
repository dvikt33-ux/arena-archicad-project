# actions.ps1 — action table + executor + repo guard for Arena Bridge v2.
# Dot-source after arena-common.ps1.

# Action table: action_id -> { Public = may publish to public Issue; Run = scriptblock($WorkDir) }.
# Run must return native command output (stdout+stderr merged). No shell strings,
# no user input reaches these invocations — arguments are fixed constants.
$script:Actions = @{
    GIT_VERSION = @{ Public = $true;  OkExit = @(0);    Run = { param($wd) & git --version 2>&1 } }
    GIT_STATUS  = @{ Public = $true;  OkExit = @(0);    Run = { param($wd) & git -C $wd status 2>&1 } }
    GIT_LOG10   = @{ Public = $true;  OkExit = @(0);    Run = { param($wd) & git -C $wd log --oneline -10 2>&1 } }
    # git diff exits 1 when there ARE changes — that is success, not failure.
    GIT_DIFF    = @{ Public = $false; OkExit = @(0, 1); Run = { param($wd) & git -C $wd diff 2>&1 } }
}

function Invoke-Action {
    # Runs an action and returns @{ ExitCode = <int>; Output = <string> }.
    param([string]$Id, [string]$WorkDir)
    if (-not $script:Actions.ContainsKey($Id)) { throw "unknown action: $Id" }
    $out  = & $script:Actions[$Id].Run $WorkDir
    $exit = $LASTEXITCODE
    $text = @($out | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message }
            else { [string]$_ }
        }) -join "`r`n"
    return [pscustomobject]@{ ExitCode = $exit; Output = $text }
}

function Test-RepoGuard {
    # Fail-closed identity check of the working repo. Returns $null on success,
    # otherwise a fixed reason string (never raw values, so it is safe to publish).
    param([string]$WorkDir, [string]$Repo)

    if ([string]::IsNullOrWhiteSpace($WorkDir)) { return 'workdir-missing' }
    if (-not (Test-Path -LiteralPath $WorkDir -PathType Container)) { return 'workdir-missing' }

    $item = Get-Item -LiteralPath $WorkDir -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        return 'workdir-is-reparse-point'
    }

    if (-not (Test-Path -LiteralPath (Join-Path $WorkDir '.git'))) { return 'no-git-dir' }

    $topOut = @(& git -C $WorkDir rev-parse --show-toplevel 2>$null)
    $topExit = $LASTEXITCODE
    if ($topExit -ne 0) { return 'rev-parse-failed' }
    $topLine = "$($topOut | Select-Object -First 1)".Trim()
    if ([string]::IsNullOrWhiteSpace($topLine)) { return 'rev-parse-failed' }

    $resTop  = Resolve-Path -LiteralPath $topLine -ErrorAction SilentlyContinue
    $resWork = Resolve-Path -LiteralPath $WorkDir -ErrorAction SilentlyContinue
    if (-not $resTop -or -not $resWork -or ($resTop.Path -ne $resWork.Path)) { return 'toplevel-mismatch' }

    $originOut = @(& git -C $WorkDir remote get-url origin 2>$null)
    $originExit = $LASTEXITCODE
    if ($originExit -ne 0) { return 'no-origin' }
    $originLine = "$($originOut | Select-Object -First 1)".Trim()
    if ([string]::IsNullOrWhiteSpace($originLine)) { return 'no-origin' }

    if (-not (Test-OriginMatches $originLine $Repo)) { return 'origin-mismatch' }

    return $null
}
