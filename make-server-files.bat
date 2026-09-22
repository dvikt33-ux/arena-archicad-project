@echo off
rem Sozdat "pisma s servera" iz otkrytogo proekta Archicad
chcp 65001 >nul
set "PYTHONPATH=%~dp0src"
python "%~dp0tools\make_server_files.py" --config "%~dp0accollab.json" --out "%~dp0server-files" %*
