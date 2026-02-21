@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

REM Official MS links (Visual C++ 2015-2022)
set URL_X64=https://aka.ms/vs/17/release/vc_redist.x64.exe
set URL_X86=https://aka.ms/vs/17/release/vc_redist.x86.exe

set TMP=%TEMP%\vcredist_bottrade
if not exist "%TMP%" mkdir "%TMP%"

REM Detect installed via registry (best-effort)
set HAS_X64=0
set HAS_X86=0

reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "Microsoft Visual C++ 2015-2022 Redistributable" | find /i "x64" >nul && set HAS_X64=1
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "Microsoft Visual C++ 2015-2022 Redistributable" | find /i "x86" >nul && set HAS_X86=1

if %HAS_X64%==1 if %HAS_X86%==1 (
  echo [OK] VC++ Runtime 2015-2022 (x64+x86) da co
  exit /b 0
)

echo [WARN] Thieu VC++ Runtime:
if %HAS_X64%==0 echo - x64 chua co
if %HAS_X86%==0 echo - x86 chua co

choice /M "Ban co muon tai va cai tu dong (can internet) khong?"
if %errorlevel% neq 1 (
  echo Bo qua tu dong. Ban co the tu tai tu trang Microsoft:
  echo - Tim: Visual C++ Redistributable 2015-2022 (x64 va x86)
  exit /b 0
)

echo Dang tai...
if %HAS_X64%==0 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%URL_X64%' -OutFile '%TMP%\vc_redist.x64.exe'" || (
    echo [FAIL] Tai x64 that bai. Hay tai thu cong: %URL_X64%
  )
)
if %HAS_X86%==0 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%URL_X86%' -OutFile '%TMP%\vc_redist.x86.exe'" || (
    echo [FAIL] Tai x86 that bai. Hay tai thu cong: %URL_X86%
  )
)

echo Dang cai (quiet)...
if %HAS_X64%==0 if exist "%TMP%\vc_redist.x64.exe" (
  "%TMP%\vc_redist.x64.exe" /install /quiet /norestart
)
if %HAS_X86%==0 if exist "%TMP%\vc_redist.x86.exe" (
  "%TMP%\vc_redist.x86.exe" /install /quiet /norestart
)

echo [OK] Da chay installer. Neu van loi, hay restart may.
exit /b 0
