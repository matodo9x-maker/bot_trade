@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d %~dp0

echo ==========================================================
echo   BOT_TRADE - ONE CLICK SETUP (Win10)
echo   - tao venv + cai thu vien
echo   - tao .env neu chua co
echo   - build Control Panel EXE
echo   - kiem tra / cai VC++ Runtime
echo   - tao shortcut ra Desktop
echo   - (tuy chon) tao Task Scheduler chay bot ngam
echo ==========================================================

REM ----------------------------------------------------------
REM 1) Detect Python launcher
REM ----------------------------------------------------------
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py
) else (
  set PY=python
)

echo.
echo [1/7] Kiem tra Python...
%PY% --version
if %errorlevel% neq 0 (
  echo [FAIL] Khong tim thay Python. Hay cai Python 3.10/3.11 va tick "Add Python to PATH".
  pause
  exit /b 1
)

REM ----------------------------------------------------------
REM 2) Create venv
REM ----------------------------------------------------------
echo.
echo [2/7] Tao venv (neu chua co)...
if not exist venv (
  %PY% -m venv venv
  if %errorlevel% neq 0 (
    echo [FAIL] Tao venv that bai.
    pause
    exit /b 1
  )
) else (
  echo [OK] venv da ton tai
)

REM ----------------------------------------------------------
REM 3) Activate venv
REM ----------------------------------------------------------
echo.
echo [3/7] Kich hoat venv...
call venv\Scripts\activate
if %errorlevel% neq 0 (
  echo [FAIL] Activate venv that bai.
  pause
  exit /b 1
)

REM ----------------------------------------------------------
REM 4) Install deps
REM ----------------------------------------------------------
echo.
echo [4/7] Cai thu vien...
python -m pip install --upgrade pip >nul
if exist requirements.txt (
  pip install -r requirements.txt
) else (
  echo [WARN] Khong thay requirements.txt (bo qua)
)
pip install customtkinter darkdetect python-dotenv pyinstaller

REM ----------------------------------------------------------
REM 5) Create .env
REM ----------------------------------------------------------
echo.
echo [5/7] Tao .env neu chua co...
if not exist .env (
  if exist .env.example (
    copy .env.example .env >nul
    echo [OK] Da tao .env tu .env.example (hay mo .env va dien API KEY)
  ) else (
    echo [WARN] Khong thay .env.example. Hay tu tao file .env.
  )
) else (
  echo [OK] .env da ton tai
)

REM ----------------------------------------------------------
REM 6) Build EXE (onedir - on dinh nhat)
REM ----------------------------------------------------------
echo.
echo [6/7] Build EXE Control Panel...
if not exist control_panel_pro.py (
  echo [FAIL] Thieu file control_panel_pro.py. Hay dam bao ban dang o dung thu muc bot_trade.
  pause
  exit /b 1
)

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

python -m PyInstaller --clean --noconfirm control_panel_pro.spec

if %errorlevel% neq 0 (
  echo [FAIL] Build EXE that bai. Hay chay lai bang CMD va gui log.
  pause
  exit /b 1
)

REM ----------------------------------------------------------
REM 7) VC++ runtime + shortcut + optional task scheduler
REM ----------------------------------------------------------
echo.
echo [7/7] Kiem tra VC++ Runtime 2015-2022...
call tools\win\check_and_install_vcredist.bat

echo.
echo Tao shortcut ra Desktop...
powershell -ExecutionPolicy Bypass -File tools\win\create_desktop_shortcut.ps1 -Target "%cd%\dist\control_panel_pro\control_panel_pro.exe" -Name "BOT_TRADE_CONTROL_PRO"

echo.
choice /M "Ban co muon tao Task Scheduler chay bot ngam (auto restart) khong?"
if %errorlevel%==1 (
  call 03_INSTALL_TASK_SCHEDULER.bat
) else (
  echo Bo qua Task Scheduler.
)

echo.
echo [OK] XONG!
echo - Mo Panel: dist\control_panel_pro\control_panel_pro.exe
echo - Mo .env:  01_OPEN_ENV.bat
echo - Xem logs: 05_OPEN_LOGS.bat
pause
