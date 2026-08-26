<#
  mcp.ps1 - management CLI for the unified local MCP-server supervisor.

  Usage:
    .\mcp.ps1 status                 # table: name, port, listening, http, pid, uptime
    .\mcp.ps1 start   [name]         # ensure server(s) running (adopts if already healthy)
    .\mcp.ps1 stop    [name]         # stop server(s)
    .\mcp.ps1 restart [name]         # stop then start server(s)
    .\mcp.ps1 logs    [name] [-Tail 40]   # tail a server log (or supervisor.log if no name)
    .\mcp.ps1 once                   # single repair pass over all servers (no loop)
    .\mcp.ps1 install                # register+start the MCP-Supervisor scheduled task
    .\mcp.ps1 uninstall              # remove the MCP-Supervisor scheduled task
    .\mcp.ps1 reconcile-tasks [-Force]    # list (and with -Force remove) legacy per-server tasks

  [name] is optional; omit it to act on all servers in the manifest.
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('status','start','stop','restart','logs','once','install','uninstall','reconcile-tasks')]
  [string]$Command = 'status',

  [Parameter(Position = 1)]
  [string]$Name,

  [int]$Tail = 40,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'McpSupervisor.psm1') -Force

function Get-TargetServers {
  $manifest = Get-McpManifest
  if ($Name) {
    $s = $manifest.servers | Where-Object { $_.name -eq $Name }
    if (-not $s) { throw "No server named '$Name'. Known: $(( $manifest.servers.name ) -join ', ')" }
    return @($s)
  }
  return @($manifest.servers)
}

function Format-Uptime {
  param([int]$ServerPid)
  if (-not $ServerPid) { return '' }
  $p = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
  if (-not $p) { return '' }
  $span = (Get-Date) - $p.StartTime
  if ($span.TotalDays -ge 1) { return ('{0:0}d{1:0}h' -f $span.Days, $span.Hours) }
  if ($span.TotalHours -ge 1) { return ('{0:0}h{1:0}m' -f $span.Hours, $span.Minutes) }
  return ('{0:0}m' -f $span.TotalMinutes)
}

