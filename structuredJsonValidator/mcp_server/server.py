"""FastMCP server exposing the Lean SSOT registry over streamable HTTP.

Run:
    SJV_DATA=path/to/registry.json python -m mcp_server.server
    # optional: SJV_HOST (default 127.0.0.1), SJV_PORT (default 8000),
    #           SJV_ACTOR (default "mcp")

Read tools:  get, find, history, view, validate, verify_integrity
Write tools: seal, and the §9 verbs (rename, move, drop, mark_present, merge,
             split, reopen, add_new, annotate, link_claim, add_citation,
             import_baseline) plus a generic `apply` escape hatch.

Every write returns {ok, ...}. Enforcement failures (schema, §7 rules, drift,
bad params) come back as {ok: false, error_type, error} — the library raised,
the wrapper only reports. Grant write access only to vetted clients (spec §11).
"""

from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from consumers.lean import build_registry
from core.errors import IntegrityError, OperationError, ValidationError

DATA_PATH = os.environ.get("SJV_DATA", "data/registry.json")
ACTOR = os.environ.get("SJV_ACTOR", "mcp")

mcp = FastMCP(
    "structured-json-validator",
    host=os.environ.get("SJV_HOST", "127.0.0.1"),
    port=int(os.environ.get("SJV_PORT", "8000")),
)


def _registry():
    # Fresh registry per call so it always reflects the current file on disk.
    return build_registry(DATA_PATH, actor=ACTOR)


def _write(op: str, params: dict[str, Any]) -> dict:
    """Run a write op through the library, converting enforcement errors into
    structured results instead of transport-level exceptions."""
    try:
        return {"ok": True, **_registry().apply(op, params)}
    except ValidationError as exc:
        return {"ok": False, "error_type": "validation", "error": str(exc), "violations": exc.violations}
    except IntegrityError as exc:
        return {"ok": False, "error_type": "integrity", "error": str(exc)}
    except OperationError as exc:
        return {"ok": False, "error_type": "operation", "error": str(exc)}


# -- read tools ---------------------------------------------------------------

@mcp.tool()
def get(id: str) -> dict:
    """Fetch one entry by its id. Returns {found, entry}."""
    entry = _registry().get(id)
    return {"found": entry is not None, "entry": entry}


@mcp.tool()
def find(filters: dict[str, Any]) -> dict:
    """Find entries matching every dotted.path=value filter (AND). Example
    filters: {"disposition": "pending", "ontology.domain": "number"}."""
    results = _registry().find(**filters)
    return {"count": len(results), "entries": results}


@mcp.tool()
def history(id: Optional[str] = None) -> dict:
    """Read the append-only audit log, optionally filtered to one entry id."""
    return {"records": _registry().history(id)}


@mcp.tool()
def view(kind: str) -> dict:
    """Render a projection view (e.g. 'status', 'domains') from the source."""
    try:
        return {"ok": True, "kind": kind, "text": _registry().export_view(kind)}
    except OperationError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def validate() -> dict:
    """Full-file conformance (structural + §7). Returns {valid, violations}."""
    violations = _registry().validate()
    return {"valid": not violations, "violations": violations}


@mcp.tool()
def verify_integrity() -> dict:
    """Check the file hash against the last audit hash. {ok, hash|error}."""
    try:
        return {"ok": True, "hash": _registry().verify_integrity()}
    except IntegrityError as exc:
        return {"ok": False, "error": str(exc)}


# -- write tools --------------------------------------------------------------

@mcp.tool()
def seal() -> dict:
    """Adopt the current file as the managed baseline (validate + record hash)."""
    try:
        rec = _registry().seal()
        return {"ok": True, "resulting_sha256": rec["resulting_sha256"]}
    except ValidationError as exc:
        return {"ok": False, "error_type": "validation", "error": str(exc), "violations": exc.violations}


