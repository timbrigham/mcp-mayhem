<#
  Launch the structuredJsonValidator MCP server (streamable HTTP).

  Used both interactively and by the `sjv-mcp` scheduled task. Config comes from
  env vars (with sensible defaults); override any of them before launch:
    SJV_DATA  - path to the flat JSON source of truth
    SJV_HOST  - bind address (default 127.0.0.1, local only)
    SJV_PORT  - port (default 8000)
    SJV_ACTOR - actor recorded in the audit log (default "mcp")
#>
$ErrorActionPreference = 'Stop'

# Repo dir = parent of this scripts/ folder.
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = $root
if (-not $env:SJV_DATA)  { $env:SJV_DATA  = Join-Path $root 'data\registry.json' }
if (-not $env:SJV_HOST)  { $env:SJV_HOST  = '127.0.0.1' }
if (-not $env:SJV_PORT)  { $env:SJV_PORT  = '8000' }
if (-not $env:SJV_ACTOR) { $env:SJV_ACTOR = 'mcp' }

# Prefer the real interpreter path (the WindowsApps alias can be flaky in a
# non-interactive/scheduled context); fall back to whatever `python` resolves to.
$py = 'C:\Users\timbr\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

Set-Location $root
& $py -m mcp_server.server
