$ErrorActionPreference = "Stop"

$ScriptPath = $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptPath)
$Runner = Join-Path $Root "scripts\run_daily_db_update.ps1"

$TaskName = "KinCompetitorDbUpdate"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger -Daily -At 9:05AM
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName

