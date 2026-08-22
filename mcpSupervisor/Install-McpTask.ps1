<#
  Install-McpTask.ps1 - register (or refresh) the single MCP-Supervisor scheduled task,
  and retire the legacy per-server keep-alive tasks it replaces.

  Requires elevation (registering scheduled tasks needs admin on this machine). If not
  already elevated, this script relaunches itself via UAC - approve the prompt.

  The task runs Supervise-Mcp.ps1 as the logged-on user at logon, so the servers it
  launches inherit the user-scope environment - including any credentials they declare
  in 'requiredEnv'. Idempotent (-Force).
#>
param(
  [switch]$SkipLegacyCleanup   # keep the old Email Handler / sjv-mcp tasks in place
)
$ErrorActionPreference = 'Stop'

# --- self-elevate -----------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host 'Elevation required to register scheduled tasks. Relaunching via UAC...' -ForegroundColor Yellow
  $relaunchArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File', "`"$PSCommandPath`"")
  if ($SkipLegacyCleanup) { $relaunchArgs += '-SkipLegacyCleanup' }
  try {
    Start-Process powershell.exe -Verb RunAs -ArgumentList $relaunchArgs
    Write-Host 'Approve the UAC prompt in the elevated window to finish.' -ForegroundColor Yellow
  } catch {
    Write-Host "Could not self-elevate: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Run this script from an elevated PowerShell instead:" -ForegroundColor Red
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -ForegroundColor Red
  }
  return
}

$TaskName    = 'MCP-Supervisor'
$SuperScript = Join-Path $PSScriptRoot 'Supervise-Mcp.ps1'
if (-not (Test-Path $SuperScript)) { throw "Supervisor script not found: $SuperScript" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$SuperScript`"")

$trigger = New-ScheduledTaskTrigger -AtLogOn

# Run as the logged-on user (Interactive) so user-scope env vars are visible; non-elevated.
$principal = New-ScheduledTaskPrincipal `
  -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) `
  -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

try {
  Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Keeps the local MCP HTTP servers listed in mcp-servers.json alive. See $PSScriptRoot." `
    -Force | Out-Null
  Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "Started '$TaskName'." -ForegroundColor Green
} catch {
  Write-Host "FAILED to register/start '$TaskName': $($_.Exception.Message)" -ForegroundColor Red
  throw
}

# --- retire legacy per-server tasks that would compete for the same ports ----
if (-not $SkipLegacyCleanup) {
  $legacyNames = @('Email Handler','ZP-MailProxyWatchdog','sjv-mcp')
  $legacy = Get-ScheduledTask | Where-Object { $legacyNames -contains $_.TaskName }
  foreach ($t in $legacy) {
    try {
      Stop-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue
      Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false
      Write-Host ("Retired legacy task: {0}{1}" -f $t.TaskPath, $t.TaskName) -ForegroundColor Green
    } catch {
      Write-Host ("Could not retire {0}{1}: {2}" -f $t.TaskPath, $t.TaskName, $_.Exception.Message) -ForegroundColor Red
    }
  }
  if (-not $legacy) { Write-Host 'No legacy MCP tasks to retire.' }
}

Write-Host ''
Write-Host "Done. Verify with:  & '$(Join-Path $PSScriptRoot 'mcp.ps1')' status" -ForegroundColor Cyan
