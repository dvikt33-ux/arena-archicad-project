# Bridge v2 — дизайн (на утверждение)

**Статус:** черновик для сверки. Код ещё не писан.
**Цель:** превратить рабочий прототип в надёжного исполнителя, закрыв P0–P1
из аудита, ДО появления пишущих действий в allowlist.

## 1. Что закрываем (маппинг на аудит)

| № | Пункт плана пользователя | Закрывает из аудита |
|---|---|---|
| 1 | Action-ID вместо shell-строк (`GIT_STATUS → & git status`) | §9, S-5→инвариант, L-1 (канонизация), H-3 частично |
| 2 | State machine `RECEIVED→RUNNING→COMPLETED→PENDING_PUBLISH→PUBLISHED`, состояние пишется **до** и **после** выполнения | H-1, M-2, §6 |
| 3 | Монотонный `seq` вместо `lastTaskId`, обработанные ID хранятся | C-2, M-3, H-4 (частично) |
| 4 | Атомарные записи (temp → `Move-Item`/`File.Replace`) | M-1, M-2, §3 |
| 5 | Repo guard перед каждым действием (fail-closed) | H-3, L-5, L-10 |
| 6 | Durable outbox: GitHub недоступен → результат ждёт, task НЕ перевыполняется | H-2, M-5 (upsert), §10 |
| 7 | Обратный канал (seq+nonce+HMAC, приватный mailbox) | **этап после v2 core**, §12 — сюда не входит |

Дополнительно в v2 core входят дешёвые M: single-instance мьютекс (M-9),
переезд из Documents (M-12), ротация result (L-8), JOIN вывода (M-10/B-5),
FAILED при exit≠0 (L-2), лимит размера результата (M-6 частично).

## 2. Что НЕ трогаем

- `llama-server` и саму Qwen — не меняются вовсе.
- `arena-bridge.ps1` / `arena-qwen-router.ps1` (v1) — остаются как есть,
  для A/B и отката. v2 лежит рядом: `arena-bridge-v2.ps1`,
  `arena-qwen-router-v2.ps1`.
- Публичная политика: `git_diff` по-прежнему никогда не публикуется;
  `status/log10/version` публикуются в Issue #1 (до появления приватного
  mailbox — тогда результат поедет туда, см. §11).

## 3. Раскладка файлов (по умолчанию `%LOCALAPPDATA%\ArenaBridge`)

```
ArenaBridge\
  arena-bridge-v2.ps1          # исполнитель (цикл)
  arena-qwen-router-v2.ps1     # маршрутизатор (пишет в inbox)
  actions.ps1                  # таблица action_id → ScriptBlock + политика
  state.json                   # last_seq + записи задач (атомарно)
  inbox\                       # очередь задач: <seq>.json
  outbox\                      # результаты, ждущие публикации: <seq>.json
  results\result-<seq>.txt     # тела результатов (история, не перезапись)
  audit-YYYY-MM-DD.jsonl       # append-only лог (без тел выводов и секретов)
```

## 4. Протокол роутер → бридж

