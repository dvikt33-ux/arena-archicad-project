# ACCOLLAB — пакет на ревью кода (2026-09-17)

Этот файл — cover letter для профессионального программиста.
Рядом лежит весь код и доки. Порядок чтения: этот файл → 00-proposal.md →
07-daemon.md → код `src/accollab/` → тесты → остальное по оглавлению ниже.

Состав пакета: `src/` (весь продукт), `tests/` (80 тестов + 2 репетиции),
`kit/` + `tools/` (полевые скрипты), `installer/` (заготовка установщика),
`refs/` (спеки Tapir), `evidence/` (живые пруфы с машины заказчика),
`.github/` (CI), доки `00–08` + этот файл.
НЕ входит: `samples/tropa-archicad-s-kartinkami.pln` (29 МБ, рабочий проект
заказчика — для ревью кода не нужен, есть в исходном воркспейсе).

---

## 1. Задача: что хотели построить

Надёжный слой **совместной работы поверх Archicad, не заменяя его**:
3–6 проектировщиков правят один PLN с разных машин, правки синхронизируются,
конфликты видны и разбираются людьми, ничего не теряется молча.

Жёсткие ограничения от заказчика (важно для ревью — не предлагать запрещённое):
- Не заменять Archicad; строить слой сверху через официальный JSON API +
  Tapir Add-On (HTTP, порты 19723+).
- Никаких выдумок про возможности Archicad: если что-то нельзя через
  официальный API/Tapir — так и писать + workaround.
- ИИ/код НЕ принимает архитектурных решений за пользователя и НЕ разруливает
  конфликты автоматически: детерминированный порядок есть, автовыбор — нет.
- Никаких тихих удалений: опасное — только с подтверждением + лог + undo.
- Процесс на правах пользователя, без виндовых служб; uninstall удаляет
  только своё; никогда не портить PLN/Archicad/чужие Add-On'ы.
- Финал — установщик под Archicad 29 (пользователь ничего вручную не ставит).

## 2. Архитектура (как задумано и как сделано)

```
Archicad 29 + Tapir 1.5.9 (HTTP :19723+)
        ^  FitInWindow / ShowAlert / Highlight (экран)
        |  GetAllElements / GetTypes / GetDetails / MoveElements / SetDetails
connector.py — тонкий клиент JSON API + Tapir, все ошибки → ArchicadError
watcher.py — снимок модели → diff → операции (modify/create/delete, lamport)
store.py — SQLite: элементы, журнал операций, outbox, локи, конфликты,
           чекпоинты, комментарии, участники, sync_state
transfer.py — экспорт/импорт операций файлами (флешка/почта, офлайн)
relay.py — свой сервер-склад (VPS, :8471, секрет в заголовке) + клиент
telegram_transport.py — транспорт через Telegram-канал кусками (чёрный ход)
applier.py — применение чужих операций: APPLIED / CONFLICT-* / LOCKED /
             SKIPPED-* / UNSUPPORTED (чужое поверх живого — только явно)
locks.py — soft/hard-блокировки с арендой, heartbeat, протуханием
checkpoints.py — снапшоты + план/применение отката (3 skipped-ветки)
comments.py — комментарии к элементам (локальные + рассылка операциями)
presence.py — подсветка занятого цветами участников (HighlightElements,
             проект НЕ меняется)
backup.py — копия PLN + ротация + sha256
bim_checks.py — СОВЕТЫ по снимку (DUP_ID/EMPTY_ID/NO_MATERIAL), не блокируют
statuspage.py — localhost-страница: вкладки, sync в фоне, zoom/диалоги,
                пульт настроек, настраиваемая раскладка (ui.json)
daemon.py — Daemon.tick(): watcher→export→relay/tg→import→apply→heartbeat→
            presence→status.json; 23 CLI-команды
```

Транспорты (3, взаимозаменяемые): файлы, relay-VPS, Telegram.
Демон толерантен: без Archicad на проводе тик не падает (офлайн-очередь).

## 3. Что РЕАЛИЗОВАНО (факт, всё покрыто тестами)

