# reservoirSearch

Read-only MCP server over a **local copy** of the Lean Reservoir package index, the data behind
reservoir.lean-lang.org, in the format of `leanprover/reservoir-index`. The index is loaded once
(about 0.6 s for ~1,000 packages) and every call is answered from memory (about 10 ms).

HTTP on `127.0.0.1:8014`, supervised by `mcpSupervisor` like the other servers here.

## Tools

| tool | answers |
|---|---|
| `search(query, toolchain?, license?, owner?, limit)` | packages whose name, description or keywords contain every word of `query`, ranked by stars |
| `get_package(name, versions_limit)` | metadata, latest version with dependencies, version list, recent builds; `owner/name`, case-insensitive, follows renames |
| `dependents(name, include_transitive, limit)` | packages whose **latest** version depends on it; direct only unless asked |
| `builds_on(toolchain, limit)` | packages whose latest version targets exactly that Lean toolchain (`v4.35.0`) |
| `toolchains()` | every toolchain in the index, with package counts |
| `status()` / `reload()` | which directory, when it loaded, and every entry that failed to parse |

Every answer carries `index` (`packages`, `aliases`, `loaded_at`). **The local copy may be partial,
so absence here is not absence from Reservoir.**

## Matching rules

- **Dependencies resolve by repository URL first**, then by `scope/name`. A dependency names its
  Lake package (`mathlib`) but the repository is what identifies it (`mathlib4`), and about a third
  of dependency entries carry no scope at all. URLs are normalised: case, scheme, a trailing `/` or
  `.git`, and the `git@host:owner/repo` form all collapse to `host/owner/repo`.
- **Toolchains match exactly.** `v4.36.0-rc2` is not `v4.36.0`. It is the toolchain a package
  declares, not proof that it built; builds are in `get_package`.
- **Only the latest version** (first entry of `versions.json`) is consulted for toolchain and
  dependencies.

## Data and freshness

`RESERVOIR_INDEX` names the directory (default `C:\Workspace\reservoir-index`). The directory is
expected to be **replaced in place** when a fuller index arrives. Before each call the server
compares a fingerprint (the mtime of the root and of every owner directory, via `os.stat`); any
package added, removed or renamed triggers a reload. A file rewritten inside an existing package
directory is not detected; call `reload()` after such an edit.

A package that fails to parse is listed in `status().skipped_entries` and left out; it never stops
the index loading.

## Tests

    cd reservoirSearch && python -m pytest -q
