# Lance le serveur de controle du GLM 50 C et ouvre le navigateur.
# Usage : clic droit > Executer avec PowerShell, ou depuis un terminal : .\start_server.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$python = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Environnement virtuel introuvable : $python`nCree-le d'abord avec :`n  python -m venv .venv`n  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

Write-Host "Demarrage du serveur GLM 50 C..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $python -ArgumentList "server.py" -PassThru -NoNewWindow

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8000/"

Write-Host "Serveur lance (PID $($proc.Id)). Ctrl+C pour arreter." -ForegroundColor Green
try {
    Wait-Process -Id $proc.Id
} finally {
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}
