$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$root = Get-Location
$pythonPath = Join-Path $root '.venv\Scripts\python.exe'
$cloudflaredPath = Join-Path $root 'runtime\cloudflared-bin\cloudflared.exe'
$runtimeDir = Join-Path $root 'runtime'
$keyPath = Join-Path $runtimeDir 'api-key.txt'
$urlPath = Join-Path $runtimeDir 'jury-tunnel-url.txt'
$apiOutput = Join-Path $runtimeDir 'jury-api.stdout.log'
$apiError = Join-Path $runtimeDir 'jury-api.stderr.log'

if (!(Test-Path -LiteralPath $pythonPath)) { throw 'Missing .venv. Run scripts\setup.ps1 first.' }
if (!(Test-Path -LiteralPath $cloudflaredPath)) { throw 'Missing cloudflared. Run scripts\install-cloudflared.ps1 first.' }
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
Remove-Item -LiteralPath $urlPath -Force -ErrorAction SilentlyContinue

if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is already in use. Stop the other Forte server before starting the jury tunnel.'
}

if (!(Test-Path -LiteralPath $keyPath)) {
    $keyBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($keyBytes)
    $rng.Dispose()
    [IO.File]::WriteAllText($keyPath, [Convert]::ToBase64String($keyBytes))
}

$env:FORTE_API_KEY = [IO.File]::ReadAllText($keyPath).Trim()
$env:FORTE_API_KEY_ONLY = '1'
$env:FORTE_AUDIT_LOG = Join-Path $runtimeDir 'jury-audit.jsonl'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONUTF8 = '1'

Write-Host 'Starting Forte on 127.0.0.1:8000...'
$api = Start-Process -FilePath $pythonPath `
    -ArgumentList @('-m', 'uvicorn', 'forte.api:app', '--host', '127.0.0.1', '--port', '8000', '--workers', '1') `
    -PassThru -WindowStyle Hidden -RedirectStandardOutput $apiOutput -RedirectStandardError $apiError

try {
    $ready = $false
    # A cold Windows machine can take a while to initialize Python and its
    # security scanner. Do not publish a tunnel until the local service answers.
    for ($attempt = 0; $attempt -lt 180; $attempt++) {
        Start-Sleep -Seconds 1
        if ($api.HasExited) {
            $details = if (Test-Path -LiteralPath $apiError) { Get-Content -LiteralPath $apiError -Raw } else { '' }
            throw "Forte stopped during startup. $details"
        }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (!$ready) { throw 'Forte did not answer on 127.0.0.1:8000 within 3 minutes.' }

    Write-Host 'Opening a temporary public Cloudflare HTTPS tunnel...'
    Write-Host 'Copy the https://...trycloudflare.com address shown below, add /docs, and send it with the key only to the jury.'
    Write-Host 'The public address stops working when this window is closed.'
    & $cloudflaredPath tunnel --url http://127.0.0.1:8000 2>&1 | ForEach-Object {
        $line = $_.ToString()
        Write-Host $line
        if ($line -match 'https://[-a-z0-9]+\.trycloudflare\.com') {
            [IO.File]::WriteAllText($urlPath, $Matches[0])
            Write-Host "Jury API address saved to $urlPath"
        }
    }
    $exitCode = $LASTEXITCODE
} finally {
    if ($api -and !$api.HasExited) { Stop-Process -Id $api.Id -Force }
}
exit $exitCode
