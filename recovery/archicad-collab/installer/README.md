# Сборка установщика ACCOLLAB (Windows)

Цель: один `ACCOLLAB-Setup-0.2.0.exe` — далее-далее-готово, Python ставить не надо.
Состав: `accollab.exe` (PyInstaller, демон+CLI+relay), Tapir 1.5.9 APX (MIT),
`USTANOVKA.txt`. Тестовые сборки НЕ подписаны (SmartScreen — «Подробнее» →
«Выполнить»); подпись — перед релизом.

## Путь 1: сборка на своей Windows-машине (одна команда)

1. Скопировать репозиторий на Windows (папки `src/`, `installer/`).
2. Двойной клик `installer\build.bat`. Он сам: проверит Python 3.10+,
   поставит PyInstaller, скачает Tapir APX, соберёт `accollab.exe`,
   поставит Inno Setup 6 (через winget) и выдаст `installer\dist\ACCOLLAB-Setup-0.2.0.exe`
   + sha256 в консоль.
3. Требования к сборочной машине: Windows 10/11 x64, Python 3.10+ (или кит
   setup.bat), интернет, права на установку Inno Setup.

## Путь 2: автоматическая сборка (GitHub Actions, машину не трогаем)

1. Залить репозиторий в GitHub (включая `.github/workflows/build-windows.yml`).
2. Запустить workflow вручную (Actions → windows-build → Run) или пушнуть тег `v0.2.0`.
3. Забрать `ACCOLLAB-Setup-0.2.0.exe` из Artifacts (или из Releases при теге).
   Перед сборкой workflow гоняет все 37 unit-тестов — красный билд не соберётся.

## Что делает установщик

- Ставится per-user без админа (`{autopf}\ACCOLLAB`), ярлыки в Пуск:
  проверка (once), status, инструкция. Удаление — только свои файлы.
- Задача «Tapir» (по умолчанию вкл.): копирует APX в Add-Ons Archicad 29;
  без прав/папки показывает инструкцию про Диспетчер надстроек (Add).
- Проверка: Archicad 29 в стандартной папке (предупреждение, не блок).
- Создаёт конфиг `%APPDATA%\ACCOLLAB\accollab.json` (существующий не трогает).
- Тихий режим: `ACCOLLAB-Setup-0.2.0.exe /VERYSILENT /TASKS="tapir"`.
- Обновление/откат: поставить другой Setup поверх; конфиг сохраняется.

## Файлы

- `build.bat` — сборка одной командой; `app_main.py` — точка входа EXE;
  `accollab.spec` — PyInstaller (onefile, console, schema в бандле);
  `version_info.txt` — версия EXE; `setup.iss` — Inno Setup 6;
  `tapir-LICENSE.txt` — MIT (обязан лежать рядом по условиям лицензии);
  `USTANOVKA.txt` — краткая инструкция пользователю (BOM+CRLF).

## Матрица ручной проверки установщика (сокращённая, v0)

1. Чистая Win10 + AC29: установка → ярлыки есть → once работает.
2. Нет AC29: предупреждение, установка продолжается.
3. Без админа + задача Tapir: понятная инструкция, APX остался в папке программы.
4. С админом + задача Tapir: APX в Add-Ons, Tapir виден после рестарта AC29.
5. /VERYSILENT: ставится молча, код возврата 0.
6. Повторная установка: конфиг не затёрт. 7. Удаление: папка программы gone,
   конфиг в %APPDATA% — спросить/оставить (v0: остаётся, удалить вручную).
8. SmartScreen: предупреждение есть (unsigned), «Выполнить» работает.
