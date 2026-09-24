@echo off
rem Mashina B: primenenie ops.json (s podtverzhdeniem Y/N)
cd /d "%~dp0"
py "%~dp0ops_apply.py" ops.json
pause
