# One-time setup for the VSCP trading-update agent (ADR-0012). Safe to run again.
#   .\setup.ps1
# Installs dependencies into .venv, checks for a recalculation engine, creates .env from
# .env.example if missing, and runs the configuration check. See README.md.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  [ok] $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  [!]  $text" -ForegroundColor Yellow }

Step "Python dependencies"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Warn "uv is not installed. Install it (no admin rights needed), open a new PowerShell window, then run this again:"
    Write-Host '       powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    exit 1
}
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
Ok "dependencies installed in .venv"

Step "Recalculation engine (LibreOffice or Excel)"
$soffice = @("$env:ProgramFiles\LibreOffice\program\soffice.exe", "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe") |
    Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$excel = Test-Path "Registry::HKEY_CLASSES_ROOT\Excel.Application"
if ($soffice) { Ok "LibreOffice: $soffice" }
elseif ($excel) { Ok "Microsoft Excel (used through COM; LibreOffice is preferred for an unattended PC)" }
else {
    Warn "Neither LibreOffice nor Excel found. Outputs cannot be validated, so nothing would be published."
    Warn "Install LibreOffice from https://www.libreoffice.org/download/ and run this again."
}

Step "Secrets (.env)"
if (Test-Path .env) { Ok ".env exists (left unchanged)" }
else {
    Copy-Item .env.example .env
    Warn ".env created from .env.example. Fill in ANTHROPIC_API_KEY and the mailbox credentials:"
    Write-Host "       notepad .env"
}

Step "Configuration check"
# The shared drive and the companies' files are VSCP's own: setup never creates or changes anything under root.
$py = "$PSScriptRoot\.venv\Scripts\python.exe"
& $py -m agent check
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nReady. Start the service with .\start.ps1 and the dashboard with .\start-dashboard.ps1" -ForegroundColor Green
    Write-Host "To start the service automatically at logon: .\install-autostart.ps1"
} else {
    Write-Host "`nFix the items marked above (config.yaml, companies\*.yaml, .env), then run: .\start.ps1 -Check" -ForegroundColor Yellow
}
