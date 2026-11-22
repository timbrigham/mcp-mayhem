"""FastMCP server: read-only search over a local copy of the Lean Reservoir package index.

Run:
    python -m reservoir_server.server
    # optional: RESERVOIR_INDEX (default C:\\Workspace\\reservoir-index),
    #           RESERVOIR_HOST (default 127.0.0.1), RESERVOIR_PORT (default 8014)

Built 2026-11-22 at Tim's request, from a spec handed over by the reservoir session. The index is
loaded once and filtered in memory; the directory is replaced in place when a fuller index lands,
and a changed directory is picked up on the next call (see `reservoir_core.index.fingerprint`).

⚠ THE MODULE PATH ``reservoir_server`` IS LOAD-BEARING. The supervisor identifies a server by
process name plus a command-line substring and force-kills every match, so it must not share a
module path with sjv (``mcp_server``), gitRobot, verdictLedger, publishRobot or publishApprove.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Optional

import anyio.to_thread
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcpcommon.calllog import serve as _serve_with_call_log  # noqa: E402
from mcpcommon.iserror import install as _install_is_error, install_resource_classification  # noqa: E402

from reservoir_core.index import ReservoirError, Store  # noqa: E402
from reservoir_server.results import (  # noqa: E402
    BuildsOnResult, DependentsResult, PackageResult, SearchResult, StatusResult, ToolchainsResult)

HERE = Path(__file__).resolve().parents[1]
STORE = Store()

mcp = FastMCP(
    "reservoirSearch",
    instructions="""Read-only search over a LOCAL copy of the Lean Reservoir package index
(reservoir.lean-lang.org's data). Loaded once, answered from memory.

START HERE: search(query) - words must all match name, description or keywords; ranked by
stars. get_package('owner/name') for one package (case-insensitive, follows renames).
dependents('owner/name') for who uses it. builds_on('v4.35.0') for every package whose latest
version targets that exact Lean toolchain; toolchains() lists the versions present.

⚠ THE LOCAL INDEX MAY BE PARTIAL. Every answer carries `index` (packages, loaded_at): absence
here is not absence from Reservoir. status() names the directory and any entries skipped.
All matching is on each package's LATEST version.""",
    host=os.environ.get("RESERVOIR_HOST", "127.0.0.1"),
    port=int(os.environ.get("RESERVOIR_PORT", "8014")),
)

_install_is_error(mcp)
install_resource_classification(mcp)

_READ = dict(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


async def _guard(tool: str, *args, **kwargs) -> dict:
    """Off the event loop (a first load reads ~3,000 files), and a deliberate refusal returned
    with its success condition."""
    try:
        fn = getattr(STORE, tool)
        return {"ok": True, **await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))}
    except ReservoirError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc),
                "satisfied_when": exc.satisfied_when}


@mcp.tool(title='Search packages', annotations=ToolAnnotations(title='Search packages', **_READ))
async def search(query: str = "", toolchain: Optional[str] = None, license: Optional[str] = None,
                 owner: Optional[str] = None, limit: int = 20) -> SearchResult:
    """Packages whose name, description or keywords contain EVERY word of `query`
    (case-insensitive substring), ranked by stars. Optional exact filters: `toolchain` of the
    latest version ('v4.35.0'), SPDX `license`, `owner`. A filter alone with no query is fine.
    `truncated` counts results beyond `limit`."""
    return await _guard("search", query, toolchain=toolchain, license=license, owner=owner,
                        limit=limit)


@mcp.tool(title='Get one package', annotations=ToolAnnotations(title='Get one package', **_READ))
async def get_package(name: str, versions_limit: int = 20) -> PackageResult:
    """Full metadata, the latest version (with dependencies), the version list (newest first,
    capped by `versions_limit`) and recent builds. `name` is owner/name, case-insensitive;
    renamed packages resolve through their alias (`resolved_alias`). The readme text is not in
    the index, only its filename (`latest.readmeFile`)."""
    return await _guard("get_package", name, versions_limit=versions_limit)


@mcp.tool(title='Packages that depend on one',
          annotations=ToolAnnotations(title='Packages that depend on one', **_READ))
async def dependents(name: str, include_transitive: bool = False,
                     limit: int = 100) -> DependentsResult:
    """Packages whose LATEST version lists `name` as a dependency, ranked by stars. Direct only
    by default; `include_transitive` adds packages that reach it indirectly. Matched by repo url
    first, then scope/name (`matched_by`). Counts of both kinds are always returned."""
    return await _guard("dependents", name, include_transitive=include_transitive, limit=limit)


@mcp.tool(title='Packages on a toolchain',
          annotations=ToolAnnotations(title='Packages on a toolchain', **_READ))
async def builds_on(toolchain: str, limit: int = 100) -> BuildsOnResult:
    """Packages whose LATEST version targets exactly this Lean toolchain: 'v4.35.0',
    '4.35.0' or 'leanprover/lean4:v4.35.0'. Exact match: 'v4.36.0-rc2' is not 'v4.36.0'.
    This is the toolchain a package declares, not proof that it built (see get_package builds)."""
    return await _guard("builds_on", toolchain, limit=limit)


@mcp.tool(title='Toolchains in the index',
          annotations=ToolAnnotations(title='Toolchains in the index', **_READ))
async def toolchains() -> ToolchainsResult:
    """Every toolchain that some package's latest version targets, with package counts."""
    return await _guard("toolchains")


@mcp.tool(title='Index status', annotations=ToolAnnotations(title='Index status', **_READ))
async def status() -> StatusResult:
    """Which directory is loaded, when, how many packages/aliases, how long the load took, and
    every entry that failed to parse (`skipped_entries`)."""
    return await _guard("status")


@mcp.tool(title='Reload the index',
          annotations=ToolAnnotations(title='Reload the index', readOnlyHint=True,
                                      destructiveHint=False, idempotentHint=True,
                                      openWorldHint=False))
async def reload() -> StatusResult:
    """Re-read the index directory now. Changes that add, remove or rename package entries are
    picked up automatically; use this after a file was rewritten in place."""
    try:
        await anyio.to_thread.run_sync(STORE.reload)
    except ReservoirError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc),
                "satisfied_when": exc.satisfied_when}
    return await _guard("status")


@mcp.resource(
    "docs://reservoirsearch/readme",
    name="reservoirSearch README",
    title="reservoirSearch - local Lean Reservoir index search",
    description="What the server answers, where the data comes from, and how freshness works.",
    mime_type="text/markdown",
)
def _readme() -> str:
    path = HERE / "README.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        return "README could not be read at %s: %s" % (path, exc)


def main() -> None:
    _serve_with_call_log(mcp, "reservoirSearch")


if __name__ == "__main__":
    main()
