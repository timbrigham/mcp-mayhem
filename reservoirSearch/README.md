# reservoirSearch

Read-only MCP server over the Lean Reservoir package index, the data behind
reservoir.lean-lang.org: the official `leanprover/reservoir-index` from GitHub with no setup, or
a local directory in the same format. The index is loaded once (about 0.6 s for ~1,000 packages)
and every call is answered from memory (about 10 ms).

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

## Sources

Two sources share one loader, because both have the same layout.

| `RESERVOIR_SOURCE` | data | settings |
|---|---|---|
| `github` (default when `RESERVOIR_INDEX` is unset) | the official `leanprover/reservoir-index`, fetched as a tarball (the route Reservoir's own website workflow uses) into a cache | `RESERVOIR_REPO`, `RESERVOIR_CACHE` (default `%LOCALAPPDATA%\reservoirSearch` or `~/.cache/reservoirSearch`), `RESERVOIR_TTL_HOURS` (24), `GITHUB_TOKEN`/`GH_TOKEN` optional |
| `local` (default when `RESERVOIR_INDEX` is set) | a directory in the same format, e.g. a complete index built by a fork | `RESERVOIR_INDEX` |

With no configuration at all the server answers from the official index. The official index has
build results for its packages; a complete local index adds packages that have none.

**GitHub freshness.** When the TTL lapses, the next call asks for the branch head (one small
request) and downloads only if it moved. `reload()` does the same check immediately. The new tree is
extracted beside the old one and renamed into place, so a reader never sees a half-extracted tree.
If a refresh fails, the cached copy keeps serving and `status().source_detail.last_refresh_error`
says why. With no cache at all the call is refused as `unavailable`, never answered from an empty
index. Measured 2026-11-22: the first fetch and load of the official index took 34 s; a reload with
an unchanged head took 1.4 s.

**Local freshness.** The directory is expected to be **replaced in place**. Before each call the
server compares a fingerprint (the mtime of the root and of every owner directory, via `os.stat`);
any package added, removed or renamed triggers a reload. A file rewritten inside an existing
package directory is not detected; call `reload()` after such an edit.

## Schema and bad entries

Every file's `schemaVersion` is counted (`status().schema_versions`). Any MAJOR.MINOR other than
1.2 is reported in `schema_warnings`, on `status()` and on every answer's `index` block. It warns
rather than failing, and it is never silent. The official index on 2026-11-22: 2,859 files at
1.2.0 and 3 at 1.0.0 (`leanprover/leanbv`).

A package that fails to parse is listed in `status().skipped_entries` and left out; it never stops
the index loading. Measured in both the official and the local index: `katzenpost/crypt_walker`
has no `versions.json`.

## Tests

    cd reservoirSearch && python -m pytest -q
