@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist logs mkdir logs
start "" explorer "%cd%\logs"
