@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "SPEC_FILE=control_panel_pro_win10.spec"
if not exist "%SPEC_FILE%" set "SPEC_FILE=control_panel_pro.spec"
set "VENV_DIR=.build_venv"

echo Build started at %DATE% %TIME%> build_exe.log
echo Working dir: %CD%>> build_exe.log
echo Using SPEC_FILE=%SPEC_FILE%>> build_exe.log
echo.>> build_exe.log

echo [1/7] Check entry + spec...
if not exist "control_panel_pro.py" (
  echo [ERROR] Missing control_panel_pro.py in %CD%>> build_exe.log
  echo [ERROR] Sai thu muc. Hay giai nen goi vao thu muc goc du an.
  pause
  exit /b 1
)
if not exist "%SPEC_FILE%" (
  echo [ERROR] Missing spec file: %SPEC_FILE%>> build_exe.log
  echo [ERROR] Thieu spec file. Hay giai nen goi vao thu muc goc du an.
  pause
  exit /b 1
)

echo [2/7] Check Python...
python --version 1>>build_exe.log 2>>&1
if errorlevel 1 (
  echo [ERROR] python not found.>>build_exe.log
  type build_exe.log
  pause
  exit /b 1
)

echo [3/7] Create build venv (if needed): %VENV_DIR% ...
if not exist "%VENV_DIR%\Scripts\python.exe" (
  python -m venv "%VENV_DIR%" 1>>build_exe.log 2>>&1
  if errorlevel 1 (
    echo [ERROR] Create venv failed.>>build_exe.log
    type build_exe.log
    pause
    exit /b 1
  )
)

call "%VENV_DIR%\Scripts\activate.bat" 1>>build_exe.log 2>>&1

echo [4/7] Install build deps...
python -m pip install --upgrade pip setuptools wheel 1>>build_exe.log 2>>&1
python -m pip install "pyinstaller==5.13.2" 1>>build_exe.log 2>>&1
python -m pip install "customtkinter>=5.2.0" "darkdetect>=0.8.0" 1>>build_exe.log 2>>&1

if exist requirements.txt (
  python -m pip install -r requirements.txt 1>>build_exe.log 2>>&1
) else (
  python -m pip install "python-dotenv>=1.0.0" "psutil>=5.9.0" 1>>build_exe.log 2>>&1
)

echo [5/7] Clean build artifacts...
if exist "build" rmdir /s /q "build" 1>>build_exe.log 2>>&1
if exist "dist" rmdir /s /q "dist" 1>>build_exe.log 2>>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force" 1>>build_exe.log 2>>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -File -Include *.pyc,*.pyo | Remove-Item -Force" 1>>build_exe.log 2>>&1

echo [6/7] Build with PyInstaller...
pyinstaller "%SPEC_FILE%" --noconfirm --clean 1>>build_exe.log 2>>&1
if errorlevel 1 (
  echo [FAIL] PyInstaller failed. See build_exe.log
  echo ===== LAST 60 LINES =====
  powershell -NoProfile -Command "Get-Content build_exe.log -Tail 60"
  pause
  exit /b 1
)

echo [7/7] DONE!
echo Output: dist\control_panel_pro\control_panel_pro.exe
echo Build finished at %DATE% %TIME%>> build_exe.log

echo ===== LAST 40 LINES =====
powershell -NoProfile -Command "Get-Content build_exe.log -Tail 40"
pause
