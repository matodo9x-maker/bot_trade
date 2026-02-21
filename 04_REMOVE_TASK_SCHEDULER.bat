@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

set TASK_NAME=BotTradeRuntime

schtasks /Query /TN "%TASK_NAME%" >nul 2>nul
if %errorlevel% neq 0 (
  echo [WARN] Không thấy task %TASK_NAME%
  pause
  exit /b 0
)

schtasks /Delete /TN "%TASK_NAME%" /F
if %errorlevel% neq 0 (
  echo [FAIL] Xóa task thất bại. Hãy chạy CMD bằng quyền Administrator.
  pause
  exit /b 1
)

echo [OK] Đã xóa task %TASK_NAME%
pause
