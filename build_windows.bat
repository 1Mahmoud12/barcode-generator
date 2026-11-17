@echo off
REM Build the Windows folder distribution.
REM
REM Run this ON WINDOWS. PyInstaller cannot cross-compile: it bundles the Python
REM interpreter of the machine it runs on, so building on macOS produces a macOS app.
REM
REM Double-click, or run from cmd in this folder.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ================================================
echo  IVD pack tooling - Windows build
echo ================================================
echo.

REM ---- 1. Python present? -------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [X] python was not found on PATH.
    echo     Install Python 3.11 or newer from python.org and tick
    echo     "Add python.exe to PATH", then run this again.
    goto :end_fail
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/6] Python !PYVER! found.

REM ---- 2. Virtual environment --------------------------------------------
if not exist .venv (
    echo [2/6] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :end_fail
) else (
    echo [2/6] Virtual environment already exists.
)
call .venv\Scripts\activate.bat
if errorlevel 1 goto :end_fail

REM ---- 3. Dependencies ---------------------------------------------------
echo [3/6] Installing dependencies...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [X] Dependency install failed. Check your internet connection.
    goto :end_fail
)
pip install pyinstaller --quiet
if errorlevel 1 goto :end_fail

REM ---- 4. Self-check BEFORE packaging ------------------------------------
echo [4/6] Running the self-check...
python selftest.py
if errorlevel 1 (
    echo.
    echo [X] The self-check failed. Nothing was packaged.
    echo     A build is only offered when every symbol decodes back correctly,
    echo     so a broken build cannot reach a lab.
    goto :end_fail
)

REM ---- 5. zint check (optional but needed for GS1) -----------------------
echo [5/6] Checking for zint (GS1 DataMatrix)...
where zint >nul 2>&1
if errorlevel 1 (
    echo     [!] zint not found on PATH.
    echo         The GS1 DataMatrix tabs will refuse to build until it is installed:
    echo             choco install zint
    echo         Or download from https://zint.org.uk and put zint.exe on PATH.
    echo         The build continues; everything else works without it.
) else (
    for /f "tokens=2" %%v in ('zint --version 2^>^&1 ^| findstr /i "version"') do echo     zint %%v
)

REM ---- 6. Package --------------------------------------------------------
echo [6/6] Packaging...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller build.spec --noconfirm
if errorlevel 1 (
    echo [X] Packaging failed.
    goto :end_fail
)

echo.
echo ================================================
echo  Done.
echo ================================================
echo.
echo  Program folder: dist\IVDPackTooling\
echo  Executable:     dist\IVDPackTooling\IVDPackTooling.exe
echo.
echo  Copy the whole IVDPackTooling folder to the target machine.
echo  zint.exe must be installed separately there for GS1 DataMatrix.
echo.
pause
exit /b 0

:end_fail
echo.
echo Build did not complete.
pause
exit /b 1
