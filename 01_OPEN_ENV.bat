@echo off
chcp 65001 >nul
cd /d %~dp0

if not exist .env (
  if exist .env.example (
    copy .env.example .env >nul
    echo [OK] Đã tạo .env từ .env.example
  ) else (
    echo [WARN] Không thấy .env.example, hãy tự tạo file .env
  )
)

start "" notepad ".env"
