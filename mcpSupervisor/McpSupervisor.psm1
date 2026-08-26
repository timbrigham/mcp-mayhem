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

function Test-McpStreamIntact {
  <#
    .SYNOPSIS
      Does every .jsonl in the backup repo end in a COMPLETE record?

    ⚠⚠ THE SUPERVISOR CANNOT TAKE THE LEDGER'S WRITE LOCK, so it may look at
    records.jsonl in the middle of an append. A record can exceed 46 KB (452 subjects)
    and a write that large is not atomic on Windows, so a commit taken at the wrong
    instant would capture a TORN LINE.

    That is worse than skipping a round: the backup would look successful, and the
    corruption would only surface on the restore, which is the one moment nobody can
    afford a surprise. Appends only ever land at the end, so the last line is the only
    place a tear can be — check it, and if it does not parse, do nothing and try again
    in 30 minutes. The stream is append-only, so a skipped round loses nothing.
  #>
  param([Parameter(Mandatory)][string]$RepoPath)
  foreach ($f in Get-ChildItem -Path $RepoPath -Filter '*.jsonl' -Recurse -File) {
    $last = Get-Content -Path $f.FullName -Tail 1 -ErrorAction SilentlyContinue
    if ([string]::IsNullOrWhiteSpace($last)) { continue }
    try { $null = $last | ConvertFrom-Json -ErrorAction Stop }
    catch { return [pscustomobject]@{ Ok = $false; File = $f.Name } }
  }
  return [pscustomobject]@{ Ok = $true; File = $null }
}

function Invoke-McpBackup {
  <#
    .SYNOPSIS
      Commit and push the run-data repo. NEVER throws.

    ⚠⚠ IT MUST NOT BE ABLE TO KILL THE SUPERVISOR. The supervisor's job is keeping
    servers up; a backup is strictly secondary. A network blip, an expired credential
    or a locked file must log and move on, never break the poll loop that is the
    reason this process exists.

    ⚠⚠ AND A FAILING BACKUP MUST BE LOUD. Every outcome is written to
    `last-backup.json`, including failures, so `mcp.ps1 status` can report the AGE of
    the last SUCCESS rather than the age of the last attempt. A backup that has been
    quietly failing for a week is indistinguishable from one that is working right up
    until you need it — which is the exact defect class the servers this supervisor
    watches exist to eliminate. Silence is never success.

    ⚠ A local commit still counts as progress even when the push fails: history is
    kept, it is simply not offsite yet. The two are reported separately for that
    reason -- conflating them would hide an auth failure behind a green commit.
  #>
  param(
    [Parameter(Mandatory)][string]$RepoPath,
    [string]$Reason = 'scheduled'
  )
  $marker = Join-Path $RepoPath 'last-backup.json'
  $result = [ordered]@{
    at = (Get-Date).ToString('o'); reason = $Reason
    committed = $false; pushed = $false; skipped = $null; error = $null
  }
  try {
    if (-not (Test-Path (Join-Path $RepoPath '.git'))) {
      $result.skipped = "no git repository at $RepoPath"
      Write-McpLog -Level 'WARN' -Message "backup: $($result.skipped)"
      return $result
    }

    $intact = Test-McpStreamIntact -RepoPath $RepoPath
    if (-not $intact.Ok) {
      # Not an error. A torn tail means a write was in flight; the next round gets it.
      $result.skipped = "$($intact.File) ends mid-record (a write was in flight) - skipping, the stream is append-only so nothing is lost"
      Write-McpLog -Message "backup: $($result.skipped)"
      return $result
    }

    $null = git -C $RepoPath add -A
    $null = git -C $RepoPath diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
      $result.skipped = 'nothing changed'
      return $result          # ⚠ no empty commits; they make `git log` unreadable
    }

    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm')
    $msg = "run data $stamp ($Reason)"
    $null = git -C $RepoPath -c user.name='mcpSupervisor' -c user.email='mcp@localhost' commit -q -m $msg
    if ($LASTEXITCODE -ne 0) {
      $result.error = 'commit failed'
      Write-McpLog -Level 'ERROR' -Message 'backup: commit failed'
      return $result
    }
    $result.committed = $true

    $null = git -C $RepoPath push -q origin HEAD
    if ($LASTEXITCODE -eq 0) {
      $result.pushed = $true
      Write-McpLog -Message "backup: committed and pushed ($Reason)"
    } else {
      # ⚠ Committed but NOT offsite. Reported distinctly, and WARN so it surfaces.
      $result.error = 'push failed - committed locally, NOT offsite'
      Write-McpLog -Level 'WARN' -Message "backup: $($result.error)"
    }
  } catch {
    $result.error = $_.Exception.Message
    Write-McpLog -Level 'ERROR' -Message "backup: $($result.error)"
  } finally {
    try { ($result | ConvertTo-Json -Compress) | Set-Content -Path $marker -Encoding utf8 } catch { }
  }
  return $result
}

function Get-McpBackupAge {
  <#
    .SYNOPSIS
      How long since the last backup that actually reached the remote.

    ⚠ Deliberately keyed on the last PUSH, not the last attempt and not the last
    commit. "It ran" and "it worked" are different facts, and only the second one is
    a backup.
  #>
  param([Parameter(Mandatory)][string]$RepoPath)
  $marker = Join-Path $RepoPath 'last-backup.json'
  if (-not (Test-Path $marker)) {
    return [pscustomobject]@{ Ever = $false; Minutes = $null; Note = 'no backup has ever run' }
  }
  try {
    $m = Get-Content -Raw -Path $marker | ConvertFrom-Json
    if (-not $m.pushed) {
      return [pscustomobject]@{ Ever = $false; Minutes = $null
                                Note = "last attempt $($m.at) did not reach the remote: $($m.error)" }
    }
    $mins = [int]((Get-Date) - [datetime]$m.at).TotalMinutes
    return [pscustomobject]@{ Ever = $true; Minutes = $mins; Note = $null }
  } catch {
    return [pscustomobject]@{ Ever = $false; Minutes = $null; Note = 'last-backup.json unreadable' }
  }
}


Export-ModuleMember -Function `
  Write-McpLog, Get-McpManifest, Resolve-McpToken, Get-McpServer, Get-McpListenerPid, Get-McpChildProcess, `
  Get-McpServerProcess, Test-McpHttp, Get-McpHealth, Stop-McpServer, Test-McpRequiredEnv, `
  Resolve-McpExe, Start-McpServer, Repair-McpServer, `
  Test-McpStreamIntact, Invoke-McpBackup, Get-McpBackupAge
