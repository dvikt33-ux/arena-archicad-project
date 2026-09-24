@echo off
rem ACCOLLAB setup v1.0: Python + Tapir + proverka. Dvoynoy klik.
rem Vse soobshcheniya - translitom (kirillitsa v .bat lomaetsya).
setlocal EnableDelayedExpansion
chcp 65001 >nul
title ACCOLLAB setup
set KIT=%~dp0
set LOG=%KIT%setup.log
echo setup v1.0 start: %date% %time% > "%LOG%"

echo ================================================
echo  ACCOLLAB setup: Python + Tapir + proverka
echo  Log: setup.log ryadom s etim faylom
echo ================================================

rem ---- Shag 1-2: Python ----
set PY=
where py >nul 2>nul
if %errorlevel%==0 set PY=py
if defined PY goto py_ver
where python >nul 2>nul
if %errorlevel%==0 set PY=python
:py_ver
if not defined PY goto py_install
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto py_install
goto py_found
:py_install
echo [1/4] Python 3.10+ ne nayden. Skachivayu ustanovshchik (~30 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $env:TEMP\accollab-python.exe" >> "%LOG%" 2>&1
if errorlevel 1 goto py_dl_fail
for %%F in ("%TEMP%\accollab-python.exe") do set PYSIZE=%%~zF
if %PYSIZE% LSS 1000000 goto py_dl_fail
echo [2/4] Stavlyu Python tikho (tolko dlya tekushchego polzovatelya, bez admina)...
"%TEMP%\accollab-python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 >> "%LOG%" 2>&1
set PY=%LocalAppData%\Programs\Python\Python312\python.exe
if not exist "%PY%" goto py_fail
del "%TEMP%\accollab-python.exe" >nul 2>&1
:py_found
echo [2/4] Python est:
%PY% --version
if errorlevel 1 goto py_fail

rem ---- Shag 3: Tapir ----
set APX=TapirAddOn_AC29_Win.apx
set ADDONS=C:\Program Files\GRAPHISOFT\ARCHICAD 29\Add-Ons
if exist "%ADDONS%\%APX%" goto tapir_ok
if not exist "%KIT%%APX%" goto tapir_dl
goto tapir_unblock
:tapir_dl
echo [3/4] Tapir ne nayden. Skachivayu s GitHub (~2 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/ENZYME-APD/tapir-archicad-automation/releases/download/1.5.9/TapirAddOn_AC29_Win.apx' -OutFile '%KIT%%APX%'" >> "%LOG%" 2>&1
if errorlevel 1 goto tapir_dl_fail
:tapir_unblock
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -Path '%KIT%%APX%'" >> "%LOG%" 2>&1
if not exist "%ADDONS%\" goto tapir_noaddons
copy /Y "%KIT%%APX%" "%ADDONS%\" >nul 2>&1
if exist "%ADDONS%\%APX%" goto tapir_ok
goto tapir_noadmin
:tapir_ok
echo [3/4] Tapir na meste. Ne zabudte perezapustit Archicad!
goto tapir_done
:tapir_noadmin
echo [3/4] Vnimanie: net zapisi v "%ADDONS%" (nuzhny prava administratora).
echo        Fayl %APX% uzhe skachan syuda: %KIT%%APX%
echo        Ruchnoy shag (odin raz, 1 minuta):
echo          1. Archicad 29 - Parametry - Dispetcher nadstroek (Add-On Manager)
echo          2. Knopka Add/Dobavit - vyberite etot APX - OK.
echo          3. Perezapustite Archicad.
goto tapir_done
:tapir_noaddons
echo [3/4] Vnimanie: papka "%ADDONS%" ne naydena.
echo        (Archicad stoit ne v standartnom meste?)
echo        Fayl %APX% uzhe skachan syuda: %KIT%%APX%
echo        Ruchnoy shag: polozhite ego v Add-Ons vashego Archicad 29
echo        libo podklyuchite cherez Dispetcher nadstroek - Add.
echo        Zatem perezapustite Archicad.
goto tapir_done
:tapir_done

rem ---- Shag 4: proverka ----
echo [4/4] Zapuskayu proverku okruzheniya...
%PY% "%KIT%check_env.py"
goto end

:py_dl_fail
echo OSHIBKA: ne smog skachat Python. Proverte internet. Podrobnosti: setup.log
echo Vruchnuyu: https://www.python.org/downloads/ (versiya 3.12, galochka Add to PATH)
goto end_pause
:py_fail
echo OSHIBKA: Python ne ustanovilsya. Sm. setup.log. Poprobuyte vruchnuyu s python.org
goto end_pause
:tapir_dl_fail
echo OSHIBKA: ne smog skachat Tapir s GitHub. Proverte internet. Sm. setup.log
echo Vruchnuyu: https://github.com/ENZYME-APD/tapir-archicad-automation/releases
echo (versiya 1.5.9, fayl TapirAddOn_AC29_Win.apx)
goto end_pause
:end_pause
pause
:end
