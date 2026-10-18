$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$domainPath = Join-Path (Get-Location) 'runtime\jury-domain.txt'
$caddyPath = Join-Path (Get-Location) 'runtime\caddy-bin\caddy.exe'
$pythonPath = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw 'Missing .venv. Run scripts\setup.ps1 first.' }
if (!(Test-Path -LiteralPath $caddyPath)) { throw 'Missing runtime\caddy-bin\caddy.exe. Run scripts\install-caddy.ps1 first.' }
if (!(Test-Path -LiteralPath $domainPath)) { throw 'Missing runtime\jury-domain.txt.' }

$env:FORTE_JURY_DOMAIN = [IO.File]::ReadAllText($domainPath).Trim()
if (!$env:FORTE_JURY_DOMAIN) { throw 'runtime\jury-domain.txt is empty.' }

$keyPath = Join-Path (Get-Location) 'runtime\api-key.txt'
if (!(Test-Path -LiteralPath $keyPath)) {
    $keyBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($keyBytes)
    $rng.Dispose()
    [IO.File]::WriteAllText($keyPath, [Convert]::ToBase64String($keyBytes))
}
$env:FORTE_API_KEY = [IO.File]::ReadAllText($keyPath).Trim()
$env:FORTE_API_KEY_ONLY = '1'
$env:FORTE_AUDIT_LOG = Join-Path (Get-Location) 'runtime\jury-audit.jsonl'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONUTF8 = '1'

$configPath = Join-Path (Get-Location) 'deploy\Caddyfile'
& $caddyPath validate --config $configPath --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy configuration is invalid.' }

Write-Host "Jury API: https://$env:FORTE_JURY_DOMAIN"
Write-Host 'Share the URL and the key in runtime\api-key.txt only with the jury.'
Write-Host 'Audit events without video data: runtime\jury-audit.jsonl'
$caddy = Start-Process -FilePath $caddyPath -ArgumentList @('run', '--config', $configPath, '--adapter', 'caddyfile') -PassThru -WindowStyle Hidden
try {
    & $pythonPath -m uvicorn forte.api:app --host 127.0.0.1 --port 8000 --workers 1
} finally {
    if (!$caddy.HasExited) { Stop-Process -Id $caddy.Id -Force }
}
exit $LASTEXITCODE
