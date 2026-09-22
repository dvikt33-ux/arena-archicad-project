# Arena Bridge v2

Надёжный локальный исполнитель для связки **ChatGPT ↔ локальная машина** через
GitHub Issue. Это **вторая версия** моста из `bridge-audit/`: прототип v1
(`arena-bridge.ps1`) доказал, что схема работает, а v2 превращает его из
демонстрации в исполнителя с гарантией «задача не выполняется дважды».

v1 **не удалён** — лежит в `bridge-audit/` для A/B и отката.

## Файлы

| Файл | Что делает |
|---|---|
| `arena-bridge-v2.ps1` | Исполнитель: цикл, state machine, repo guard, outbox, публикация |
| `arena-qwen-router-v2.ps1` | Маршрутизатор: просьба → ACTION ID → `inbox/<seq>.json` |
| `arena-common.ps1` | Общие хелперы (атомарная запись, state, seq-seed) — подключается обоими |
| `actions.ps1` | Таблица action_id → команда + политика публикации (только бридж) |
| `tests/smoke-test.ps1` | Проверки бриджа на фейковых `git`/`gh` (без сети, Windows PowerShell 5.1 и pwsh) |
| `tests/fake-llama.ps1` | Фейковый llama-сервер для теста роутера (без GPU) |

## Что закрыто (из аудита)

- **Action-ID вместо shell-строк**: Qwen отдаёт `GIT_STATUS`, бридж сам
  сопоставляет `GIT_STATUS → & git -C <repo> status`. Инъекции не существует
  даже концептуально (§9, L-1).
- **State machine** `RECEIVED → RUNNING → COMPLETED → PENDING_PUBLISH → PUBLISHED`,
  состояние пишется **до** (RUNNING-fence) и **после** выполнения (H-1, M-2, §6).
- **Монотонный `seq`** вместо `lastTaskId`: `seq ≤ last_seq` = дубликат/replay,
  игнорируется; дыры (`seq > last_seq+1`) ждут, не выполняются вне очереди
  (C-2, M-3, H-4).
- **Атомарные записи** всех task/state/result: temp-файл → rename/`File.Replace`
  (M-1, M-2, §3).
- **Repo guard** перед каждым действием (fail-closed): каталог есть, `.git` есть,
  `rev-parse --show-toplevel` == ожидаемому пути, `origin` ==
  `dvikt33-ux/arena-archicad-project` (H-3, L-5, L-10).
- **Durable outbox**: GitHub недоступен → результат лежит в очереди и
  досылается по порядку, задача **не перевыполняется** (H-2). Идемпотентная
  публикация по маркеру `<!-- arena-task:<seq> -->` (upsert, M-5).
- Single-instance мьютекс (M-9), переезд в `%LOCALAPPDATA%` (M-12),
  ротация `result-<seq>.txt` (L-8), `-join` вывода (M-10), FAILED при exit≠0 (L-2),
  лимит 60К + `[truncated]` (M-6 частично), append-only JSONL аудит-лог (M-7).

## Состояния задачи (state.json)

Поле `state` — этап машины: `RECEIVED / RUNNING / COMPLETED / PENDING_PUBLISH /
PUBLISHED / BLOCKED / FAILED`. Поле `status` — вердикт выполнения:
`COMPLETED / FAILED / BLOCKED` (не затирается доставкой).

- `RUNNING` при старте бриджа → `FAILED(recovered)` — **без автоповтора**
  (повтор только вручную новым seq).
- `exit ≠ 0` → `status=FAILED`, но задача потреблена (вечного re-exec нет).
  Исключение: `git diff` возвращает 1 при наличии изменений — это не ошибка
  (`OkExit = 0,1`).
- BLOCKED/FAILED публикуются в Issue как статус-маркер (без чувствительного тела).

## Запуск (Windows)

Один раз настроить и оставить работать:

```powershell
cd <каталог с файлами v2>
.\arena-bridge-v2.ps1
```

Параметры (все имеют дефолты под ваш сетап):

```powershell
.\arena-bridge-v2.ps1 `
    -WorkDir "$env:USERPROFILE\Documents\arena-archicad-project" `
    -Repo   "dvikt33-ux/arena-archicad-project" `
    -Issue  1 `
    -ArenaRoot "$env:LOCALAPPDATA\ArenaBridge"
```

Запрос Qwen — как в v1: пишете просьбу в
`Documents\arena-bridge-request.txt`, затем:

```powershell
.\arena-qwen-router-v2.ps1
```

Выходы роутера: `0` ок, `1` нет/пустой request или Qwen-ошибка, `2` BLOCKED
по смыслу, `3` не из allowlist, `4` битый ответ Qwen, `6` уже запущен,
`7` state.json не читается. Бридж: `5` уже запущен, `6` state.json повреждён
(fail-closed).

## Тест на вашей машине (без сети и без GitHub)

```powershell
cd <каталог с файлами v2>\tests
powershell -NoProfile -File smoke-test.ps1      # или pwsh
```

Ожидаете `ALL SMOKE TESTS PASSED`. Тест создаёт временную песочницу и фейковые
`git`/`gh`. Реальный репозиторий, GitHub и ваш
`Documents\arena-bridge-last-task.txt` он не читает: иначе первый запуск
унаследовал бы номер задачи v1 и проверка `last_seq=0` упала бы. Живой бридж
при первом старте этот файл по-прежнему читает.

На Windows PowerShell 5.1 пути в дочерний процесс передаются через переменные
окружения, а не аргументами командной строки (пробел в `C:\Users\...` иначе
разрезает `-ArenaRoot`). Публикация в `gh` идёт через `--input` файл, без `|`
и `<!-- -->` в аргументах: 5.1 заново разбирает командную строку.

Проверка роутера без llama (опционально): в одном окне
`powershell -NoProfile -File fake-llama.ps1`, в другом —
`.\arena-qwen-router-v2.ps1 -ApiUrl http://127.0.0.1:8333/v1/chat/completions`.

## Первый запуск и миграция с v1

- При первом запуске бридж читает `Documents\arena-bridge-last-task.txt` (v1)
  и продолжает счётчик с последнего выполненного ID — повтор старых задач
  исключён. Ненumerid значение игнорируется (старт с 0).
- Оставшийся `Documents\arena-bridge-task.txt` (v1) v2 **не читает** — об этом
  пишется предупреждение. Пользуйтесь `arena-qwen-router-v2.ps1`.
- Если `state.json` повреждён, бридж падает fail-closed (exit 6) — чинить
  руками, а не «сбрасывать» (иначе возможен повтор).

## Осознанные ограничения v2 (этап «после»)

- Обратный канал ChatGPT→локалка пока **не строится поверх v1/v2** (по решению
  пользователя): сначала P0–P1. Целевой транспорт — приватный mailbox-репо +
  подписанные конверты `seq+nonce+HMAC` (см. `DESIGN.md` §11 и
  аудит §8.3).
- Публикация по-прежнему в публичный Issue #1; `git diff` никогда не
  публикуется (локальный результат).
- Задачи пока не подписываются: любой локальный процесс может положить файл
  в inbox (M-8 из аудита) — это закроет HMAC на следующем этапе.
