@echo off
rem ACCOLLAB daemon: primer komandy - once / run / status / conflicts / serve / show
chcp 65001 >nul
set "PYTHONPATH=%~dp0src"
python -m accollab.daemon --config "%~dp0accollab.json" %*
