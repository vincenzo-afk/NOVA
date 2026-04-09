@echo off
setlocal enabledelayedexpansion
set "NOVA_GUI=0"
set "NOVA_SKIP_ONBOARDING=0"
set "NOVA_DRY_RUN=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--gui" set "NOVA_GUI=1"
if /I "%~1"=="--no-onboarding" set "NOVA_SKIP_ONBOARDING=1"
if /I "%~1"=="--dry-run" set "NOVA_DRY_RUN=1"
shift
goto parse_args
:args_done

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
  if "%NOVA_DRY_RUN%"=="1" (
    echo [dry-run] py -3 -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
)

call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
  echo Failed to activate virtual environment.
  exit /b 1
)

echo Upgrading pip tooling...
if "%NOVA_DRY_RUN%"=="1" (
  echo [dry-run] python -m pip install --upgrade pip setuptools wheel
) else (
  python -m pip install --upgrade pip setuptools wheel
)
if %errorlevel% neq 0 exit /b 1

if exist "requirements.lock" (
  echo Installing pinned dependencies from requirements.lock...
  if "%NOVA_DRY_RUN%"=="1" (
    echo [dry-run] pip install -r requirements.lock
  ) else (
    pip install -r requirements.lock
  )
) else (
  echo Installing dependencies from requirements.txt...
  if "%NOVA_DRY_RUN%"=="1" (
    echo [dry-run] pip install -r requirements.txt
  ) else (
    pip install -r requirements.txt
  )
)
if %errorlevel% neq 0 exit /b 1

echo Running deep PC scan...
if "%NOVA_DRY_RUN%"=="1" (
  echo [dry-run] python -m config.pc_scanner
) else (
  python -m config.pc_scanner
)

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
  )
)

echo.
echo Installation complete.
echo Launch NOVA with:  python main.py
if "%NOVA_SKIP_ONBOARDING%"=="1" (
  echo Onboarding skipped (--no-onboarding).
) else (
  if "%NOVA_DRY_RUN%"=="1" (
    if "%NOVA_GUI%"=="1" (
      echo [dry-run] python -m interfaces.onboarding --force --gui
    ) else (
      echo [dry-run] python -m interfaces.onboarding --force
    )
  ) else (
    if "%NOVA_GUI%"=="1" (
      python -m interfaces.onboarding --force --gui
    ) else (
      python -m interfaces.onboarding --force
    )
  )
)
echo.
exit /b 0
