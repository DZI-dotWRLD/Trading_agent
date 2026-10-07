# Start the trading-update service: poll the inbox forever (ADR-0003). Stop with Ctrl+C.
#   .\start.ps1                     run the service
#   .\start.ps1 -Check              only check configuration, credentials and folders
#   .\start.ps1 -Config other.yaml  use another config file
# Logs go to the console and to data\service.log. See README.md, section 10.
param([switch]$Check, [string]$Config = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No .venv found. Run .\setup.ps1 first." }
$env:PYTHONIOENCODING = "utf-8"

$cfgArgs = @()
if ($Config) { $cfgArgs = @("--config", (Resolve-Path $Config).Path) }

if ($Check) {
    & $python -m agent @cfgArgs check
    exit $LASTEXITCODE
}
& $python -m agent @cfgArgs run
exit $LASTEXITCODE
