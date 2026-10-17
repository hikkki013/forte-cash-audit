@echo off
cd /d "%~dp0"
if exist "%~dp0python\python.exe" (
  "%~dp0python\python.exe" -I "%~dp0scripts\portable.py" --check
) else (
  echo This check requires the portable release. Download Forte-Windows from Releases.
)
pause
