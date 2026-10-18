$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$targetDir = Join-Path (Get-Location) 'runtime\cloudflared-bin'
$targetPath = Join-Path $targetDir 'cloudflared.exe'
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

# Official Cloudflare release binary for Windows x64. This directory is ignored by Git.
Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' `
    -OutFile $targetPath
& $targetPath --version
if ($LASTEXITCODE -ne 0) { throw 'cloudflared did not start after download.' }
