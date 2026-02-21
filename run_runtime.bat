@echo off
REM Run runtime trader loop (demo/data/paper/live) with env auto-load.
REM
REM Recommended:
REM   1) copy .env.example .env
REM   2) edit TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
REM   3) run: run_runtime.bat

cd /d %~dp0

python supervisor.py runtime

pause
