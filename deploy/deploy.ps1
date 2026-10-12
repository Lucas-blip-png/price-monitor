# Leva o bot para um servidor Linux (Ubuntu/Debian) e sobe com Docker. Rode de novo para atualizar.
#   .\deploy\deploy.ps1 -Server ubuntu@203.0.113.10 -Key C:\caminho\chave.key
# Antes de rodar: pare o bot local (`docker compose down`), senão os dois disputam o mesmo token.
param(
    [Parameter(Mandatory)] [string]$Server,
    [string]$Key
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env)) { throw '.env não encontrado: copie .env.example e preencha.' }

$git = Split-Path (Split-Path (Get-Command git).Source) -Parent  # ...\Git
$ssh = (Get-Command ssh -ErrorAction SilentlyContinue).Source ?? "$git\usr\bin\ssh.exe"
$scp = (Get-Command scp -ErrorAction SilentlyContinue).Source ?? "$git\usr\bin\scp.exe"
$opts = @('-o', 'StrictHostKeyChecking=accept-new') + $(if ($Key) { @('-i', $Key) })

$tar = Join-Path $env:TEMP 'price-monitor.tar'
git archive HEAD -o $tar  # só arquivos versionados: o .env nunca entra aqui
& $scp @opts $tar "${Server}:price-monitor.tar"
if (Test-Path data\price_monitor.db) { & $scp @opts data\price_monitor.db "${Server}:price_monitor.db" }

# .env por stdin (não passa por arquivo temporário legível por outros) e com permissão 600
(Get-Content .env -Raw) -replace "`r", '' | & $ssh @opts $Server 'umask 077; mkdir -p ~/price-monitor/data; cat > ~/price-monitor/.env'

$remote = @'
set -e
cd ~/price-monitor
tar -xf ~/price-monitor.tar && rm ~/price-monitor.tar
if [ -f ~/price_monitor.db ]; then [ -f data/price_monitor.db ] || mv ~/price_monitor.db data/; rm -f ~/price_monitor.db; fi
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sudo sh
sudo docker compose up -d --build
sudo docker compose ps
'@ -replace "`r", ''
& $ssh @opts $Server $remote
