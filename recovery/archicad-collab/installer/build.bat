@echo off
rem ACCOLLAB: sborka Setup.exe na Windows odnoj komandoj. Zapusk: build.bat
setlocal
cd /d "%~dp0"
set HERE=%~dp0
set DIST=%HERE%dist
where py >nul 2>nul
if errorlevel 1 goto nopy
set PY=py -3
goto pyok
:nopy
where python >nul 2>nul
if errorlevel 1 goto nopy2
set PY=python
goto pyok
:nopy2
echo Nuzhen Python 3.10+. Snachala zapustite kit setup.bat
exit /b 1
:pyok
%PY% --version
echo [1/5] PyInstaller...
%PY% -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 goto pipfail
echo [2/5] Tapir APX...
if exist "%HERE%TapirAddOn_AC29_Win.apx" goto apxok
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/ENZYME-APD/tapir-archicad-automation/releases/download/1.5.9/TapirAddOn_AC29_Win.apx' -OutFile '%HERE%TapirAddOn_AC29_Win.apx'"
if errorlevel 1 goto apxfail
:apxok
echo [3/5] accollab.exe (PyInstaller, eto neskolko minut)...
%PY% -m PyInstaller --clean --noconfirm accollab.spec
if errorlevel 1 goto pyifail
echo [4/5] Inno Setup...
where iscc >nul 2>nul
if not errorlevel 1 goto isccok
where winget >nul 2>nul
if errorlevel 1 goto noiscc
winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
where iscc >nul 2>nul
if errorlevel 1 goto noiscc
:isccok
echo [5/5] Setup.exe...
iscc setup.iss
if errorlevel 1 goto iscfail
echo GOTOVO: %DIST%\ACCOLLAB-Setup-0.2.0.exe
%PY% -c "import hashlib; print('sha256:', hashlib.sha256(open(r'%DIST%\ACCOLLAB-Setup-0.2.0.exe','rb').read()).hexdigest())"
exit /b 0
:pipfail
echo Ne vstal pyinstaller. Proverte internet i prava.
exit /b 1
:apxfail
echo Ne skachalsya Tapir APX. Proverte internet.
exit /b 1
:pyifail
echo Oshibka PyInstaller. Sm. log vyshe.
exit /b 1
:noiscc
echo Net iscc. Postavte Inno Setup 6: https://jrsoftware.org/isinfo.php
exit /b 1
:iscfail
echo Oshibka Inno Setup. Sm. log vyshe.
exit /b 1
