<#
  McpSupervisor.psm1 - shared logic for the unified local MCP-server supervisor.

  Consumed by Supervise-Mcp.ps1 (the watchdog loop) and mcp.ps1 (the CLI).
  Layered health check (port -> required child process -> HTTP), detached hidden
  launch with per-server logs, adopt-if-already-healthy.

  Windows PowerShell 5.1 compatible (no ternary / ?? / ?. operators).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:McpRoot     = $PSScriptRoot
$script:ManifestPath = Join-Path $PSScriptRoot 'mcp-servers.json'
$script:LogDir      = Join-Path $PSScriptRoot 'logs'
$script:SupervisorLog = Join-Path $script:LogDir 'supervisor.log'

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
function Write-McpLog {
  param(
    [Parameter(Mandatory)][string]$Message,
    [string]$Level = 'INFO'
  )
  if (-not (Test-Path $script:LogDir)) {
    New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
  }
  $line = '{0}  {1,-5}  {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
  Add-Content -Path $script:SupervisorLog -Value $line
  Write-Host $line
}

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
function Get-McpManifest {
  if (-not (Test-Path $script:ManifestPath)) {
    # The manifest is machine-specific and deliberately untracked, so a fresh
    # clone always lands here first. Name the fix rather than just the problem.
    $sample = Join-Path $script:McpRoot 'mcp-servers.sample.json'
    if (Test-Path $sample) {
      throw ("Manifest not found: {0}`n`n" -f $script:ManifestPath) +
            ("It is machine-specific and deliberately untracked. Create it with:`n" ) +
            ("  Copy-Item '{0}' '{1}'`n`n" -f $sample, $script:ManifestPath) +
            ("then edit it for this machine (exe paths, working dirs, ports, which servers to run).")
    }
    throw "Manifest not found: $script:ManifestPath"
  }
  return Get-Content -Raw -Path $script:ManifestPath | ConvertFrom-Json
}

# Expand the ${McpRoot} token (this folder) in a manifest string value and
# normalize the result. This is what lets a manifest point at sibling projects
# relatively, so the shipped sample works from a fresh clone no matter where the
# repo lives. Values without the token pass through untouched.
function Resolve-McpToken {
  param([string]$Value)
  if ([string]::IsNullOrEmpty($Value)) { return $Value }
  if ($Value -notlike '*${McpRoot}*') { return $Value }
  $expanded = $Value.Replace('${McpRoot}', $script:McpRoot)
  # Collapse '..' segments so Start-Process and PYTHONPATH get a clean path.
  try { return [System.IO.Path]::GetFullPath($expanded) } catch { return $expanded }
}

function Get-McpServer {
  param([Parameter(Mandatory)][string]$Name)
  $m = Get-McpManifest
  $s = $m.servers | Where-Object { $_.name -eq $Name }
  if (-not $s) { throw "No server named '$Name' in manifest." }
  return $s
}

# ---------------------------------------------------------------------------
# Process discovery
# ---------------------------------------------------------------------------

# The PID that owns the listening socket on $Port (or $null).
function Get-McpListenerPid {
  param([Parameter(Mandatory)][int]$Port)
  $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
          Select-Object -First 1
  if ($conn) { return [int]$conn.OwningProcess }
  return $null
}

# Live node.exe (or other) children of a given parent PID.
function Get-McpChildProcess {
  param(
    [Parameter(Mandatory)][int]$ParentPid,
    [Parameter(Mandatory)][string]$ChildName
  )
  return Get-CimInstance Win32_Process `
    -Filter "Name='$ChildName' AND ParentProcessId=$ParentPid" -ErrorAction SilentlyContinue
}

# Processes matching a server's identity by command-line (fallback to port owner).
function Get-McpServerProcess {
  param([Parameter(Mandatory)]$Server)
  $id = $Server.identity
  $procs = Get-CimInstance Win32_Process -Filter "Name LIKE '$($id.processName -replace '\*','%')'" `
             -ErrorAction SilentlyContinue |
           Where-Object { $_.CommandLine -and $_.CommandLine -like "*$($id.cmdlineMatch)*" }
  return $procs
}

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

# Probe the HTTP endpoint. Any HTTP status (incl. 4xx/406) => responding=$true.
# Only a connection-level failure / timeout => $false.
function Test-McpHttp {
  param([Parameter(Mandatory)]$Server)
  $url = "http://$($Server.host):$($Server.port)$($Server.healthPath)"
  try {
    Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop | Out-Null
    return $true
  } catch {
    # A returned HTTP status (4xx/5xx) still proves the app is alive and responding.
    if ($_.Exception.Response) { return $true }
    return $false
  }
}

# Returns a status object: Health = Healthy | ChildDead | Down, plus diagnostics.
function Get-McpHealth {
  param([Parameter(Mandatory)]$Server)

  $listenerPid = Get-McpListenerPid -Port $Server.port
  $result = [PSCustomObject]@{
    Name       = $Server.name
    Port       = $Server.port
    Listening  = [bool]$listenerPid
    Pid        = $listenerPid
    ChildOk    = $true
    HttpOk     = $false
    Health     = 'Down'
  }

  if (-not $listenerPid) { return $result }

  # proxyWithChild: the wrapper can hold the port while its stdio backend is dead.
  if ($Server.kind -eq 'proxyWithChild') {
    $childName = $Server.identity.requireChildProcess
    $child = Get-McpChildProcess -ParentPid $listenerPid -ChildName $childName
    if (-not $child) {
      $result.ChildOk = $false
      $result.Health  = 'ChildDead'
      return $result
    }
  }

  $result.HttpOk = Test-McpHttp -Server $Server
  if ($result.HttpOk) { $result.Health = 'Healthy' } else { $result.Health = 'Down' }
  return $result
}

