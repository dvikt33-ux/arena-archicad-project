$requestFile = "$env:USERPROFILE\Documents\arena-bridge-request.txt"
$taskFile    = "$env:USERPROFILE\Documents\arena-bridge-task.txt"
$stateFile   = "$env:USERPROFILE\Documents\arena-bridge-last-task.txt"

$apiUrl = "http://127.0.0.1:8080/v1/chat/completions"
$model  = "C:\LocalAI\models\Qwen3.8-27B-UD-Q4_K_XL.gguf"

$allowed = @(
    "git --version",
    "git status",
    "git diff",
    "git log --oneline -10"
)

if (-not (Test-Path $requestFile)) {
    Write-Host "ERROR: request file not found:"
    Write-Host $requestFile
    exit 1
}

$request = (Get-Content $requestFile -Raw).Trim()

if ([string]::IsNullOrWhiteSpace($request)) {
    Write-Host "ERROR: request is empty"
    exit 1
}

$body = @{
    model = $model

    messages = @(
        @{
            role = "system"
            content = @"
Ты маршрутизатор команд для локального Arena Bridge.

Пользователь пишет обычную просьбу на русском или английском.
Ты должен выбрать РОВНО одну подходящую команду.

Разрешены ТОЛЬКО эти команды:

git --version
git status
git diff
git log --oneline -10

Не добавляй пояснений.
Не используй Markdown.
Не используй кавычки.
Не создавай новые команды.
Не объединяй несколько команд.

Если просьба не соответствует разрешённым действиям, ответь ровно:

BLOCKED
"@
        }

        @{
            role = "user"
            content = $request
        }
    )

    temperature = 0
    max_tokens = 128
} | ConvertTo-Json -Depth 6

try {

    $response = Invoke-RestMethod `
        -Uri $apiUrl `
        -Method Post `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body))

}
catch {

    Write-Host "QWEN API ERROR:"
    Write-Host $_.Exception.Message
    exit 1
}

$command = $response.choices[0].message.content.Trim()

Write-Host "REQUEST:"
Write-Host $request
Write-Host ""
Write-Host "QWEN:"
Write-Host $command
Write-Host ""

if ($command -eq "BLOCKED") {
    Write-Host "BLOCKED BY QWEN"
    exit 2
}

# Вторая независимая проверка.
# Даже если модель выдаст что-то постороннее,
# оно не попадёт в Bridge.
if ($command -notin $allowed) {
    Write-Host "BLOCKED BY ROUTER ALLOWLIST"
    exit 3
}

$lastId = "000"

if (Test-Path $stateFile) {
    $saved = (Get-Content $stateFile -Raw).Trim()

    if ($saved -match '^\d+$') {
        $lastId = $saved
    }
}

$nextNumber = [int]$lastId + 1
$taskId = "{0:D3}" -f $nextNumber

Set-Content `
    -Path $taskFile `
    -Value "$taskId|$command" `
    -Encoding UTF8

Write-Host "SENT TO BRIDGE:"
Write-Host "$taskId|$command"