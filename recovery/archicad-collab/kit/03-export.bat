@echo off
rem Mashina A: snyatie operaciy (baseline -> sdvig -> ops.json)
cd /d "%~dp0"
py "%~dp0ops_export.py"
pause
