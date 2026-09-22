# Arena Local Bridge — промежуточный аудит

## Что это

Локальный мост между:
1. ChatGPT / внешним управляющим агентом
2. локальной Qwen через llama-server
3. PowerShell executor
4. GitHub Issue как каналом передачи результатов

Сейчас рабочая цепочка такая:

Пользовательская фраза
→ arena-qwen-router.ps1
→ локальная Qwen
→ разрешённая команда
→ arena-bridge-task.txt
→ arena-bridge.ps1
→ PowerShell / Git
→ arena-bridge-result.txt
→ GitHub Issue #1
→ ChatGPT читает результат

## Текущий протокол задачи

Формат:

TASK_ID|COMMAND

Пример:

003|git status

Последний успешно обработанный TASK_ID сохраняется локально и используется для защиты от повторного выполнения после перезапуска.

## Что нужно проверить

Проведи глубокий аудит двух файлов:

- arena-bridge.ps1
- arena-qwen-router.ps1

Особенно проверь:

### 1. Command injection
Можно ли обойти allowlist через:
- ;
- |
- &&
- перенос строки
- кавычки
- PowerShell substitution
- Unicode / whitespace tricks
- подмену содержимого task-файла

### 2. Повторное выполнение
Проверь:
- рестарт Bridge
- повтор TASK_ID
- сбой между выполнением команды и сохранением state
- сбой между выполнением команды и публикацией результата
- race condition при изменении task-файла

Команда не должна случайно выполняться дважды.

### 3. Race conditions
Проверь одновременное:
- чтение task-файла
- запись router в task-файл
- запись result-файла
- обновление state-файла

Нужна ли атомарная запись через temp + rename?

### 4. Fail-closed
При любой неоднозначности система должна НЕ выполнять команду.

Проверь поведение при:
- пустом ответе Qwen
- Markdown в ответе
- нескольких командах
- недоступном llama-server
- повреждённом JSON
- недоступном GitHub
- ошибке gh
- отсутствии workDir
- отсутствии файлов state/task/result

### 5. GitHub security
GitHub Issue публичный.

Проверь риск утечки:
- токенов
- API keys
- паролей
- путей
- содержимого git diff
- stdout/stderr
- environment variables

Проверь достаточность safeToPublish.

### 6. State machine
Нужно определить корректные состояния задачи, например:

NEW
VALIDATED
RUNNING
COMPLETED
PUBLISHED
FAILED
BLOCKED

Проверь, не теряется ли задача при сбое между состояниями.

### 7. Local AI trust boundary
Qwen считается недоверенным компонентом.

Она не должна иметь возможность:
- выполнить произвольный PowerShell
- изменить allowlist
- изменить executor
- выйти за пределы проекта
- передать несколько команд вместо одной

### 8. File-system security
Проверь:
- path traversal
- symlink / junction risks
- замену файлов другим процессом
- работу за пределами C:\Users\Admin\Documents\arena-archicad-project

### 9. Process execution
Проверь использование:

powershell -NoProfile -NonInteractive -Command $command

Нужно ли отказаться от передачи строки через -Command и вместо этого запускать заранее определённые действия напрямую.

Например вместо:
powershell -Command "git status"

использовать:
& git status

или таблицу command -> scriptblock.

### 10. GitHub delivery
Проверь:
- retry logic
- duplicate comments
- timeout
- offline режим
- восстановление после reconnect
- идемпотентность публикации

### 11. Logging
Нужно ли добавить отдельный append-only audit log:
- task id
- timestamp
- requested intent
- resolved command
- exit code
- hash результата
- GitHub comment id

Без записи секретов.

### 12. Архитектура следующего этапа

Следующий этап:
ChatGPT → transport → local bridge → Qwen/tools → result → ChatGPT

Предложи безопасную архитектуру обратного канала.

Особенно интересует:
- polling GitHub
- локальный HTTP relay
- WebSocket
- GitHub Actions
- отдельный private repo
- signed messages
- nonce / sequence number
- HMAC

## Ограничения

Не предлагай просто дать модели полный shell access.

Не считать Qwen доверенной.

Не считать GitHub Issue приватным.

Не менять код автоматически.

Сначала только аудит.

## Формат результата

Дай:

1. Critical
2. High
3. Medium
4. Low
5. подтверждённые баги
6. потенциальные риски
7. конкретные repro steps
8. рекомендуемую целевую архитектуру
9. patch plan по приоритетам

Для каждого серьёзного пункта укажи файл и участок кода.
