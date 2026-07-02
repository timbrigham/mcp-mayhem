# sjv MCP server

A thin [FastMCP](https://github.com/modelcontextprotocol) transport over the
`structuredJsonValidator` (`sjv`) enforcement core. It exposes the registry's
read queries and operation-mediated writes as MCP tools over streamable HTTP.

**It enforces nothing itself.** Every tool call is delegated to the library
(`consumers.lean.build_registry(...).apply(...)`), which owns all schema,
business-rule (§7), and integrity checks. If the MCP server is down, the flat
file and its rules still hold. Enforcement failures surface as structured
`{ok: false, error_type, error}` results, never as transport-level crashes.

## Run

```bash
SJV_DATA=data/registry.json python -m mcp_server.server
# streamable-HTTP MCP at http://127.0.0.1:8000/mcp
```

A fresh registry is built per call, so the server always reflects the current
file on disk.

### Environment variables

| Var        | Default              | Purpose                                        |
| ---------- | -------------------- | ---------------------------------------------- |
| `SJV_DATA` | `data/registry.json` | Path to the JSON registry (the SSOT file).     |
| `SJV_HOST` | `127.0.0.1`          | Bind address. Keep loopback unless you mean it.|
| `SJV_PORT` | `8000`               | Listen port.                                   |
| `SJV_ACTOR`| `mcp`                | Actor name recorded in the audit log.          |

The audit sidecar is always `<SJV_DATA>.audit.jsonl` (e.g.
`data/registry.json.audit.jsonl`).

## Tools

**Read** (`{...}` result shapes vary):
- `get(id)` — one entry by id → `{found, entry}`
- `find(filters)` — dotted-path AND filters → `{count, entries}`
- `history(id?)` — append-only audit log, optionally per-entry
- `view(kind)` — render a projection (`status`, `domains`, …)
- `validate()` — full-file conformance → `{valid, violations}`
- `verify_integrity()` — file hash vs last audit hash → `{ok, hash|error}`

**Write** (each returns `{ok, ...}`; failures return `{ok: false, error_type, error}`):
- `seal()` — adopt the current file as the managed baseline (validate + record hash)
- §9 verbs — `rename`, `move`, `mark_present`, `drop`, `merge`, `split`,
  `reopen`, `add_new`, `annotate`, `link_claim`, `add_citation`
- terminal-state guard — `dropped`/`merged` entries are immutable: a
  disposition-changing verb on one is refused unless `force=true`; use
  `reopen(id, reason)` to return it to `pending` first
- `export_full(dest)` — publish the complete validated, deterministic registry
  to `dest` for a consuming repo to commit
- `apply(op, params)` — generic escape hatch for any registered operation

> **Security:** the server applies no authentication and no per-tool
> authorization. Any client that can reach the port can write. Bind to
> loopback and grant write access only to vetted clients (spec §11).

## Data privacy — real data is git-ignored by default

The server writes your live registry to `SJV_DATA` (default
`data/registry.json`) plus its audit sidecar `data/registry.json.audit.jsonl`.
**Everything the server writes under `data/` is treated as private and kept out
of git**, via `structuredJsonValidator/.gitignore`:

```gitignore
data/*
!data/sample.json
```

Only the demo fixture `data/sample.json` is tracked. Your real registry and its
audit log will **not** be committed.

If you deliberately want to publish a registry as a committed source-of-truth,
either:
- point `SJV_DATA` at a path **outside** `data/` that the consuming repo tracks
  on purpose, or
- use `export_full(dest)` to write a validated, deterministic dump into the
  consuming repo (the recommended publication path), or
- force-add a specific file: `git add -f data/<file>.json`.

## See also

The root [`../README.md`](../README.md) covers the enforcement core, the CLI,
design principles, and the publication (`export` / `export_full`) model.
