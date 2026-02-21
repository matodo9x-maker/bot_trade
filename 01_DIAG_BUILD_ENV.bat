@echo off
setlocal
cd /d "%~dp0"

echo ==== WHERE AM I? ====
echo %CD%
echo.

echo ==== CHECK KEY FILES ====
if exist control_panel_pro.py (echo OK: control_panel_pro.py) else (echo MISSING: control_panel_pro.py)
if exist control_panel_pro_win10.spec (echo OK: control_panel_pro_win10.spec) else (echo NOTE: no control_panel_pro_win10.spec)
if exist control_panel_pro.spec (echo OK: control_panel_pro.spec) else (echo NOTE: no control_panel_pro.spec)
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