| Модуль | Строк | Что делает |
|---|---|---|
| daemon.py | 901 | тик, 23 CLI, пин порта, авто-чекпоинт, уведомления |
| statuspage.py | 600 | вкладки+меню ⋯, /sync фон, /show, /ask, /settings, /layout |
| store.py | 212 | схема SQLite, идемпотентность, курсоры |
| relay.py | 205 | сервер + клиент, дедуп, секрет, персист jsonl |
| telegram_transport.py | 172 | куски, подписи HMAC, 429, курсоры, prune |
| locks.py | 159 | аренда/heartbeat/sweep/remote-оп |
| connector.py | 146 | официальный API + Tapir-обёртки + zoom/диалоги |
| comments.py | 144 | CRUD + рассылка + плохие входы |
| applier.py | 133 | применение + отчёты + конфликты |
| watcher.py | 124 | снимок/diff/операции |
| checkpoints.py | 73 | снапшот/откат |
| bim_checks.py | 66 | 3 правила + фильтр |
| backup.py | 59 | копия/ротация/sha |
| presence.py | 51 | цвета/группы/свой цвет |
| transfer.py | 34 | файлы экспорта/импорта |
| **Итого src** | **3082** | только stdlib, ноль зависимостей |

Проверки (все зелёные на 2026-09-17):
- **80/80 unit-тестов**, 13 модулей (`tests/test_*.py`), мок Archicad
  (`mock_archicad.py`) с настоящей HTTP-семантикой;
- **sim_two_machines 9/9** — файловый цикл А→Б;
- **sim_daemon_http 6/6** — два демона против двух моков на реальных
  19723/19724: сдвиг→APPLIED→сверка координат→лок→комментарий→presence;
- живые пруфы с машины заказчика: `evidence/*.json`, `evidence/*.png`
  (диагностика, подсветка, сдвиги — всё проходило на настоящем AC29).

Инфраструктура: relay поднят на VPS (Ubuntu 24.04, `08-relay-server.md`),
CI-воркфлоу `.github/workflows/build-windows.yml` (13 модулей), заготовка
установщика `installer/` (build.bat + Inno Setup + PyInstaller-spec, EXE ещё
не собран — нужен Windows), полевое kit v4 (`kit/` + `INSTRUKTSIYA.txt`).

## 4. Что задумано, но НЕ сделано / в работе (честно)

1. **Сборка EXE/установщика** — скрипты есть, сборки не было (нет Windows).
   Демон в полевое kit НЕ входит (только скрипты v4).
2. **BIM-правила по именам слоёв/перьям** — отложены осознанно: в живых
   данных есть только `layerIndex`, команда называется `GetLayers`
   (вход — attributeIds), живой зондаж связки index→имя впереди. Не гадали.
3. **Встроенная палитра в окне Archicad** — требует C++ Add-On (DevKit);
   есть только макет (`evidence/palette-mockup.html`). Всё, что Tapir реально
   умеет на экране (зум, диалоги, подсветка) — уже используется.
4. **Подтверждения доставки relay** — если VPS умрёт до fetch второй
   машиной, операции потеряны (первая очередь уже очистила). Задокументировано
   в `08-relay-server.md`, фикса нет.
5. **Живые проверки впереди:** диалог ShowAlert и зум на настоящем проекте,
   русские буквы в диалогах, страница в реальном браузере, второй POST /sync
   впритык на долгой модели, живой Telegram-канал, скорость снимка/хеша на
   большом PLN, применение «чужого» поверх живого.
6. **Открытые вопросы с поля:** «тайна сдвига БЛК-151», живой тест №4,
   пин порта против двух живых инстансов AC (26+29 рядом).

## 5. Окружение заказчика (точные версии + нюансы)

| Что | Версия / факт | Источник |
|---|---|---|
| Archicad (цель) | **29.0.0.3000 RUS FULL** | слова заказчика |
| Archicad (рядом) | 26, 27, 28 стоят бок о бок | слова заказчика |
| Tapir Add-On | **1.5.9**, `TapirAddOn_AC29_Win` (APX в `vendor/`, MIT) | файл + setup.bat |
| Python (по инструкции) | **3.12.10 amd64** | setup.bat (ссылка ниже) |
| Python (на машине?) | замечен **3.14** на скрине `evidence/python-3.14-user-machine.png` — **уточнить, что стоит сейчас** | скрин |
| Windows | x64, точная сборка неизвестна | — |
| Связь машин А–Б | только интернет, без LAN | слова заказчика |
| VPS relay | Ubuntu 24.04, 195.19.202.100:8471, Free Tier 3 мес. | панель REG.RU |
| Порты | AC JSON API 19723–19727 (скан), relay 8471, страница 8472 | код |
| Проект | «тропа», ~393 элемента (по живому diag) | evidence |

