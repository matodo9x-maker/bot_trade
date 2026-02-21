@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

set TASK_NAME=BotTradeRuntime
set RUN_CMD=cmd /c "cd /d %cd% && scripts\run_bot_bg.bat"

echo ==========================================
echo Cài Task Scheduler: %TASK_NAME%
echo Bot sẽ chạy NGẦM và tự restart nếu bị lỗi
echo Log: logs\runtime_trader_bg.log
echo ==========================================

schtasks /Query /TN "%TASK_NAME%" >nul 2>nul
if %errorlevel%==0 (
  echo [WARN] Task đã tồn tại. Sẽ ghi đè...
  schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>nul
)

REM ONLOGON: chạy khi user đăng nhập
schtasks /Create /TN "%TASK_NAME%" /TR %RUN_CMD% /SC ONLOGON /F
if %errorlevel% neq 0 (
  echo [FAIL] Tạo task thất bại. Hãy chạy CMD bằng quyền Administrator rồi chạy lại.
  pause
  exit /b 1
)

echo [OK] Đã tạo task. Bạn có thể:
echo - Task Scheduler -> Task Scheduler Library -> %TASK_NAME%
echo - Hoặc restart máy / log out-in để bot tự chạy.
pause
