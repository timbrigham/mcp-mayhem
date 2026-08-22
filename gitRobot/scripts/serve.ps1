<#
  Launch the gitRobot MCP server (streamable HTTP).

  Used both interactively and by the supervisor. Config comes from env vars
  (with sensible defaults); override any of them before launch:
    GITROBOT_REPO  - the ONE repository this server may act on
    GITROBOT_DATA  - append-only operation log
    GITROBOT_HOST  - bind address (default 127.0.0.1, local only)
    GITROBOT_PORT  - port (default 8010; must match ~/.claude.json)
    GITROBOT_ACTOR - actor recorded in the log (default "mcp")

  NOTE the module path is `gitrobot_server.server`, NOT `mcp_server.server`.
  The supervisor matches processes on a command-line substring, and the sibling
  structuredJsonValidator already occupies `mcp_server.server` — sharing it would
  make a gitRobot repair kill that server instead.
#>
$ErrorActionPreference = 'Stop'

# Repo dir = parent of this scripts/ folder.
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = $root
if (-not $env:GITROBOT_REPO)  { $env:GITROBOT_REPO  = 'C:\Workspace\ZeroParadox' }
if (-not $env:GITROBOT_DATA)  { $env:GITROBOT_DATA  = Join-Path $root 'data\git_ops.jsonl' }
if (-not $env:GITROBOT_HOST)  { $env:GITROBOT_HOST  = '127.0.0.1' }
if (-not $env:GITROBOT_PORT)  { $env:GITROBOT_PORT  = '8010' }
if (-not $env:GITROBOT_ACTOR) { $env:GITROBOT_ACTOR = 'mcp' }

# Prefer the real interpreter path (the WindowsApps alias can be flaky in a
# non-interactive/scheduled context); fall back to whatever `python` resolves to.
$py = 'C:\Users\timbr\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

Set-Location $root
& $py -m gitrobot_server.server
