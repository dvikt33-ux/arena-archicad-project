param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('ping','product_info','selection','wall_count')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $here 'archicad_runner.py'

if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    Write-Output '{"protocol":1,"backend":"archicad-python-json","ok":false,"error":"runner-missing"}'
    exit 13
}

$script:RunnerExitCode = 1
function Invoke-PythonRunner {
    param([string]$Exe, [string[]]$PrefixArgs)
    $args = @()
    $args += $PrefixArgs
    $args += @($runner, '--action', $Action)
    & $Exe @args
    $script:RunnerExitCode = $LASTEXITCODE
}

# Explicit override wins. It must be a local executable path configured by the
# machine owner; no task can set it.
if (-not [string]::IsNullOrWhiteSpace($env:ARENA_ARCHICAD_PYTHON)) {
    $python = $env:ARENA_ARCHICAD_PYTHON
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        Write-Output '{"protocol":1,"backend":"archicad-python-json","ok":false,"error":"configured-python-missing"}'
        exit 14
    }
    Invoke-PythonRunner -Exe $python -PrefixArgs @()
    exit $script:RunnerExitCode
}

# Prefer the Windows py launcher when available, then fall back to python.
$py = Get-Command py -ErrorAction SilentlyContinue
if ($null -ne $py) {
    Invoke-PythonRunner -Exe $py.Source -PrefixArgs @('-3')
    exit $script:RunnerExitCode
}

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($null -ne $pythonCmd) {
    Invoke-PythonRunner -Exe $pythonCmd.Source -PrefixArgs @()
    exit $script:RunnerExitCode
}

Write-Output '{"protocol":1,"backend":"archicad-python-json","ok":false,"error":"python-not-found"}'
exit 15
