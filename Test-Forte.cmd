@echo off
cd /d "%~dp0"
if exist "%~dp0python\python.exe" (
  "%~dp0python\python.exe" -I -m pytest -q
) else (
  echo This test requires the portable release. Download Forte-Windows from Releases.
)
pause