Роутер пишет **по одной задаче на файл** в `inbox\` атомарно
(`<seq>.json.tmp` → rename в `<seq>.json`):

```json
{"seq":12,"action":"GIT_STATUS","ts":"2026-09-22T12:00:00Z","request":"покажи статус репо"}
```

- `action` — ТОЛЬКО из таблицы: `GIT_VERSION`, `GIT_STATUS`, `GIT_DIFF`,
  `GIT_LOG10`. Строки-команд в протоколе больше нет.
- `request` — исходная просьба (для аудита и будущего HMAC-конверта).
- `seq` — монотонный. Никаких `|`-строк, никаких команд от Qwen.

Rename атомарен на одном томе → рваных чтений нет (M-1). Перезапись другой
задачи невозможна (каждый seq — новый файл) → H-4 закрыт. Старый seq не
переигрывается (см. §5) → C-2 закрыт.

## 5. State machine и правила

Состояния: `RECEIVED → VALIDATED → RUNNING → COMPLETED → PENDING_PUBLISH → PUBLISHED`;
боковые `BLOCKED`, `FAILED`. Всё — в `state.json` (атомарно).

```
state.json = {
  "last_seq": 12,
  "tasks": {
    "12": {"action":"GIT_STATUS","state":"PUBLISHED","exit":0,
           "result_file":"results/result-12.txt","comment_id":123456789,
           "updated":"2026-09-22T12:00:05Z"}
  }
}
```

**Переходы (в цикле бриджа):**

1. **RECEIVED:** файл `inbox/<seq>.json` существует.
   - `seq ≤ last_seq` → дубликат/replay → переместить в `inbox\.done\`, IGNORE.
   - `seq > last_seq+1` → дыра → ждать (не выполнять вне очереди), лог 1 раз.
   - `seq = last_seq+1` → читать, перейти к VALIDATED.
2. **VALIDATED:** `action` есть в таблице, JSON валиден. Иначе → BLOCKED
   (результат пишется, задача потребляется, публикуется статусный маркер).
3. **RUNNING:** записать в `state.json` `{"state":"RUNNING","pid":..,"started":..}`
   **до** выполнения. Это fence против H-1.
4. **COMPLETED:** выполнить action; записать `exit` + `result-<seq>.txt`
   + `result_sha256` **после** выполнения. `exit≠0` → статус FAILED в теле,
   но задача потреблена (никакого ре-выполнения).
5. **PENDING_PUBLISH:** положить результат в `outbox\<seq>.json`.
6. **PUBLISHED:** доставка успешна (201), `comment_id` сохранён, файл из
   outbox удалён.

**Crash recovery при старте:** любая задача в `RUNNING` → `FAILED(recovered)`
(«упали во время выполнения — не повторяем вслепую»; повтор только вручную
новым seq). Задача в `COMPLETED`/`PENDING_PUBLISH` → publisher досылает
из outbox. Это закрывает окно exec→state (H-1) и state→publish (H-2).

**ERROR-гарантия (C-1):** любое исключение внутри обработки задачи = задача
потребляется с `FAILED` и пишется в state/outbox. Вечного re-exec не существует
по построению (нет ветки «попробовать ещё раз без изменения state»).

## 6. Repo guard (перед КАЖДЫМ действием, fail-closed)

```
1. Test-Path $workDir          → иначе FAILED
2. Test-Path "$workDir\.git"   → иначе FAILED
3. $top = git -C $workDir rev-parse --show-toplevel
   Resolve-Path $top == Resolve-Path $workDir (точное совпадение, реальный путь)
   → иначе FAILED (закрывает symlink/junction-побег, L-5)
4. $origin = git -C $workDir remote get-url origin
   нормализовать (снять .git-суффикс, https↔ssh, регистр хоста, слеш)
   → должен заканчиваться на "dvikt33-ux/arena-archicad-project"
   → иначе FAILED (H-3)
