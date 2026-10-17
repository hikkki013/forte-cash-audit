$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) { throw 'Install dependencies first (see README).' }
& '.\.venv\Scripts\python.exe' -m pytest -q
if ($LASTEXITCODE) { throw 'Python tests failed' }
if (!(Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22+ to run frontend checks.' }
& node tests/frontend.cjs
if ($LASTEXITCODE) { throw 'Frontend checks failed' }
& '.\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE) { throw 'Dependency check failed' }
Write-Host 'All code checks passed. This does NOT measure model accuracy.'
