@echo off
chcp 65001 >nul
cd /d %~dp0

if exist docs\WORKFLOW.md start "" notepad "docs\WORKFLOW.md"
if exist docs\CONFIG_MATRIX.md start "" notepad "docs\CONFIG_MATRIX.md"
if exist docs\OPERATOR_GUIDE_FUTURES.md start "" notepad "docs\OPERATOR_GUIDE_FUTURES.md"
if exist docs\VPS_SETUP.md start "" notepad "docs\VPS_SETUP.md"

echo [OK] Đã mở các file hướng dẫn (nếu tồn tại).
