<#
  Launch the verdictLedger MCP server (streamable HTTP).

  Config comes from env vars; override any of them before launch:
    ZPLEDGER_DATA     - the append-only record stream
    ZPLEDGER_POLICY   - policy.v1.json      (thresholds, actions, genesis)
    ZPLEDGER_REQUIRED - required.v2.json    (the type registry)
    ZPLEDGER_GITOPS   - gitRobot's git_ops.jsonl, for crossref
    ZPLEDGER_REPO     - the repo whose content is judged
    ZPLEDGER_HOST / ZPLEDGER_PORT - default 127.0.0.1 / 8011 (gitRobot holds 8010)
    ZPLEDGER_ACTOR    - actor recorded on writes

  NOTE the module path is `ledger_server.server` — NOT `mcp_server.server` (sjv)
  and NOT `gitrobot_server.server` (gitRobot). The supervisor matches processes on
  a command-line substring and a repair force-kills every machine-wide match, so a
  shared module path is actively collateral-killing rather than merely ambiguous.
#>
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = $root
if (-not $env:ZPLEDGER_DATA)     { $env:ZPLEDGER_DATA     = Join-Path $root 'data\records.jsonl' }
if (-not $env:ZPLEDGER_POLICY)   { $env:ZPLEDGER_POLICY   = Join-Path $root 'config\policy.v1.json' }
if (-not $env:ZPLEDGER_REQUIRED) { $env:ZPLEDGER_REQUIRED = Join-Path $root 'config\required.v2.json' }
if (-not $env:ZPLEDGER_HOST)     { $env:ZPLEDGER_HOST     = '127.0.0.1' }
if (-not $env:ZPLEDGER_PORT)     { $env:ZPLEDGER_PORT     = '8011' }
if (-not $env:ZPLEDGER_ACTOR)    { $env:ZPLEDGER_ACTOR    = 'mcp' }

$py = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }

Set-Location $root
& $py -m ledger_server.server