Нюансы, влияющие на код: зомби-инстанс Archicad на 19723 (отсюда пин порта);
Tapir отвечает `{succeeded, result}`, команды Tapir — через
`API.ExecuteAddOnCommand` с `TapirCommand.<Name>`, полезное — в
`result.addOnCommandResponse`; деталей элементов в официальном API нет —
только Tapir `GetDetailsOfElements`; записи выделения в Tapir нет
(«показать» = FitInWindow + подсветка). Всё сверено со спекой
(`refs/tapir-1.5.8.json`, список команд `evidence/tapir-commands.txt`).

## 6. Что скачать/поставить (пользователю и ревьюеру)

- Python 3.12.10 amd64 (Windows):
  https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
- Tapir 1.5.9 для AC29 (или взять из `vendor/` этого пакета):
  https://github.com/ENZYME-APD/tapir-archicad-automation/releases/latest/download/TapirAddOn_AC29_Win.apx
  ставится через Archicad → Options → Add-On Manager → Add.
- Документация команд Tapir:
  https://enzyme-apd.github.io/tapir-archicad-automation/archicad-addon
- Сам этот пакет (код + доки) — приложен.
- Полевое kit v4 отдельной ссылкой протухло — собирать из `kit/` здесь.

## 7. Как запустить проверки (ревьюеру, нужен только Python 3.12+)

```
cd tests
python -m unittest test_connector test_watcher test_sync test_locks test_checkpoints test_relay test_daemon test_telegram test_comments test_presence test_backup test_bim test_statuspage
# должно быть: Ran 80 tests ... OK
python sim_two_machines.py     # SIM OK: vse 9 shagov proshli.
python sim_daemon_http.py      # SIM-HTTP OK (или честный SKIP, если порты заняты)
```

Живой прогон страницы/демона требует Windows + Archicad 29 + Tapir:
`python -m accollab.daemon init --author ...` → `once` → `serve` →
http://127.0.0.1:8472. Детали: `07-daemon.md`. Ретранслятор: `08-relay-server.md`.

## 8. Вопросы к ревьюеру (что оценить)

1. Корректность протокола: идемпотентность, порядок применения, дедуп,
   курсоры relay/Telegram — где дыры?
2. Правильность использования Tapir: payload'ы Highlight/FitInWindow/
   ShowAlert/MoveElements/SetDetails против спеки в `refs/`.
3. Логика конфликтов: достаточно ли кодов CONFLICT-*/SKIPPED-*? Что будет
   при гонках?
4. Безопасность: секрет relay, HMAC Telegram, localhost-only страница —
   что пропустили? (Секреты в `08-relay-server.md` — живые; после ревью
   заказчику стоит их сменить, процедура там же в шаге 7.)
5. SQLite в потоках (фоновый /sync со своим соединением) — дисциплина
   соблюдена?
6. Что сломается первым на проекте 10 000+ элементов?
7. План установщика (`02-installer-plan.md`, `installer/`) — реалистичен?

## 9. Документы в пакете (карта)

- `00-proposal.md` — исходное предложение системы (ТЗ-ish).
- `01-what-i-need.md` — что нужно от заказчика.
- `02-installer-plan.md` — план установщика.
- `03-versions.md` — журнал версий (пошагово, с итогами прогонов).
- `04-file-registry.md` — реестр файлов от пользователя.
- `05-phase-a-log.md` — подробный журнал работ A-1…A-17 (что/почему/итог).
- `06-second-machine.md` — онбординг второй машины.
- `07-daemon.md` — руководство по демону (конфиг, CLI, тик, страница).
- `08-relay-server.md` — развёртывание relay на VPS + живой секрет.
- `installer/README.md`, `kit/INSTRUKTSIYA.txt`, `refs/README.md` — локальные.
