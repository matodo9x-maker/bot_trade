@echo off
chcp 65001 >nul
cd /d %~dp0\..

if not exist logs mkdir logs
if not exist data\runtime mkdir data\runtime

REM Prefer venv python if available
set PY=python
if exist venv\Scripts\python.exe set PY=venv\Scripts\python.exe

REM Use GUI env if present
set ENV_FILE=runtime_gui.env
if not exist "%ENV_FILE%" (
  echo [WARN] Không thấy %ENV_FILE%. Hãy mở Control Panel và bấm Lưu để tạo file env.
)

set BOT_ENV_FILE=%cd%\%ENV_FILE%

:loop
echo ===============================================================>> logs\runtime_trader_bg.log
echo START %date% %time% >> logs\runtime_trader_bg.log
echo BOT_ENV_FILE=%BOT_ENV_FILE% >> logs\runtime_trader_bg.log

"%PY%" -u -m apps.runtime_trader >> logs\runtime_trader_bg.log 2>&1

echo EXIT %date% %time% >> logs\runtime_trader_bg.log
timeout /t 5 /nobreak >nul
goto loop
