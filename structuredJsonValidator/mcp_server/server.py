"""FastMCP server exposing the multi-collection SSOT store over streamable HTTP.

Run:
    SJV_DATA=path/to/registry.json python -m mcp_server.server
    # optional: SJV_HOST (default 127.0.0.1), SJV_PORT (default 8000),
    #           SJV_ACTOR (default "mcp")

The store holds two collections (interop issue #12, Option B):
  * ``declarations`` — the 1012-decl registry (the default collection for the
    original tools);
  * ``claims`` — the claim graph (its own tools, prefixed ``claim_*``).

Read tools:  get, find, history, view, validate, verify_integrity
Declaration write tools: seal, the §9 verbs (rename, move, drop, mark_present,
  merge, split, reopen, add_new, annotate, annotate_many, annotate_by_filter,
  link_claim, unlink_claim, add_citation, set_verify, set_vocab, import_baseline,
  reconcile).
Claim write tools: claim_add, claim_seed, claim_set_status, claim_set_edge,
  claim_annotate, claim_set_vocab.
Plus a generic collection-aware ``apply`` escape hatch.

Every write returns {ok, ...}. Enforcement failures (schema, §7 rules, the
cross-collection witness invariant, drift, bad params) come back as
{ok: false, error_type, error}. Grant write access only to vetted clients.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from consumers.store import build_store
from core.errors import IntegrityError, OperationError, ValidationError
from core.query import _MISSING, get_path

DATA_PATH = os.environ.get("SJV_DATA", "data/registry.json")
ACTOR = os.environ.get("SJV_ACTOR", "mcp")

mcp = FastMCP(
    "structured-json-validator",
    host=os.environ.get("SJV_HOST", "127.0.0.1"),
    port=int(os.environ.get("SJV_PORT", "8000")),
)


def _store():
    # Fresh store per call so it always reflects the current file on disk.
    return build_store(DATA_PATH, actor=ACTOR)


# Cap the violations echoed on a failed write so a pathological validation
# failure (e.g. thousands of violations) can't blow the caller's token budget
# (interop issue #6 applied to the error path). The full count is always given.
_MAX_VIOLATIONS_ECHO = 100


def _validation_result(exc: ValidationError) -> dict:
    """Terse, budget-safe result for a validation failure (full count + capped
    list). str(ValidationError) joins every violation, so never echo it."""
    violations = exc.violations
    result = {
        "ok": False, "error_type": "validation",
        "error": f"{len(violations)} validation violation(s)",
        "violation_count": len(violations),
        "violations": violations[:_MAX_VIOLATIONS_ECHO],
    }
    if len(violations) > _MAX_VIOLATIONS_ECHO:
        result["violations_truncated"] = len(violations) - _MAX_VIOLATIONS_ECHO
    return result


def _write(collection: str, op: str, params: dict[str, Any]) -> dict:
    """Run a write op on a collection through the library, converting enforcement
    errors into structured results instead of transport-level exceptions."""
    try:
        return {"ok": True, **_store().apply(collection, op, params)}
    except ValidationError as exc:
        return _validation_result(exc)
    except IntegrityError as exc:
        return {"ok": False, "error_type": "integrity", "error": str(exc)}
    except OperationError as exc:
        return {"ok": False, "error_type": "operation", "error": str(exc)}


# -- read tools ---------------------------------------------------------------

@mcp.tool()
def get(id: str, collection: str = "declarations") -> dict:
    """Fetch one entry by its surrogate id from a collection (default
    'declarations'). Returns {found, entry}. For a claim, the greppable key is
    claim_id — use find(collection='claims', filters={'claim_id': '...'})."""
    entry = _store().get(collection, id)
    return {"found": entry is not None, "entry": entry}


def _project(entry: dict, fields: list[str]) -> dict:
    """Pull only the requested dotted paths out of an entry (interop issue #6)."""
    out: dict[str, Any] = {}
    for path in fields:
        value = get_path(entry, path)
        if value is not _MISSING:
            out[path] = value
    return out


@mcp.tool()
def find(filters: dict[str, Any], collection: str = "declarations",
         count_only: bool = False, limit: Optional[int] = None, offset: int = 0,
         fields: Optional[list[str]] = None) -> dict:
    """Find entries in a collection matching every dotted.path=value filter (AND).
    `collection` defaults to 'declarations' (use 'claims' for the claim graph,
    e.g. filters={'claim_id': 'T-SNAP'} or {'status': 'proved'}).

    At scale, keep the return small (interop issue #6):
      - count_only=True   -> just {count}, no entries (cheapest).
      - limit / offset    -> page the results; `count` is the full match total.
      - fields=[...]       -> project only those dotted paths per entry.
    """
    results = _store().find(collection, **filters)
    total = len(results)
    if count_only:
        return {"count": total}
    if offset:
        results = results[offset:]
    if limit is not None:
        results = results[:limit]
    if fields:
        results = [_project(e, fields) for e in results]
    return {"count": total, "returned": len(results), "entries": results}


@mcp.tool()
def history(id: Optional[str] = None) -> dict:
    """Read the append-only whole-store audit log, optionally filtered to one
    entry id (spans all collections; each record is tagged with its collection)."""
    return {"records": _store().history(id)}


@mcp.tool()
def view(kind: str, collection: str = "declarations", count_only: bool = False,
         limit: Optional[int] = None, offset: int = 0) -> dict:
    """Render a projection view from a collection.
    declarations: 'status', 'domains', 'anomalies' (anomalies is the tagging
      worklist — leads with a summary; count_only for just that; limit/offset page).
    claims: 'status' (dated status table with derived live-witness counts) and
      'graph' (a deterministic Mermaid claim graph).
    deps: 'cycles' (directed cycles / mutual blocks — informational, not a gate)."""
    try:
        text = _store().export_view(collection, kind, count_only=count_only,
                                    limit=limit, offset=offset)
        return {"ok": True, "collection": collection, "kind": kind, "text": text}
    except OperationError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def validate() -> dict:
    """Full whole-store conformance: each collection (structural + business) plus
    the cross-collection witness invariant. Returns {valid, violations}."""
    violations = _store().validate()
    return {"valid": not violations, "violations": violations}


@mcp.tool()
def verify_integrity() -> dict:
    """Check the file hash against the last audit hash (whole-store). {ok, hash|error}."""
    try:
        return {"ok": True, "hash": _store().verify_integrity()}
    except IntegrityError as exc:
        return {"ok": False, "error": str(exc)}


# -- declaration write tools --------------------------------------------------

@mcp.tool()
def seal() -> dict:
    """Adopt the current store file as the managed baseline (validate whole store
    + record the whole-store hash)."""
    try:
        rec = _store().seal()
        return {"ok": True, "resulting_sha256": rec["resulting_sha256"]}
    except ValidationError as exc:
        return _validation_result(exc)


@mcp.tool()
def rename(id: str, new_qualified: str, new_file: str, namespace: str, reason: str,
           force: bool = False) -> dict:
    """Rename a declaration into a new qualified name/file/namespace. A terminal
    (dropped/merged) entry is refused unless force=True (reopen it instead)."""
    return _write("declarations", "rename", {"id": id, "new_qualified": new_qualified,
                  "new_file": new_file, "namespace": namespace,
                  "reason": reason, "force": force})


@mcp.tool()
def move(id: str, new_file: str, reason: Optional[str] = None, force: bool = False) -> dict:
    """Move a declaration to a new file (qualified name unchanged by default). A
    terminal (dropped/merged) entry is refused unless force=True."""
    params: dict[str, Any] = {"id": id, "new_file": new_file, "force": force}
    if reason is not None:
        params["reason"] = reason
    return _write("declarations", "move", params)


@mcp.tool()
def mark_present(id: str, force: bool = False) -> dict:
    """Mark a pending declaration as present (new mirrors old identity). A
    terminal (dropped/merged) entry is refused unless force=True."""
    return _write("declarations", "mark_present", {"id": id, "force": force})


@mcp.tool()
def drop(id: str, reason: str, force: bool = False) -> dict:
    """Drop a declaration (new.* stays null; reason required). Re-dropping a
    terminal (dropped/merged) entry is refused unless force=True."""
    return _write("declarations", "drop", {"id": id, "reason": reason, "force": force})


@mcp.tool()
def reopen(id: str, reason: str) -> dict:
    """Return a terminal (dropped/merged) entry to pending so it can be
    re-dispositioned. The sanctioned undo for a deliberate drop/merge."""
    return _write("declarations", "reopen", {"id": id, "reason": reason})


@mcp.tool()
def merge(ids: list[str], target: dict, reason: str, force: bool = False) -> dict:
    """Merge several declarations into one target {qualified, file, namespace?}.
    Needs >= 2 source ids. Any terminal source is refused unless force=True."""
    return _write("declarations", "merge",
                  {"ids": ids, "target": target, "reason": reason, "force": force})


@mcp.tool()
def split(id: str, targets: list[dict], reason: str, force: bool = False) -> dict:
    """Split a declaration; new.* records the primary (first) target. Needs >= 2
    targets. A terminal (dropped/merged) entry is refused unless force=True."""
    return _write("declarations", "split",
                  {"id": id, "targets": targets, "reason": reason, "force": force})


@mcp.tool()
def add_new(new: dict, reason: str) -> dict:
    """Add a genuinely-new declaration (old.* null). new={qualified, file, namespace?}."""
    return _write("declarations", "add_new", {"new": new, "reason": reason})


@mcp.tool()
def annotate(id: str, object=None, domain=None, role=None) -> dict:
    """Set curated ontology axes (only the provided ones). Each axis is stored as
    a LIST; a scalar is coerced (`"core"` -> `["core"]`), a list is kept, and
    `[]` clears. An omitted axis is left unchanged."""
    params: dict[str, Any] = {"id": id}
    if object is not None:
        params["object"] = object
    if domain is not None:
        params["domain"] = domain
    if role is not None:
        params["role"] = role
    return _write("declarations", "annotate", params)


@mcp.tool()
def annotate_many(items: list[dict], force: bool = False) -> dict:
    """Batch-annotate declaration ontology axes by explicit id — the write-side
    scale tool. `items` is a list of `{id, object?, domain?, role?, …}`. Per item:
    an omitted axis is left unchanged, a value SETS it, explicit `null` CLEARS it.
    Atomic; terse receipt `{ok, count, unchanged, resulting_sha256}`."""
    return _write("declarations", "annotate_many", {"items": items, "force": force})


@mcp.tool()
def annotate_by_filter(filter: dict, tags: dict, dry_run: bool = False,
                       force: bool = False) -> dict:
    """Annotate every declaration matching a `find`-style filter with uniform
    `tags`. `filter` uses dotted-path AND semantics (e.g. {"old.prefix":"ZPA"},
    or add {"ontology.domain": []} to hit only untagged ones). An empty filter is
    refused unless force=true. With dry_run=true NOTHING is written — returns
    {ok, would_match, sample}. On apply: {ok, matched, updated, resulting_sha256}."""
    if dry_run:
        if not isinstance(filter, dict):
            return {"ok": False, "error": "filter must be an object"}
        if not filter and not force:
            return {"ok": False, "error":
                    "empty filter would match the whole registry; pass force=true"}
        matches = _store().find("declarations", **filter)
        sample = []
        for m in matches[:20]:
            grp = m.get("new") if m.get("disposition") in ("renamed", "new") else m.get("old")
            sample.append({"id": m.get("id"), "qualified": (grp or {}).get("qualified")})
        return {"ok": True, "dry_run": True, "would_match": len(matches), "sample": sample}
    return _write("declarations", "annotate_by_filter",
                  {"filter": filter, "tags": tags, "force": force})


@mcp.tool()
def set_vocab(vocab=None) -> dict:
    """Adopt the DECLARATION controlled ontology vocab from a caller-owned config.
    `vocab` may be an inline object or a path; omit it to load the default
    tag_vocab.json from the store's data folder. Once set, `validate` REJECTS
    ontology values outside their field's list; cardinality stays a soft
    expectation surfaced by view('anomalies')."""
    source = vocab if vocab is not None else str(_store().vocab_path("declarations"))
    return _write("declarations", "set_vocab", {"vocab": source})


@mcp.tool()
def link_claim(id: str, claim: str) -> dict:
    """Link a declaration to a claim it witnesses (declarations.claims.witness_of).
    The claim must already exist (a dangling link is refused). If the claim is
    proved/deep and this decl is sorry_free, it becomes a live witness."""
    return _write("declarations", "link_claim", {"id": id, "claim": claim})


@mcp.tool()
def unlink_claim(id: str, claim: str) -> dict:
    """Remove a claim from a declaration's witness_of. If this was the last live
    witness of a proved/deep claim, the write is refused (the store invariant
    rolls it back) — a witness cannot be silently pulled from under a proved claim."""
    return _write("declarations", "unlink_claim", {"id": id, "claim": claim})


@mcp.tool()
def add_citation(id: str, target: str) -> dict:
    """Add a citation to a declaration (claims.citations)."""
    return _write("declarations", "add_citation", {"id": id, "target": target})


@mcp.tool()
def set_verify(id: str, sorry_free: Optional[bool] = None, axioms=None) -> dict:
    """Record the build-derived verification state on a declaration. Flipping
    sorry_free to false on the sole live witness of a proved/deep claim is refused
    (a broken proof cannot leave a proved claim standing)."""
    params: dict[str, Any] = {"id": id}
    if sorry_free is not None:
        params["sorry_free"] = sorry_free
    if axioms is not None:
        params["axioms"] = axioms
    return _write("declarations", "set_verify", params)


@mcp.tool()
def reconcile(scanner_output, anchor: Optional[dict] = None) -> dict:
    """Fold a fresh scan into the declarations collection, preserving curation.
    Matches scan decls to entries by fully-qualified name, updates locations, ADDS
    new decls as pending, and FLAGS vanished / phantom / resurrected names — never
    silently drops or guesses a rename. Returns a terse {ok, ..., drift} summary."""
    params: dict[str, Any] = {"scanner_output": scanner_output}
    if anchor is not None:
        params["anchor"] = anchor
    return _write("declarations", "reconcile", params)


# -- claim write tools --------------------------------------------------------

@mcp.tool()
def claim_add(claim_id: str, statement: str, status: Optional[str] = None,
              object=None, domain=None, date: Optional[str] = None,
              reason: Optional[str] = None, from_claim: Optional[str] = None,
              to_claim: Optional[str] = None) -> dict:
    """Add one claim (a NODE, or an EDGE when from_claim/to_claim are given — one
    shape). `claim_id` is the greppable natural key (e.g. 'T-SNAP'); `status` seeds
    the history provenance. `from_claim`/`to_claim` are the edge endpoints — the
    claim_ids this edge connects (both must reference existing claims). `status`
    must clear the enum; proved/deep additionally require a live declaration
    witness."""
    params: dict[str, Any] = {"claim_id": claim_id, "statement": statement}
    if status is not None:
        params["status"] = status
    if object is not None:
        params["object"] = object
    if domain is not None:
        params["domain"] = domain
    if date is not None:
        params["date"] = date
    if reason is not None:
        params["reason"] = reason
    if from_claim is not None:
        params["from"] = from_claim
    if to_claim is not None:
        params["to"] = to_claim
    return _write("claims", "add_claim", params)


@mcp.tool()
def claim_seed(items: list[dict], force: bool = False) -> dict:
    """Bulk-add claims atomically. `items` is a list of claim_add-shaped dicts.
    Edges may reference sibling claims added in the SAME batch (the whole batch is
    one validated postcondition). Duplicate claim_id (in-batch or existing) is
    refused. Terse receipt {ok, count, resulting_sha256}."""
    return _write("claims", "seed_claims", {"items": items, "force": force})


@mcp.tool()
def claim_set_status(claim_id: str, status: str, date: Optional[str] = None,
                     reason: Optional[str] = None) -> dict:
    """Change a claim's status and APPEND {status, date} to its history (append-
    only provenance; downgrades are kept, never erased). proved/deep require a
    live declaration witness or the change is refused."""
    params: dict[str, Any] = {"claim_id": claim_id, "status": status}
    if date is not None:
        params["date"] = date
    if reason is not None:
        params["reason"] = reason
    return _write("claims", "set_status", params)


@mcp.tool()
def claim_set_edge(claim_id: str, from_claim: Optional[str] = None,
                   to_claim: Optional[str] = None) -> dict:
    """Set the from/to endpoints on an existing claim, turning a node into an edge.
    `from_claim`/`to_claim` are the endpoint claim_ids (reference-checked). At least
    one must be given. (To CLEAR an endpoint to null, use `apply` with
    op='set_edge', params={'claim_id':..., 'from': null}.)"""
    params: dict[str, Any] = {"claim_id": claim_id}
    if from_claim is not None:
        params["from"] = from_claim
    if to_claim is not None:
        params["to"] = to_claim
    return _write("claims", "set_edge", params)


@mcp.tool()
def claim_drop(claim_id: str, reason: str) -> dict:
    """Remove a claim seeded in error (hard delete of the node/edge). For RETIRING
    a claim while keeping its history, use claim_set_status (e.g. a 'retracted'
    status) instead. Invariant-guarded: dropping a claim that declarations still
    witness, or that is an edge endpoint, is refused (unlink/repoint first).
    reason is required."""
    return _write("claims", "drop_claim", {"claim_id": claim_id, "reason": reason})


@mcp.tool()
def claim_annotate(claim_id: str, object=None, domain=None) -> dict:
    """Set the curated object/domain axes on a claim (reuses the declaration
    object/domain vocab; element-aware). Only provided axes change; [] clears."""
    params: dict[str, Any] = {"claim_id": claim_id}
    if object is not None:
        params["object"] = object
    if domain is not None:
        params["domain"] = domain
    return _write("claims", "annotate_claim", params)


@mcp.tool()
def claim_set_vocab(vocab=None) -> dict:
    """Adopt the CLAIMS controlled vocab (object/domain/status) from a caller-owned
    config. `vocab` may be inline or a path; omit it to load the default
    claims_vocab.json from the store's data folder. status extends its built-in
    floor (commitment/conj/corr/deep/proved); object/domain are vocab-governed."""
    source = vocab if vocab is not None else str(_store().vocab_path("claims"))
    return _write("claims", "set_vocab", {"vocab": source})


# -- deps write tools ---------------------------------------------------------

@mcp.tool()
def import_deps(edges) -> dict:
    """Bulk-import the declaration dependency graph (interop #13) — a whole-
    collection REPLACE from a freshly extracted edge set. `edges` is an inline list
    of {from, to, kind?} (kind: 'type'|'proof'|null) OR a path to a JSON file (the
    practical form at 5k–30k edges). Endpoints reference the effective-current
    declaration `qualified`; a dangling from/to fails validate (nothing written).
    Identical (from,to,kind) edges are deduped. Terse receipt {ok, replaced,
    imported, deduped, resulting_sha256} — the wholesale swap is derived-data
    semantics (no curation to preserve)."""
    return _write("deps", "import_deps", {"edges": edges})


# -- publication + generic escape hatch ---------------------------------------

@mcp.tool()
def export_full(dest: str) -> dict:
    """Publish the COMPLETE validated store (all collections) as a deterministic
    artifact to `dest`, for the caller to commit with git. Refuses to export an
    invalid or drifted store. Returns {ok, dest, entries, export_sha256,
    source_sha256}."""
    try:
        return {"ok": True, **_store().export_full(dest)}
    except ValidationError as exc:
        return _validation_result(exc)
    except IntegrityError as exc:
        return {"ok": False, "error_type": "integrity", "error": str(exc)}


@mcp.tool()
def apply(op: str, params: dict, collection: str = "declarations") -> dict:
    """Generic escape hatch: run any registered operation on a collection
    (default 'declarations') with a params dict."""
    return _write(collection, op, params)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
