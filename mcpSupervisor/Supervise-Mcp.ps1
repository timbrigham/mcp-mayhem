<#
  Supervise-Mcp.ps1 - the watchdog loop.

  Run continuously by the MCP-Supervisor scheduled task (at logon, as the
  logged-on user). Every pollSeconds it repairs each server in the manifest:
  adopts the healthy, restarts the dead. One bad server never kills the loop.

  Manual use:  powershell -NoProfile -ExecutionPolicy Bypass -File Supervise-Mcp.ps1
  Stop with Ctrl+C (interactive) or by stopping the scheduled task.
#>
param(
  [switch]$Once   # run a single repair pass over all servers, then exit (for testing)
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'McpSupervisor.psm1') -Force

$LockFile = Join-Path $PSScriptRoot 'logs\supervisor.lock'

function Test-AnotherInstance {
  if (-not (Test-Path $LockFile)) { return $false }
  try {
    $otherPid = [int](Get-Content -Raw -Path $LockFile).Trim()
  } catch { return $false }
  if ($otherPid -eq $PID) { return $false }
  $p = Get-Process -Id $otherPid -ErrorAction SilentlyContinue
  if ($p -and $p.ProcessName -match 'powershell|pwsh') { return $true }
  return $false
}

function Repair-AllOnce {
  $manifest = Get-McpManifest
  foreach ($server in $manifest.servers) {
    try {
      Repair-McpServer -Server $server | Out-Null
    } catch {
      Write-McpLog -Level 'ERROR' -Message "$($server.name): repair threw - $($_.Exception.Message)"
    }
  }
}

# ---- one-shot mode -------------------------------------------------------
if ($Once) {
  Write-McpLog 'single repair pass (-Once)'
  Repair-AllOnce
  return
}

# ---- persistent loop -----------------------------------------------------
if (Test-AnotherInstance) {
  Write-McpLog -Level 'WARN' -Message "another supervisor instance is already running (pid in lock) - exiting."
  return
}
if (-not (Test-Path (Split-Path $LockFile))) {
  New-Item -ItemType Directory -Path (Split-Path $LockFile) -Force | Out-Null
}
Set-Content -Path $LockFile -Value $PID

$manifest = Get-McpManifest
$poll = if ($manifest.PSObject.Properties.Name -contains 'pollSeconds') { [int]$manifest.pollSeconds } else { 30 }
$fails = @{}          # server name -> consecutive failed repairs
$lastState = @{}      # server name -> last Health, for change-only logging
$heartbeatEvery = 20  # ticks between "all healthy" heartbeat lines
$tick = 0

Write-McpLog "supervisor starting (pid $PID, poll ${poll}s, $($manifest.servers.Count) servers)"

try {
  while ($true) {
    $tick++
    $allHealthy = $true
    foreach ($server in $manifest.servers) {
      $name = $server.name
      try {
        $h = Repair-McpServer -Server $server
        if (-not $lastState.ContainsKey($name)) { $lastState[$name] = '' }
        if ($h.Health -ne $lastState[$name]) {
          Write-McpLog "$name -> $($h.Health)"
          $lastState[$name] = $h.Health
        }
        if ($h.Health -eq 'Healthy') {
          $fails[$name] = 0
        } else {
          $allHealthy = $false
          if (-not $fails.ContainsKey($name)) { $fails[$name] = 0 }
          $fails[$name]++
          if ($fails[$name] -ge 3) {
            $backoff = [Math]::Min(300, 30 * $fails[$name])
            Write-McpLog -Level 'WARN' -Message "${name}: $($fails[$name]) consecutive failed repairs - backing off ${backoff}s."
            Start-Sleep -Seconds $backoff
          }
        }
      } catch {
        $allHealthy = $false
        Write-McpLog -Level 'ERROR' -Message "${name}: loop error - $($_.Exception.Message)"
      }
    }
    if ($allHealthy -and ($tick % $heartbeatEvery -eq 0)) {
      Write-McpLog "heartbeat: all $($manifest.servers.Count) servers healthy"
    }
    Start-Sleep -Seconds $poll
  }
} finally {
  if (Test-Path $LockFile) {
    $owner = (Get-Content -Raw -Path $LockFile -ErrorAction SilentlyContinue).Trim()
    if ($owner -eq "$PID") { Remove-Item -Path $LockFile -ErrorAction SilentlyContinue }
  }
  Write-McpLog "supervisor exiting (pid $PID)"
}
