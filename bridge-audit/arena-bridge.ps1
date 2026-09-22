$taskFile   = "$env:USERPROFILE\Documents\arena-bridge-task.txt"
$resultFile = "$env:USERPROFILE\Documents\arena-bridge-result.txt"
$stateFile  = "$env:USERPROFILE\Documents\arena-bridge-last-task.txt"
$workDir    = "$env:USERPROFILE\Documents\arena-archicad-project"

$githubRepo  = "dvikt33-ux/arena-archicad-project"
$githubIssue = "1"

$allowed = @(
    "git --version",
    "git status",
    "git diff",
    "git log --oneline -10"
)

# Пока автоматически отправляем в публичный GitHub
# только результаты, где практически нет риска утечки секретов.
$safeToPublish = @(
    "git --version",
    "git status",
    "git log --oneline -10"
)

function Send-ToGitHub {
    param(
        [string]$Text
    )

    for ($attempt = 1; $attempt -le 3; $attempt++) {

        & gh api `
            -X POST `
            "repos/$githubRepo/issues/$githubIssue/comments" `
            -f "body=$Text" `
            --silent

        if ($LASTEXITCODE -eq 0) {
            Write-Host "SENT TO CHATGPT VIA GITHUB"
            return $true
        }

        Write-Host "GitHub send failed. Attempt $attempt/3"

        Start-Sleep -Seconds 2
    }

    Write-Host "GITHUB SEND FAILED"
    return $false
}

$lastTaskId = ""

if (Test-Path $stateFile) {
    $lastTaskId = (Get-Content $stateFile -Raw).Trim()
}

Write-Host "Arena Bridge is running..."
Write-Host "Watching: $taskFile"
Write-Host "Project:  $workDir"
Write-Host "Last completed task: $lastTaskId"
Write-Host "GitHub mailbox: Issue #$githubIssue"
Write-Host "Press Ctrl+C to stop."

while ($true) {

    try {

        if (Test-Path $taskFile) {

            $raw = (Get-Content $taskFile -Raw).Trim()

            if (-not [string]::IsNullOrWhiteSpace($raw)) {

                $parts = $raw -split '\|', 2

                if ($parts.Count -eq 2) {

                    $taskId  = $parts[0].Trim()
                    $command = $parts[1].Trim()

                    if (
                        -not [string]::IsNullOrWhiteSpace($taskId) -and
                        $taskId -ne $lastTaskId
                    ) {

                        Write-Host "NEW [$taskId]: $command"

                        if ($command -notin $allowed) {

                            $resultText = @"
[LOCAL RESULT $taskId]

TASK ID:
$taskId

TIME:
$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

COMMAND:
$command

STATUS:
BLOCKED

REASON:
Command is not in the allowlist.
"@

                            $resultText |
                                Set-Content $resultFile -Encoding UTF8

                            Set-Content `
                                $stateFile `
                                $taskId `
                                -Encoding UTF8

                            $lastTaskId = $taskId

                            Write-Host "BLOCKED [$taskId]: $command"
                        }
                        else {

                            try {

                                Push-Location $workDir

                                try {
                                    $result = powershell `
                                        -NoProfile `
                                        -NonInteractive `
                                        -Command $command 2>&1

                                    $exitCode = $LASTEXITCODE
                                }
                                finally {
                                    Pop-Location
                                }

                                $resultText = @"
[LOCAL RESULT $taskId]

TASK ID:
$taskId

TIME:
$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

COMMAND:
$command

STATUS:
COMPLETED

EXIT CODE:
$exitCode

RESULT:
$result
"@

                                $resultText |
                                    Set-Content `
                                        $resultFile `
                                        -Encoding UTF8

                                Set-Content `
                                    $stateFile `
                                    $taskId `
                                    -Encoding UTF8

                                $lastTaskId = $taskId

                                Write-Host "DONE [$taskId]: $command"

                                if ($command -in $safeToPublish) {
                                    Send-ToGitHub $resultText | Out-Null
                                }
                                else {
                                    Write-Host "RESULT NOT PUBLISHED: command may expose sensitive data"
                                }
                            }
                            catch {

                                $resultText = @"
[LOCAL RESULT $taskId]

TASK ID:
$taskId

TIME:
$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

COMMAND:
$command

STATUS:
ERROR

ERROR:
$($_.Exception.Message)
"@

                                $resultText |
                                    Set-Content `
                                        $resultFile `
                                        -Encoding UTF8

                                Write-Host "ERROR [$taskId]: $($_.Exception.Message)"
                            }
                        }
                    }
                }
                else {
                    Write-Host "IGNORED: invalid task format"
                }
            }
        }
    }
    catch {
        Write-Host "BRIDGE ERROR: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 1
}