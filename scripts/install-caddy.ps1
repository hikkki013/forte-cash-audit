$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$target = Join-Path (Get-Location) 'runtime\caddy-bin'
New-Item -ItemType Directory -Force -Path $target | Out-Null
Invoke-WebRequest -Uri 'https://caddyserver.com/api/download?os=windows&arch=amd64' -OutFile (Join-Path $target 'caddy.exe')
& (Join-Path $target 'caddy.exe') version