switch ($Command) {

  'status' {
    $rows = foreach ($s in Get-TargetServers) {
      $h = Get-McpHealth -Server $s
      [PSCustomObject]@{
        Name    = $h.Name
        Port    = $h.Port
        Health  = $h.Health
        Listen  = if ($h.Listening) { 'yes' } else { 'no' }
        Http    = if ($h.HttpOk) { 'ok' } else { '-' }
        Pid     = if ($h.Pid) { $h.Pid } else { '' }
        Uptime  = Format-Uptime -ServerPid ([int]$h.Pid)
      }
    }
    $rows | Format-Table -AutoSize

    # ⚠⚠ REPORT THE AGE OF THE LAST BACKUP THAT ACTUALLY REACHED THE REMOTE, on every
    # status call, loudly when it is stale or has never worked.
    #
    # A backup that has been quietly failing for a week is indistinguishable from one
    # that is working, right up until the moment you need it -- which is the exact
    # defect class the servers this supervisor watches exist to eliminate. Silence is
    # never success. `Get-McpBackupAge` keys on the last PUSH, not the last attempt and
    # not the last commit: "it ran" and "it worked" are different facts, and only the
    # second one is a backup.
    if (-not $Name) {
      $m = Get-McpManifest
      $repo = if ($m.PSObject.Properties.Name -contains 'backupRepo') { Resolve-McpToken $m.backupRepo } else { Join-Path $PSScriptRoot '..\.mcp-local' }
      $every = if ($m.PSObject.Properties.Name -contains 'backupMinutes') { [int]$m.backupMinutes } else { 30 }
      $age = Get-McpBackupAge -RepoPath $repo
      if (-not $age.Ever) {
        Write-Host ("BACKUP: NEVER REACHED THE REMOTE - {0}" -f $age.Note) -ForegroundColor Red
      } elseif ($age.Minutes -gt (3 * $every)) {
        Write-Host ("BACKUP: STALE - last offsite {0} min ago, expected every {1} min" -f $age.Minutes, $every) -ForegroundColor Red
      } else {
        Write-Host ("backup: offsite {0} min ago (every {1} min)" -f $age.Minutes, $every)
      }
    }
    break
  }

  'start' {
    foreach ($s in Get-TargetServers) {
      $h = Repair-McpServer -Server $s
      Write-Host ("{0}: {1}" -f $s.name, $h.Health)
    }
    break
  }

  'stop' {
    foreach ($s in Get-TargetServers) {
      Stop-McpServer -Server $s
      Write-Host ("{0}: stopped" -f $s.name)
    }
    break
  }

  'restart' {
    foreach ($s in Get-TargetServers) {
      Stop-McpServer -Server $s
      Start-Sleep -Seconds 2
      Start-McpServer -Server $s | Out-Null
      Start-Sleep -Seconds 6
      $h = Get-McpHealth -Server $s
      Write-Host ("{0}: {1}" -f $s.name, $h.Health)
    }
    break
  }

  'logs' {
    $logDir = Join-Path $PSScriptRoot 'logs'
    if ($Name) {
      $out = Join-Path $logDir "$Name.out.log"
      $err = Join-Path $logDir "$Name.err.log"
      foreach ($f in @($out, $err)) {
        if (Test-Path $f) {
          Write-Host "==== $f (last $Tail) ====" -ForegroundColor Cyan
          Get-Content -Path $f -Tail $Tail
        }
      }
    } else {
      $sup = Join-Path $logDir 'supervisor.log'
      if (Test-Path $sup) {
        Write-Host "==== $sup (last $Tail) ====" -ForegroundColor Cyan
        Get-Content -Path $sup -Tail $Tail
      } else { Write-Host "no supervisor.log yet at $sup" }
    }
    break
  }

  'once' {
    & (Join-Path $PSScriptRoot 'Supervise-Mcp.ps1') -Once
    break
  }

  'install' {
    & (Join-Path $PSScriptRoot 'Install-McpTask.ps1')
    break
  }

  'uninstall' {
    $t = Get-ScheduledTask -TaskName 'MCP-Supervisor' -ErrorAction SilentlyContinue
    if ($t) {
      Stop-ScheduledTask -TaskName 'MCP-Supervisor' -ErrorAction SilentlyContinue
      Unregister-ScheduledTask -TaskName 'MCP-Supervisor' -Confirm:$false
      Write-Host 'MCP-Supervisor task removed.'
    } else { Write-Host 'MCP-Supervisor task not present.' }
    break
  }

  'reconcile-tasks' {
    # Legacy per-server keep-alive tasks that would fight the unified supervisor.
    $legacyNames = @('Email Handler','ZP-MailProxyWatchdog','sjv-mcp')
    $found = Get-ScheduledTask | Where-Object { $legacyNames -contains $_.TaskName }
    if (-not $found) { Write-Host 'No legacy MCP tasks found.'; break }
    Write-Host 'Legacy MCP-related scheduled tasks:' -ForegroundColor Yellow
    $found | Select-Object TaskName, TaskPath, State | Format-Table -AutoSize
    if ($Force) {
      foreach ($t in $found) {
        try {
          Stop-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue
          Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false
          Write-Host ("removed: {0}{1}" -f $t.TaskPath, $t.TaskName) -ForegroundColor Green
        } catch {
          Write-Host ("FAILED to remove {0}{1}: {2}" -f $t.TaskPath, $t.TaskName, $_.Exception.Message) -ForegroundColor Red
          Write-Host "  (removing scheduled tasks needs elevation - run:  .\mcp.ps1 install  and approve UAC)" -ForegroundColor Yellow
        }
      }
    } else {
      Write-Host 'Re-run with -Force to disable/remove these.' -ForegroundColor Yellow
    }
    break
  }
}