```

Любой провал guard → задача `FAILED`, в лог — причина, выполнение не
происходит (L-10).

## 7. Исполнитель без shell-строк (actions.ps1)

```powershell
$Actions = @{
  GIT_VERSION = @{ Run = { & git --version 2>&1 };            Public = $true }
  GIT_STATUS  = @{ Run = { & git -C $workDir status 2>&1 };   Public = $true }
  GIT_LOG10   = @{ Run = { & git -C $workDir log --oneline -10 2>&1 }; Public = $true }
  GIT_DIFF    = @{ Run = { & git -C $workDir diff 2>&1 };     Public = $false }
}
```

- Никаких `powershell -Command "<строка>"`, никакого `Push-Location` —
  только `& git -C <фикс.путь> <фикс.аргументы>`.
- Вывод: `($out -join "`r`n")` (лечит M-10/B-5), лимит + `[truncated]`.
- Команды v1 сохраняют семантику (`status` полный, `log --oneline -10`).
- Будущие мутирующие действия: поле `Approval='interactive'` + флаг
  `ReplaySafe` — заготовка в таблице, сейчас не используется.

## 8. Outbox и идемпотентная публикация

- Publisher (тот же процесс, отдельная фаза цикла) берёт `outbox\<seq>.json`,
  шлёт `gh api -X POST .../comments` с телом, содержащим маркер
  `<!-- arena-task:<seq> -->`.
- Успех → `comment_id` в state.json, файл из outbox удалён.
- Неуспех → файл остаётся, ретрай с экспоненциальным backoff (2→4→8…с,
  кап 60 с; 401/404/422 — стоп, в лог). Задача при этом **не перевыполняется**.
- Идемпотентность (M-5): перед POST — поиск своего комментария по маркеру
  через `gh api .../comments`; найден → `PATCH` этого комментария вместо
  нового POST (upsert). Плюс `comment_id` в state как второй рубеж.
- Офлайн: мост продолжает принимать задачи и складывать в outbox; сеть
  вернулась — publisher досылает по порядку seq (reconnect без потерь).

## 9. Атомарные записи и single-instance

```powershell
function Write-FileAtomic($Path, $Text) {
  $tmp = Join-Path (Split-Path $Path -Parent) ("~" + [guid]::NewGuid().ToString('N') + ".tmp")
  [System.IO.File]::WriteAllText($tmp, $Text, (New-Object System.Text.UTF8Encoding($false)))
  if (Test-Path $Path) { [System.IO.File]::Replace($tmp, $Path, $null) }
  else { Move-Item -LiteralPath $tmp -Destination $Path -Force }
}
```

- Single-instance: `[System.Threading.Mutex]::new($false,'ArenaBridge.v2')`,
  `WaitOne(0)` не удалось → exit 5 (второй экземпляр умирает; M-9).
- Роутер берёт свой мьютекс `ArenaRouter.v2` на время вычисления seq + записи.

## 10. Роутер v2 (минимальный diff от v1)

- Промпт: «выбери РОВНО один ACTION ID из: GIT_VERSION, GIT_STATUS, GIT_DIFF,
  GIT_LOG10; иначе ответь ровно BLOCKED». Allowlist — те же ID.
- Валидация схемы ответа Qwen (`choices` не пуст) с отдельным exit-кодом (L-4).
- Вычисление seq: `next = max(last_seq из state.json, max seq в inbox) + 1`,
  под мьютексом, с повторной проверкой «файл уже есть? → seq+1» (гонка двух
  запусков роутера не рождает перезаписи).
- Запись: `inbox\<seq>.json.tmp` → rename. `request` — в конверт.
- Больше НЕ пишет в `task.txt` и НЕ читает `last-task.txt`.

## 11. Что откладывается (после v2 core, по решению пользователя)

- Обратный канал: код есть, live выключен. Транспорт — приватный mailbox.
  Разрешение — права репозитория (private, не форк, точное имя, нет лишнего
  writer и deploy key), не текст GitHub и не автор коммита. Подпись не
  подделывается. См. MAILBOX.md и AUTONOMY.md.
  Remote-имя — `inbox/<task_id>.json`, не exec seq. Staging не занимает локальную дыру.
  Пагинация прав обязательна и не доказывает exclusive writer. `archive/` не очередь.
- Проверка `author==owner` у комментариев публичного Issue (M-11) — не источник
  команд. Issue по-прежнему только для уже разрешённых результатов.
- Таймаут `gh` через job+kill (в v2 — backoff; жёсткий таймаут можно добавить
  позже, обёртка не меняет контракт).

## 12. Тестирование (на машине пользователя)

- **Pester-набор** (единичные, без сети): state machine переходы, dedup
  (seq ≤ last_seq), дыра (gap), guard (5 провалов → FAILED), атомарная запись,
  crash-recovery (RUNNING→FAILED-recovered), exit≠0→FAILED, JOIN вывода.
- **Дым-тест с фейками:** shim-каталог на PATH с поддельными `git.exe` и
  `gh.exe` (bash/cmd-скрипты, пишут аргументы в лог) → прогнать полный цикл
  без реального репо и без GitHub; затем то же на реальном репо с
  `gh` в dry-run (`gh api` не вызовется — фейк ловит аргументы).
- **Контроль на живом Issue:** один ручной прогон `GIT_VERSION` + `GIT_STATUS`,
  сверить комментарий и отсутствие дублей при повторе.

## 13. Открытые решения (нужны ответы до написания кода)

1. Формат очереди: inbox-каталог (рекомендую) / JSONL / один task-файл+ack.
2. Расположение файлов: `%LOCALAPPDATA%\ArenaBridge` (рекомендую) / Documents.
3. Область этапа: Bridge v2 + Роутер v2 вместе (рекомендую) / только Bridge v2
   с приёмом legacy-команд.
4. Точка отсчёта seq: продолжить с текущего last-task.txt / начать с 001.
