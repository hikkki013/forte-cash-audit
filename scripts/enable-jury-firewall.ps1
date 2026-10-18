#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$caddy = (Join-Path (Get-Location) 'runtime\caddy-bin\caddy.exe')
if (!(Test-Path -LiteralPath $caddy)) { throw 'Install Caddy first: scripts\install-caddy.ps1' }
& netsh advfirewall firewall delete rule name='Forte Jury HTTPS (Caddy)' | Out-Null
& netsh advfirewall firewall add rule name='Forte Jury HTTPS (Caddy)' dir=in action=allow `
    program=$caddy enable=yes profile=private,public protocol=TCP localport=80,443
if ($LASTEXITCODE -ne 0) { throw 'Windows Firewall did not accept the Caddy rule.' }
Write-Host 'Opened TCP 80 and 443 only for Caddy. Forte port 8000 remains loopback-only.'
