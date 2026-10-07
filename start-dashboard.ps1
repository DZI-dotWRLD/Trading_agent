# Start the VSCP portfolio dashboard (ADR-0011) at http://localhost:8501 (this PC only).
#   .\start-dashboard.ps1 [-Port 8501] [-Config path\to\config.yaml] [-NoBrowser]
param([int]$Port = 8501, [string]$Config = "", [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No .venv found. Run .\setup.ps1 first." }
if ($Config) { $env:VSCP_CONFIG = (Resolve-Path $Config).Path }
if (-not $NoBrowser) { Start-Job { Start-Sleep 4; Start-Process "http://localhost:$using:Port" } | Out-Null }
& $python -m streamlit run dashboard\app.py --server.port $Port --server.address localhost --server.headless true --browser.gatherUsageStats false