# ---------------------------------------------------------------------------
# Stop / Start
# ---------------------------------------------------------------------------

function Stop-McpServer {
  param([Parameter(Mandatory)]$Server)

  $listenerPid = Get-McpListenerPid -Port $Server.port

  # For proxyWithChild, kill the backend children first so the wrapper can't
  # linger holding the port.
  if ($Server.kind -eq 'proxyWithChild' -and $listenerPid) {
    Get-McpChildProcess -ParentPid $listenerPid -ChildName $Server.identity.requireChildProcess |
      ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      }
  }

  # Kill the listener itself, plus any identity-matching stragglers not bound to
  # the port (stale launches that never finished binding).
  $targets = @()
  if ($listenerPid) { $targets += $listenerPid }
  $targets += (Get-McpServerProcess -Server $Server | ForEach-Object { $_.ProcessId })
  $targets | Sort-Object -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
  }
}

# Ensure the env vars this server needs are present in the supervisor's own
# environment (which, run as the logged-on user, inherits user-scope creds).
function Test-McpRequiredEnv {
  param([Parameter(Mandatory)]$Server)
  $missing = @()
  foreach ($name in @($Server.requiredEnv)) {
    if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name))) {
      $missing += $name
    }
  }
  return $missing
}

function Resolve-McpExe {
  param([Parameter(Mandatory)]$Server)
  $exe = Resolve-McpToken ([string]$Server.start.exe)
  if (Test-Path $exe) { return $exe }
  # A bare command name (python/node) is resolved via PATH by Start-Process.
  if ($exe -notmatch '[\\/]') { return $exe }
  if ($Server.start.PSObject.Properties.Name -contains 'exeFallback') {
    return (Resolve-McpToken ([string]$Server.start.exeFallback))
  }
  throw "Executable not found for '$($Server.name)': $exe"
}

function Start-McpServer {
  param([Parameter(Mandatory)]$Server)

  $missing = @(Test-McpRequiredEnv -Server $Server)
  if ($missing.Count -gt 0) {
    Write-McpLog -Level 'ERROR' -Message "$($Server.name): missing required env [$($missing -join ', ')] - refusing to start (run as the logged-on user with user-scope vars set)."
    return $false
  }

  if (-not (Test-Path $script:LogDir)) {
    New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
  }
  $out = Join-Path $script:LogDir "$($Server.name).out.log"
  $err = Join-Path $script:LogDir "$($Server.name).err.log"
  $exe = Resolve-McpExe -Server $Server

  # Apply per-server env just for this launch, then restore, so server-specific
  # vars (TRANSPORT, SJV_PORT, ...) never leak between servers in the long-lived
  # supervisor process.
  $saved = @{}
  $envObj = $Server.start.env
  if ($envObj) {
    foreach ($p in $envObj.PSObject.Properties) {
      $saved[$p.Name] = [Environment]::GetEnvironmentVariable($p.Name)  # may be $null
      Set-Item -Path "Env:$($p.Name)" -Value (Resolve-McpToken ([string]$p.Value))
    }
  }

  try {
    $args = @($Server.start.args | ForEach-Object { Resolve-McpToken ([string]$_) })
    $startArgs = @{
      FilePath               = $exe
      WorkingDirectory       = (Resolve-McpToken ([string]$Server.start.workingDir))
      WindowStyle            = 'Hidden'
      RedirectStandardOutput = $out
      RedirectStandardError  = $err
      PassThru               = $true
    }
    if ($args.Count -gt 0) { $startArgs['ArgumentList'] = $args }
    $proc = Start-Process @startArgs
    Write-McpLog "$($Server.name): launched pid $($proc.Id) ($exe $($args -join ' '))"
  } finally {
    foreach ($k in $saved.Keys) {
      if ($null -eq $saved[$k]) {
        Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue
      } else {
        Set-Item -Path "Env:$k" -Value $saved[$k]
      }
    }
  }
  return $true
}

# ---------------------------------------------------------------------------
# Repair - the unit of work the loop and the CLI both call.
# Adopts an already-healthy server; otherwise stop -> start -> re-probe.
# Returns the post-action health object.
# ---------------------------------------------------------------------------
function Repair-McpServer {
  param(
    [Parameter(Mandatory)]$Server,
    [int]$SettleSeconds = 6
  )
  $h = Get-McpHealth -Server $Server
  if ($h.Health -eq 'Healthy') { return $h }

  Write-McpLog -Level 'WARN' -Message "$($Server.name): $($h.Health) - restarting."
  Stop-McpServer -Server $Server
  Start-Sleep -Seconds 2
  $started = Start-McpServer -Server $Server
  if (-not $started) { return (Get-McpHealth -Server $Server) }

  Start-Sleep -Seconds $SettleSeconds
  $h2 = Get-McpHealth -Server $Server
  if ($h2.Health -eq 'Healthy') {
    Write-McpLog "$($Server.name): recovered (pid $($h2.Pid))."
  } else {
    Write-McpLog -Level 'ERROR' -Message "$($Server.name): still $($h2.Health) after restart."
  }
  return $h2
}

Export-ModuleMember -Function `
  Write-McpLog, Get-McpManifest, Resolve-McpToken, Get-McpServer, Get-McpListenerPid, Get-McpChildProcess, `
  Get-McpServerProcess, Test-McpHttp, Get-McpHealth, Stop-McpServer, Test-McpRequiredEnv, `
  Resolve-McpExe, Start-McpServer, Repair-McpServer
