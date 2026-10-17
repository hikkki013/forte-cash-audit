@echo off
cd /d "%~dp0"
if exist "%~dp0python\python.exe" (
  "%~dp0python\python.exe" -I "%~dp0scripts\portable.py"
) else (
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
)
pause