@mcp.tool()
def rename(id: str, new_qualified: str, new_file: str, namespace: str, reason: str,
           force: bool = False) -> dict:
    """Rename a declaration into a new qualified name/file/namespace. A terminal
    (dropped/merged) entry is refused unless force=True (reopen it instead)."""
    return _write("rename", {"id": id, "new_qualified": new_qualified,
                             "new_file": new_file, "namespace": namespace,
                             "reason": reason, "force": force})


@mcp.tool()
def move(id: str, new_file: str, reason: Optional[str] = None, force: bool = False) -> dict:
    """Move a declaration to a new file (qualified name unchanged by default). A
    terminal (dropped/merged) entry is refused unless force=True."""
    params: dict[str, Any] = {"id": id, "new_file": new_file, "force": force}
    if reason is not None:
        params["reason"] = reason
    return _write("move", params)


@mcp.tool()
def mark_present(id: str, force: bool = False) -> dict:
    """Mark a pending declaration as present (new mirrors old identity). A
    terminal (dropped/merged) entry is refused unless force=True."""
    return _write("mark_present", {"id": id, "force": force})


@mcp.tool()
def drop(id: str, reason: str, force: bool = False) -> dict:
    """Drop a declaration (new.* stays null; reason required). Re-dropping a
    terminal (dropped/merged) entry is refused unless force=True."""
    return _write("drop", {"id": id, "reason": reason, "force": force})


@mcp.tool()
def reopen(id: str, reason: str) -> dict:
    """Return a terminal (dropped/merged) entry to pending so it can be
    re-dispositioned. The sanctioned undo for a deliberate drop/merge."""
    return _write("reopen", {"id": id, "reason": reason})


@mcp.tool()
def merge(ids: list[str], target: dict, reason: str, force: bool = False) -> dict:
    """Merge several declarations into one target {qualified, file, namespace?}.
    Needs >= 2 source ids. Any terminal source is refused unless force=True."""
    return _write("merge", {"ids": ids, "target": target, "reason": reason, "force": force})


@mcp.tool()
def split(id: str, targets: list[dict], reason: str, force: bool = False) -> dict:
    """Split a declaration; new.* records the primary (first) target. Needs >= 2
    targets. A terminal (dropped/merged) entry is refused unless force=True."""
    return _write("split", {"id": id, "targets": targets, "reason": reason, "force": force})


@mcp.tool()
def add_new(new: dict, reason: str) -> dict:
    """Add a genuinely-new declaration (old.* null). new={qualified, file, namespace?}."""
    return _write("add_new", {"new": new, "reason": reason})


@mcp.tool()
def annotate(id: str, object: Optional[str] = None, domain: Optional[str] = None,
             role: Optional[str] = None) -> dict:
    """Set curated ontology axes (only the provided ones)."""
    params: dict[str, Any] = {"id": id}
    if object is not None:
        params["object"] = object
    if domain is not None:
        params["domain"] = domain
    if role is not None:
        params["role"] = role
    return _write("annotate", params)


@mcp.tool()
def link_claim(id: str, claim: str) -> dict:
    """Link a claim to an entry (claims.witness_of)."""
    return _write("link_claim", {"id": id, "claim": claim})


@mcp.tool()
def add_citation(id: str, target: str) -> dict:
    """Add a citation to an entry (claims.citations)."""
    return _write("add_citation", {"id": id, "target": target})


@mcp.tool()
def export_full(dest: str) -> dict:
    """Publish the COMPLETE validated registry as a deterministic artifact to
    `dest` (e.g. a path inside a consuming repo), for the caller to commit with
    git. Distinct from `view`: this is the full, schema-valid, byte-stable dump,
    not a lossy projection. Refuses to export an invalid or drifted source.
    Returns {ok, dest, entries, export_sha256, source_sha256}."""
    try:
        return {"ok": True, **_registry().export_full(dest)}
    except ValidationError as exc:
        return {"ok": False, "error_type": "validation", "error": str(exc), "violations": exc.violations}
    except IntegrityError as exc:
        return {"ok": False, "error_type": "integrity", "error": str(exc)}


@mcp.tool()
def apply(op: str, params: dict) -> dict:
    """Generic escape hatch: run any registered operation with a params dict."""
    return _write(op, params)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
