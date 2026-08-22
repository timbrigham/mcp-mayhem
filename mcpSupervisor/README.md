# mcpSupervisor

A keep-alive watchdog for local MCP servers on Windows. One scheduled task polls every
server listed in a manifest, and repairs anything that has stopped responding.

It is a general-purpose supervisor that happens to live here: two of the servers it
manages are this repo's own subprojects (`structuredJsonValidator`, `gitRobot`), but it
is not limited to them. See "Adding your own servers" below.

## Setup

The manifest is machine-specific and deliberately untracked. Create yours from the sample:

    Copy-Item .\mcp-servers.sample.json .\mcp-servers.json

The sample ships working entries for `sjv` (port 8000) and `gitRobot` (port 8010) that run
as-is from a fresh clone. Edit it for your machine, then register the scheduled task:

    .\mcp.ps1 install

This needs elevation; the script self-elevates via UAC, so approve the prompt. It registers
a single `MCP-Supervisor` task that runs at logon as the logged-on user, so the servers it
launches inherit your user-scope environment variables.

## Commands

    .\mcp.ps1 status              # table: name, port, health, listener pid, uptime
    .\mcp.ps1 start   <name>      # also: stop, restart
    .\mcp.ps1 logs    <name>      # tail that server's stdout/stderr
    .\mcp.ps1 once                # one supervision pass, then exit
    .\mcp.ps1 install             # register/refresh the scheduled task (UAC)
    .\mcp.ps1 uninstall
    .\mcp.ps1 reconcile-tasks     # list legacy per-server tasks; -Force removes them

`<name>` is optional throughout - omit it to act on every server in the manifest.

## The ${McpRoot} token

Any `exe`, `args`, `workingDir`, or `env` value in the manifest may contain `${McpRoot}`,
which expands to the folder holding the manifest, with `..` segments collapsed. Use it so
the manifest stays portable instead of hardcoding an absolute location:

    "workingDir": "${McpRoot}\\..\\structuredJsonValidator"

Values without the token pass through untouched.

## Adding your own servers

Any local MCP server that listens on an HTTP port can be supervised. Add an entry with:

- `kind: "process"` if the server binds the port itself.
- `kind: "proxyWithChild"` if it is a stdio server fronted by a proxy such as `mcp_proxy`.
  The proxy keeps holding the port even when its backend has died, so
  `identity.requireChildProcess` names the child that must also be alive for the server to
  count as healthy.

Two constraints are load-bearing:

- **`identity.cmdlineMatch` must be unique across servers.** Process lookup matches on
  process name plus a command-line substring only - no working directory, no port - and a
  repair force-kills every machine-wide match. Two servers sharing a module path would be
  indistinguishable, and repairing one would kill the other.
- **Ports must match** the URL registered for that server in `~/.claude.json`.

Secrets are never stored in the manifest. List the variable *names* a server needs in
`requiredEnv`; the supervisor refuses to launch it until those user-scope variables are
set, rather than starting a broken process.

## Health checks

Layered, in order: is anything listening on the port; for `proxyWithChild`, is the required
child process alive; then an HTTP probe. Any HTTP status counts as alive, including 4xx -
MCP endpoints commonly return 406 to a bare GET, and only a connection-level failure means
the server is actually down.

## Logs

Per-server stdout/stderr plus `supervisor.log` are written to `logs/` (untracked). The
supervisor logs health *transitions* rather than every poll, plus a heartbeat every 20
ticks, so a quiet log is normal and not a sign of a hang.

There is **no log rotation**. `logs/` grows without bound; prune it periodically.

## Tests

None yet. This is the only subproject here without a test suite.