# gitRobot MCP server

Streamable-HTTP FastMCP transport for `core`.

```
GITROBOT_REPO=C:\Workspace\ZeroParadox python -m gitrobot_server.server
# or: scripts\serve.ps1
```

**It enforces nothing itself.** Every tool call is delegated to `core`, which owns
tier classification, gate running, git invocation and the audit log. If this
server is down, the rules still exist and `python -m core.cli` still applies them.

⚠ **The module path `gitrobot_server` is load-bearing — never rename it to
`mcp_server`.** The process supervisor identifies a running server by process name
plus a command-line substring, with no working-directory or port filter. The
sibling `structuredJsonValidator` already runs `python -m mcp_server.server`; a
second server on that module path would be indistinguishable from it, and a
gitRobot repair would have targeted and killed the registry instead. Caught during
registration, before it ran.

## Tools

| tool | tier | does |
|---|---|---|
| `read(op, args?, repo_mode?)` | 3 | allow-listed read-only git; anything unrecognised is refused |
| `status()` | 3 | tree + branch + unpushed count + what would block a push |
| `stage(paths[], repo_mode?)` | 2 | named paths only (`-A` refused on the main repo) |
| `commit(message_file, reason?, repo_mode?)` | 2 | `pre-commit` pipeline, then commit; message from a file |
| `preflight(reason?)` | 2 | the full `pre-push` pipeline **without** pushing |
| `push(branch, reason)` | 2 | refuses without a passing preflight for the current HEAD |
| `worktree(action, ref?, name?)` | 2 | the sanctioned isolation path |
| `explain(refusal_id)` | — | why it was refused and exactly what discharges it |
| `history(limit?)` | — | the append-only op log |

Every failure returns `{ok: false, error_type, error}` and never a transport
crash. A refusal additionally carries `alternative` and `refusal_id`.

**Absent by design**, and asserted absent by a test over this module: no `force`,
no `no_verify`, no `skip_gates`, no `allow_dirty`, no `repo`, no raw
`passthrough(cmd)`.

## Registration

Supervisor (`C:\Workspace\env\mcp-servers.json`) and the ZeroParadox project block
of `~/.claude.json` must agree on the port. Both are already set to **8010**, with
`cmdlineMatch: gitrobot_server.server`.

This server is **half** a mechanism. Without the PreToolUse deny on direct `git`
in the ZeroParadox project settings, it closes nothing — an agent would simply
keep using `git` and never call these tools.
