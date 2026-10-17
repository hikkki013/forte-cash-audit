$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (!(Test-Path '.venv\Scripts\python.exe')) { throw 'First run scripts\setup.ps1 with Python 3.12.' }
New-Item -ItemType Directory -Force -Path 'runtime' | Out-Null
if (!$env:FORTE_API_KEY) {
    $keyPath = Join-Path (Get-Location) 'runtime\api-key.txt'
    if (!(Test-Path -LiteralPath $keyPath)) {
        $keyBytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($keyBytes)
        $rng.Dispose()
        [System.IO.File]::WriteAllText($keyPath, [Convert]::ToBase64String($keyBytes))
    }
    $env:FORTE_API_KEY = [System.IO.File]::ReadAllText($keyPath).Trim()
    Write-Host 'API key: runtime\api-key.txt (keep private; do not commit)'
}
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONUTF8 = '1'
Write-Host 'Open the web interface: http://127.0.0.1:8000 ; stop with Ctrl+C'
& '.\.venv\Scripts\python.exe' -m uvicorn forte.api:app --host 127.0.0.1 --port 8000 --workers 1
exit $LASTEXITCODE
