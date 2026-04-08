@echo off
setlocal enabledelayedexpansion

echo.
echo NOVA Windows Installer
echo ======================
echo.

where py >nul 2>&1
if %errorlevel% neq 0 (
  echo Python launcher not found. Attempting install via winget...
  where winget >nul 2>&1
  if %errorlevel% neq 0 (
    echo winget is not available. Install Python 3.12 manually and rerun.
    exit /b 1
  )
  winget install -e --id Python.Python.3.12
)

py -3 --version >nul 2>&1
if %errorlevel% neq 0 (
  echo Python 3 not available after installation attempt.
  exit /b 1
)

if not exist ".venv" (
  echo Creating virtual environment...
  py -3 -m venv .venv
)

call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
  echo Failed to activate virtual environment.
  exit /b 1
)

echo Upgrading pip tooling...
python -m pip install --upgrade pip setuptools wheel
if %errorlevel% neq 0 exit /b 1

if exist "requirements.lock" (
  echo Installing pinned dependencies from requirements.lock...
  pip install -r requirements.lock
) else (
  echo Installing dependencies from requirements.txt...
  pip install -r requirements.txt
)
if %errorlevel% neq 0 exit /b 1

echo Running deep PC scan...
python -m config.pc_scanner

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
  )
)

echo.
echo Installation complete.
echo Launch NOVA with:  python main.py
echo.
exit /b 0
