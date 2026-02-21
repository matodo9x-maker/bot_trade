@echo off
setlocal
cd /d "%~dp0"

echo ==== WHERE AM I? ====
cd
echo.

echo ==== CHECK KEY FILES ====
dir /b control_panel_pro.py 2>nul
dir /b control_panel_pro.spec 2>nul
dir /b control_panel_pro_win10.spec 2>nul
echo.

echo ==== CHECK PROJECT FOLDERS ====
if exist apps (echo OK: apps\) else (echo MISSING: apps\)
if exist trade_ai (echo OK: trade_ai\) else (echo MISSING: trade_ai\)
echo.

echo ==== PYTHON PATH ====
where python
python --version
echo.

echo ==== VENV ====
if exist venv\Scripts\python.exe (echo OK: venv\Scripts\python.exe) else (echo NOTE: no venv\Scripts\python.exe)
echo.

echo ==== DONE ====
pause
