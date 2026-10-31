@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Race Engineer installeren
echo.
echo  ==============================================
echo     AI Race Engineer - installeren
echo  ==============================================
echo.
echo  Dit bouwt het programma op deze pc en zet het in je Startmenu
echo  en op je bureaublad. Duurt de eerste keer 3-5 minuten.
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo  Python is nodig om het programma eenmalig te bouwen.
  echo  Installeer Python via https://www.python.org/downloads/
  echo  en vink tijdens de installatie "Add python.exe to PATH" aan.
  echo  Start daarna dit bestand opnieuw.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

echo  [1/4] Bouwomgeving maken...
python -m venv _bouw
call _bouw\Scripts\activate.bat
python -m pip install --upgrade pip -q

echo  [2/4] Onderdelen downloaden...
pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
  echo  Downloaden mislukt. Controleer je internetverbinding en probeer opnieuw.
  pause
  exit /b 1
)
pip install -q SpeechRecognition pyaudio >nul 2>nul || echo  (Microfoon-onderdelen overgeslagen: vragen stellen met je stem werkt dan niet)

echo  [3/4] Programma bouwen...
pip install -q pywin32 comtypes >nul 2>nul
python installer\set_version.py 2.0.0
pyinstaller --noconfirm --clean --log-level WARN RaceEngineer.spec
if not exist "dist\RaceEngineer\RaceEngineer.exe" (
  echo  Bouwen mislukt. Stuur de foutmelding hierboven naar Claude.
  pause
  exit /b 1
)

echo  [4/4] Installeren...
set "DEST=%LOCALAPPDATA%\Programs\RaceEngineer"
taskkill /im RaceEngineer.exe /f >nul 2>nul
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /e /i /q /y "dist\RaceEngineer" "%DEST%" >nul

powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell);" ^
  "foreach($p in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))){" ^
  "$l=$s.CreateShortcut((Join-Path $p 'AI Race Engineer.lnk'));" ^
  "$l.TargetPath='%DEST%\RaceEngineer.exe'; $l.WorkingDirectory='%DEST%'; $l.IconLocation='%DEST%\RaceEngineer.exe'; $l.Save()}"

call deactivate
echo.
echo  Klaar! Je vindt "AI Race Engineer" op je bureaublad en in het Startmenu.
echo  Deze map mag je daarna weggooien.
echo.
start "" "%DEST%\RaceEngineer.exe"
pause
