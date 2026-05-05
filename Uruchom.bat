@echo off
cd /d "%~dp0"
title Shoplet Lead Generator — Przygotowanie
color 0A

echo.
echo  ============================================
echo   SHOPLET LEAD GENERATOR
echo  ============================================
echo.
echo  Trwa przygotowanie programu, prosze czekac...
echo.

:: ── KROK 1: Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% equ 0 goto :python_ok

echo  [1/4] Instalowanie Python 3.13...
echo        (moze to zajac 2-3 minuty)
echo.

winget --version >nul 2>&1
if %errorlevel% equ 0 (
    echo        Pobieranie Python przez Windows Package Manager...
    winget install Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements
    echo        Python zainstalowany.
    goto :refresh_path
)

echo        Pobieranie instalatora Python z python.org...
powershell -Command "Write-Host '        Laczenie z serwerem...'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe' -OutFile '%TEMP%\python_setup.exe'" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo  BLAD: Nie mozna pobrac Pythona.
    echo  Sprawdz polaczenie z internetem i sprobuj ponownie.
    echo.
    pause
    exit /b 1
)
echo        Instalowanie Python...
"%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
del "%TEMP%\python_setup.exe" >nul 2>&1
echo        Python zainstalowany.

:refresh_path
echo        Odswiezanie srodowiska...
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH 2^>nul') do set "USER_PATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "SYS_PATH=%%b"
set "PATH=%SYS_PATH%;%USER_PATH%"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Instalacja zakonczona. Wymagany restart komputera.
    echo  Zrestartuj komputer i uruchom Uruchom.bat ponownie.
    echo.
    pause
    exit /b 0
)

:python_ok
echo  [1/4] Python .................... OK
echo.

:: ── KROK 2: pip + zaleznosci ────────────────────────────────────────────────
echo  [2/4] Instalowanie wymaganych skladnikow...
echo        (streamlit, pandas, playwright, ddgs...)
echo        Moze to zajac 1-2 minuty przy pierwszym uruchomieniu.
echo.
python -m pip install --upgrade pip -q 2>nul
python -m pip install -r requirements_gmaps.txt -q
if %errorlevel% neq 0 (
    echo.
    echo  BLAD: Nie udalo sie zainstalowac skladnikow.
    echo  Sprawdz polaczenie z internetem i sprobuj ponownie.
    echo.
    pause
    exit /b 1
)
echo  [2/4] Skladniki ................. OK
echo.

:: ── KROK 3: Chromium ────────────────────────────────────────────────────────
echo  [3/4] Instalowanie przegladarki Chromium...
echo        (wymagana do przeszukiwania Google Maps)
echo        Przy pierwszym uruchomieniu: pobieranie ~130 MB, prosze czekac...
echo.
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo.
    echo  BLAD: Nie udalo sie zainstalowac przegladarki Chromium.
    echo.
    pause
    exit /b 1
)
echo  [3/4] Chromium .................. OK
echo.

:: ── KROK 4: Start ───────────────────────────────────────────────────────────
echo  [4/4] Uruchamianie aplikacji...
echo.
echo  ============================================
echo   Program gotowy! Otwieram przegladarke...
echo   Adres: http://localhost:8501
echo  ============================================
echo.
echo  Aby zatrzymac program: zamknij to okno.
echo.
title Shoplet Lead Generator — Dziala
python -m streamlit run app.py --browser.gatherUsageStats false --server.headless false
pause
