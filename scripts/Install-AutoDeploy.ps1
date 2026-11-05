[CmdletBinding()]
param(
    [string]$TaskName = 'Ballroom Stats Analyzer - GitHub Update',
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$At = '08:00'
)

$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$scriptPath = Join-Path $PSScriptRoot 'Update-FromGitHub.ps1'
$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $scriptPath
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Once each morning, fast-forward clean main from GitHub and rebuild only the app if its deployed commit changed. Logs: project\tmp\auto-deploy.' -Force | Out-Null
Write-Output "Installed '$TaskName' daily at $At in the PC's local time zone."
Write-Output 'Runs while this user is signed in. A missed run starts when available. Docker Desktop must be running.'
