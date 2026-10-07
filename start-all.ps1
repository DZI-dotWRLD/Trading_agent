# Start the service and the dashboard together, each in its own window, then open the dashboard.
#   .\start-all.ps1                     check the configuration, then start both
#   .\start-all.ps1 -Config other.yaml  use another config file (for example config.test.yaml)
#   .\start-all.ps1 -Port 8502          dashboard on another port
# Anything already running is left alone: the service is found by its heartbeat (the dashboard's status
# line reads the same file), the dashboard by its port. Close a window, or press Ctrl+C in it, to stop that part.
param([string]$Config = "", [int]$Port = 8501)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No .venv found. Run .\setup.ps1 first." }
$env:PYTHONIOENCODING = "utf-8"
$cfgArg = ""
$cfgPath = "$PSScriptRoot\config.yaml"
if ($Config) { $cfgPath = (Resolve-Path $Config).Path; $cfgArg = " -Config `"$cfgPath`"" }

& "$PSScriptRoot\start.ps1" -Check -Config $cfgPath
if ($LASTEXITCODE -ne 0) { throw "Configuration check failed; fix it before starting." }

$probe = "import sys; from agent import config, heartbeat; from datetime import datetime; " +
         "c = config.load(sys.argv[1]); print(heartbeat.read_status(c.state_file, datetime.now().astimezone())['state'])"
$state = (& $python -c $probe $cfgPath | Select-Object -Last 1)
if ($state -in @("running", "busy")) {
    Write-Host "Service is already running ($state); not starting a second one."
} else {
    Start-Process powershell.exe -WorkingDirectory $PSScriptRoot -WindowStyle Minimized `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSScriptRoot\start.ps1`"$cfgArg"
    Write-Host "Service started in a minimised window (logs also in data\service.log)."
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Dashboard is already running on port $Port."
    Start-Process "http://localhost:$Port"
} else {
    Start-Process powershell.exe -WorkingDirectory $PSScriptRoot -WindowStyle Minimized `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSScriptRoot\start-dashboard.ps1`" -Port $Port$cfgArg"
    Write-Host "Dashboard starting at http://localhost:$Port (opens in the browser in a few seconds)."
}
