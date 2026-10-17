param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) {
    & $Python -c "import sys; assert sys.version_info[:2] == (3,12), 'Use Python 3.12'"
    if ($LASTEXITCODE) { throw 'Python 3.12 is required' }
    & $Python -m venv .venv
    if ($LASTEXITCODE) { throw 'venv failed' }
}
& '.\.venv\Scripts\python.exe' -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE) { throw 'PyTorch install failed' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE) { throw 'Dependencies install failed' }
$env:HF_HUB_DISABLE_XET = '1'
& '.\.venv\Scripts\python.exe' -m scripts.download_model
if ($LASTEXITCODE) { throw 'Model download failed' }
& '.\.venv\Scripts\python.exe' -m pytest -q
exit $LASTEXITCODE
