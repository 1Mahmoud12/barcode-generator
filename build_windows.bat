@echo off
REM Build a standalone Windows folder. Run from the project root.
setlocal

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt || goto :error
pip install pyinstaller || goto :error

echo.
echo Running self-check before packaging...
python selftest.py || goto :selftest_failed

echo.
echo Building...
pyinstaller --noconfirm --windowed --name BarcodeSheet ^
    --add-data "bcgen;bcgen" ^
    app.py || goto :error

echo.
echo Done. See dist\BarcodeSheet\BarcodeSheet.exe
goto :eof

:selftest_failed
echo Self-check failed. Nothing was packaged.
exit /b 1

:error
echo Build failed.
exit /b 1
