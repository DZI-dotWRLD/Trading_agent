# Start the service automatically when this user logs on, and restart it if it stops (ADR-0012).
#   .\install-autostart.ps1              register the "VSCP Trading Agent" scheduled task
#   .\install-autostart.ps1 -Dashboard   also register "VSCP Dashboard" (localhost:8501)
#   .\install-autostart.ps1 -Uninstall   remove both tasks
# Runs as the current user, so no admin rights are needed. For production, run it while logged on
# as the dedicated service account (docs/NEXT_STEPS.md, section 2).
param([switch]$Dashboard, [switch]$Uninstall)
$ErrorActionPreference = "Stop"

$tasks = @{ "VSCP Trading Agent" = "start.ps1"; "VSCP Dashboard" = "start-dashboard.ps1" }

if ($Uninstall) {
    foreach ($name in $tasks.Keys) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed '$name'"
        }
    }
    exit 0
}

if (-not (Test-Path "$PSScriptRoot\.venv\Scripts\python.exe")) { throw "No .venv found. Run .\setup.ps1 first." }
& "$PSScriptRoot\start.ps1" -Check
if ($LASTEXITCODE -ne 0) { throw "Configuration check failed; fix it before installing autostart." }

$user = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$install = @("VSCP Trading Agent")
if ($Dashboard) { $install += "VSCP Dashboard" }
foreach ($name in $install) {
    $script = Join-Path $PSScriptRoot $tasks[$name]
    $extra = if ($name -eq "VSCP Dashboard") { " -NoBrowser" } else { "" }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $PSScriptRoot `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"$extra"
    Register-ScheduledTask -TaskName $name -Trigger $trigger -Principal $principal -Settings $settings -Action $action `
        -Description "VSCP trading-update automation ($($tasks[$name])). Installed by install-autostart.ps1." -Force | Out-Null
    Write-Host "Registered '$name': starts at logon of $user, restarts every 5 min if it stops." -ForegroundColor Green
}
Write-Host "`nStart now without logging off:  Start-ScheduledTask -TaskName 'VSCP Trading Agent'"
Write-Host "Check it:                       Get-ScheduledTask -TaskName 'VSCP*' | Get-ScheduledTaskInfo"
Write-Host "Logs:                           data\service.log"
