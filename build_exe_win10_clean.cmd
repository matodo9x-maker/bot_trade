@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM ==========================================================
REM  Build Control Panel EXE (Win10) - CLEAN & STABLE
REM  - creates .build_venv
REM  - installs deps (incl. customtkinter)
REM  - cleans dist/build/__pycache__
REM  - builds using control_panel_pro.spec (onedir)
REM ==========================================================

set "VENV_DIR=.build_venv"
set "SPEC_FILE=control_panel_pro.spec"

cd /d "%~dp0"

echo.
echo [1/6] Check Python...
python --version 2>NUL
if errorlevel 1 (
  echo [ERROR] Khong tim thay 'python' trong PATH.
  echo -> Hay cai Python 3.10 x64 va tick "Add Python to PATH".
  pause
  exit /b 1
)

echo.
echo [2/6] Create build venv (if missing): %VENV_DIR%
if not exist "%VENV_DIR%\Scripts\python.exe" (
  python -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [ERROR] Tao venv that bai.
    pause
    exit /b 1
  )
)

call "%VENV_DIR%\Scripts\activate.bat"

echo.
echo [3/6] Install build deps...
python -m pip install --upgrade pip setuptools wheel >nul
python -m pip install "pyinstaller==5.13.2" >nul

REM Install project deps (requirements.txt includes customtkinter)
if exist "requirements.txt" (
  pip install -r requirements.txt
) else (
  echo [WARN] Khong thay requirements.txt, cai toi thieu...
  pip install python-dotenv psutil customtkinter darkdetect
)

echo.
echo [4/6] Syntax check (py_compile)...
python -m py_compile control_panel_pro.py
if errorlevel 1 (
  echo [FAIL] Loi cu phap trong control_panel_pro.py (py_compile).
  pause
  exit /b 1
)

echo.
echo [5/6] Clean build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -File -Include *.pyc,*.pyo | Remove-Item -Force" >nul 2>&1

echo.
echo [6/6] Build EXE...
if not exist "%SPEC_FILE%" (
  echo [ERROR] Khong tim thay %SPEC_FILE% trong thu muc nay.
  pause
  exit /b 1
)

pyinstaller "%SPEC_FILE%" --noconfirm --clean
if errorlevel 1 (
  echo [FAIL] Build that bai. Xem log ben tren.
  pause
  exit /b 1
)

echo.
echo DONE! EXE:
echo   dist\control_panel_pro\control_panel_pro.exe
echo NOTE: ONEDIR -> khong copy rieng .exe ra ngoai folder, can _internal\...
pause
