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
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# ⚠ The repo root, so `mcpcommon` resolves. The supervisor starts this server with the
# SERVER directory on sys.path (that is what makes `from consumers import ...` work), and
# the repo root is not on it. Derived from __file__ rather than the cwd, because the cwd
# is the supervisor's choice and has changed before.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcpcommon.calllog import serve as _serve_with_call_log  # noqa: E402
from mcpcommon.iserror import install as _install_is_error, install_resource_classification  # noqa: E402

from mcp_server.results import (  # noqa: E402
    CheckHeadResult, ExportResult, FindResult, GetResult, HistoryResult,
    ValidateResult, VerifyIntegrityResult, ViewResult, WriteResult)

from consumers.store import build_store, head_correspondence, require_source_root
from core.errors import IntegrityError, OperationError, ValidationError
from core import store as _store_bytes
from core.query import _MISSING, get_path

DATA_PATH = os.environ.get("SJV_DATA", "data/registry.json")
ACTOR = os.environ.get("SJV_ACTOR", "mcp")

mcp = FastMCP(
    "structured-json-validator",
    instructions="""A validated JSON store: schema-checked collections with integrity
verification, content addressing and history.

START HERE: validate() — whole-store, takes NO arguments — then view(kind='status') for a
summary of one collection. To learn which collections exist, call find with a collection
that does not exist: the refusal names them all.

THE FIVE THAT MATTER: view - find - get - validate - verify_integrity.

THE MISTAKE THAT WILL BITE YOU: assuming every response carries ok:true. It does NOT on this
server - find(filters={}, count_only=True) returns {count}, validate returns
{valid, violations}. Read
the tool's own outputSchema rather than assuming a fleet-wide shape. A REFUSAL carries
isError:true and a JSON body, never structuredContent.

OBSERVED 2026-09-09, 6-for-6 across three servers: after this server RESTARTS, the first
call on a connection that predates the restart fails with a bare transport error and NO
body - retry once and the second call succeeds. Isolated by an accidental control in one
batch: the server whose connection had already been re-established succeeded on its first
read; the two that were stale failed. The only variable that differed was connection age.

This is a DATED OBSERVATION ABOUT CLIENT BEHAVIOUR, not a guarantee. Neither this server
nor its author owns the client, and a client change could end it without notice. It is
written here rather than in the error payload because the payload IS classified -
error_type unavailable, retryable true - and at least one MCP client discards it and
surfaces only "Connection closed".""",
    host=os.environ.get("SJV_HOST", "127.0.0.1"),
    port=int(os.environ.get("SJV_PORT", "8000")),
)

# ⚠ AFTER the constructor: FastMCP registers its own call_tool handler there, and this
# replaces it so a refusal sets `isError` while the body stays pure JSON.
_install_is_error(mcp)
# Resources get the same classification the tool path has had since the ledger was
# built: a failure says whether retrying could ever help. Found missing 2026-09-08.
install_resource_classification(mcp)


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
        return {"ok": False, "error_type": IntegrityError.error_type, "error": str(exc)}
    except OperationError as exc:
        # ⚠ `satisfied_when` IS FORWARDED WHEN THE RAISE SUPPLIED ONE, and omitted when it did
        # not. Measured 2026-09-10: the ABSENT-root branch above returns a satisfied_when while
        # this branch dropped it, so two refusals from the same tool -- both `usage`, both about
        # `root` -- carried different shapes depending on which line produced them. A caller
        # cannot tell "this refusal has no success condition" from "this path forgot to pass one".
        refusal = {"ok": False, "error_type": OperationError.error_type, "error": str(exc)}
        satisfied_when = getattr(exc, "satisfied_when", None)
        if satisfied_when:
            refusal["satisfied_when"] = satisfied_when
        return refusal


def _write_store(op: str, params: dict[str, Any]) -> dict:
    """Run a STORE-LEVEL (cross-collection) op — same error mapping as ``_write``."""
    try:
        return {"ok": True, **_store().apply_store(op, params)}
    except ValidationError as exc:
        return _validation_result(exc)
    except IntegrityError as exc:
        return {"ok": False, "error_type": IntegrityError.error_type, "error": str(exc)}
    except OperationError as exc:
        # ⚠ `satisfied_when` IS FORWARDED WHEN THE RAISE SUPPLIED ONE, and omitted when it did
        # not. Measured 2026-09-10: the ABSENT-root branch above returns a satisfied_when while
        # this branch dropped it, so two refusals from the same tool -- both `usage`, both about
        # `root` -- carried different shapes depending on which line produced them. A caller
        # cannot tell "this refusal has no success condition" from "this path forgot to pass one".
        refusal = {"ok": False, "error_type": OperationError.error_type, "error": str(exc)}
        satisfied_when = getattr(exc, "satisfied_when", None)
        if satisfied_when:
            refusal["satisfied_when"] = satisfied_when
        return refusal


# -- read tools ---------------------------------------------------------------

@mcp.tool(title='Get one entry',
          annotations=ToolAnnotations(title='Get one entry', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def get(id: str, collection: str = "declarations") -> GetResult:
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


@mcp.tool(title='Search entries',
          annotations=ToolAnnotations(title='Search entries', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def find(filters: dict[str, Any], collection: str = "declarations",
         count_only: bool = False, limit: Optional[int] = None, offset: int = 0,
         fields: Optional[list[str]] = None) -> FindResult:
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


@mcp.tool(title='Entry history',
          annotations=ToolAnnotations(title='Entry history', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def history(id: Optional[str] = None) -> HistoryResult:
    """Read the append-only whole-store audit log, optionally filtered to one
    entry id (spans all collections; each record is tagged with its collection)."""
    return {"records": _store().history(id)}


@mcp.tool(title='View the store',
          annotations=ToolAnnotations(title='View the store', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def view(kind: str, collection: str = "declarations", count_only: bool = False,
         limit: Optional[int] = None, offset: int = 0, root: Optional[str] = None) -> ViewResult:
    """Render a projection view from a collection.
    declarations: 'status' (per-disposition counts, with a LIVE total that excludes
      dropped/merged/split/withdrawn), 'domains', 'anomalies' (the tagging worklist
      — leads with a summary; count_only for just that; limit/offset page), and
      'phantoms' (entries whose new.file does not resolve on disk — pass `root` for
      the corpus checkout; a report, never a gate).
    claims: 'status' (dated status table with derived live-witness counts) and
      'graph' (a deterministic Mermaid claim graph).
    deps: 'cycles' (directed cycles / mutual blocks — informational, not a gate)."""
    try:
        extra = {} if root is None else {"root": root}
        text = _store().export_view(collection, kind, count_only=count_only,
                                    limit=limit, offset=offset, **extra)
        return {"ok": True, "collection": collection, "kind": kind, "text": text}
    except OperationError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool(title='Validate without writing',
          annotations=ToolAnnotations(title='Validate without writing', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def validate() -> ValidateResult:
    """Full whole-store conformance: each collection (structural + business) plus
    the cross-collection witness invariant. Returns {valid, violations}."""
    violations = _store().validate()
    return {"valid": not violations, "violations": violations}


@mcp.tool(title='Check head correspondence',
          annotations=ToolAnnotations(title='Check head correspondence', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def check_head(root: str = "", tier: str = "paths", limit: int = 25) -> CheckHeadResult:
    """HEAD-correspondence check: does the registry still describe the SOURCE TREE?
    (interop #16b/#17.)

    `validate` proves the store is internally well-formed; it cannot prove the
    store still matches reality, and drift has shipped green three times. This is
    the check that fails loud instead — run it before `export_full`.

    tier='paths' (cheap, the default): every live entry's `new.file` resolves on
    disk under `root`. One stat per entry, no Lean parsing — catches a reverted
    file's whole stranded declaration set. tier='names': additionally each live
    entry's short name is actually declared in that file — strictly stronger,
    catches a live FILE with a dead NAME (a theorem split), heuristic by nature
    (it reads the source, it does not elaborate it).

    Also reports duplicate live names. Read-only; terse (counts + bounded sample).
    Returns {ok, checked, resolved, unresolvable_files, missing_files[],
    missing_files_by_file{}, duplicate_live_names, duplicates[]}."""
    # ⛔⛔ `root` USED TO DEFAULT TO ".", AND THAT IS A CONFIDENT WRONG ANSWER RATHER THAN A
    # MISSING ONE. This is a long-lived SERVER: "." is whatever directory the supervisor
    # happened to launch it from, which is not the source tree the registry describes and is
    # not knowable to the caller. Measured 2026-09-10 by an external conformance sweep:
    # `check_head()` reported `root: "."`, checked 1717, resolved 0, unresolvable 1717 —
    # which reads as TOTAL registry drift and is almost certainly a wrong root.
    #
    # ⚠ The registry describes the CONSUMER's source tree; this server's own directory is not
    # it, so there is no defensible server-side default. Refusing names the success condition;
    # guessing produces a catastrophic-looking number that is a true count of the wrong thing.
    resolved_root = root or os.environ.get("SJV_ROOT", "")
    if not resolved_root:
        # RETURNED, NOT RAISED -- and the difference is the whole reason `mcpcommon/iserror.py`
        # exists. A raise escapes to FastMCP, which REWRITES the text to
        # "Error executing tool check_head: <msg>" and stamps error_type `unhandled`; the body
        # stops being JSON and the caller's json.loads falls back to None. Measured here
        # 2026-09-10 by raising it first and reading the wire: the refusal came back prefixed
        # and unparseable, which is the exact shape iserror.py's docstring warns sjv's raising
        # read tools already produce. A refusal must travel as DATA.
        return {
            "ok": False,
            "error_type": OperationError.error_type,
            "error": "check_head needs a `root` — the source tree the registry describes.",
            "satisfied_when": (
                "pass `root` as the absolute path of the source tree the registry describes "
                "(or set SJV_ROOT in the server's environment). This server's own directory "
                "is not that tree, and a long-lived server has no meaningful current "
                "directory to fall back on — a relative default resolves against wherever "
                "the supervisor happened to launch it and reports every entry unresolvable."),
        }
    try:
        report = head_correspondence(_store().load(), root=resolved_root,
                                     tier=tier, limit=limit)
    except OperationError as exc:
        # ⚠ `satisfied_when` IS FORWARDED WHEN THE RAISE SUPPLIED ONE, and omitted when it did
        # not. Measured 2026-09-10: the ABSENT-root branch above returns a satisfied_when while
        # this branch dropped it, so two refusals from the same tool -- both `usage`, both about
        # `root` -- carried different shapes depending on which line produced them. A caller
        # cannot tell "this refusal has no success condition" from "this path forgot to pass one".
        refusal = {"ok": False, "error_type": OperationError.error_type, "error": str(exc)}
        satisfied_when = getattr(exc, "satisfied_when", None)
        if satisfied_when:
            refusal["satisfied_when"] = satisfied_when
        return refusal

    # ⛔⛔ THE DOMAIN `ok` MUST NOT CLOBBER THE CALL-STATUS `ok`. `head_correspondence`
    # returns its own `ok` — "no drift", the FINDING axis, which `core/cli.py` turns into
    # exit 0-vs-1 — and `{"ok": True, **report}` let the spread overwrite the call status
    # with it. So a successful call that FOUND drift answered `ok: false`, and
    # `mcpcommon/iserror.py` read that as a refusal and stripped the whole report's
    # `structuredContent`. One key, two axes, decided by dict ordering.
    # ⭐ Renamed on the way out: `matches` carries the finding, `ok` carries the call.
    matches = report.pop("ok", None)
    out = {"ok": True, "matches": matches, "root": str(Path(resolved_root).resolve()),
           **report}

    # ⚠ NOTHING RESOLVING AT ALL IS EVIDENCE ABOUT THE ROOT, NOT ABOUT THE REGISTRY. Said
    # here rather than left for the reader, because "1717 of 1717 unresolvable" is exactly
    # the shape that gets reported upward as a crisis.
    #
    # ⭐ THIS NOTE IS NOW CORRECTLY SCOPED, WHICH IT WAS NOT BEFORE 2026-09-10. It used to
    # cover a root that did not exist at all, i.e. it was doing double duty as an advisory for
    # a finding AND as cover for a typo. `head_correspondence` now REFUSES a nonexistent or
    # non-directory root, so by the time this line runs the root is a real directory and
    # "wrong tree" is the honest reading of zero-resolved rather than a guess spanning two
    # unrelated causes.
    #
    # ⚠ KNOWN AND DELIBERATE, raised by the zptester session the same day: this fires only at
    # EXACTLY zero, so a registry that genuinely drifted 100% still reports `matches: False`
    # with this advisory attached. That is a guard scoped to a ROUTE (wrong root) rather than
    # to a PROPERTY (registry matches). The trade is accepted -- a wrong root is common and
    # total drift is not -- and it is recorded here rather than left for someone to rediscover.
    if out.get("checked") and not out.get("resolved"):
        out["note"] = (
            "ZERO of %d entries resolved. A wrong `root` explains this better than total "
            "drift — check that %s is the source tree the registry describes before "
            "treating this as a finding." % (out["checked"], out["root"]))
    return out


@mcp.tool(title='Verify store integrity',
          annotations=ToolAnnotations(title='Verify store integrity', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def verify_integrity() -> VerifyIntegrityResult:
    """Check the file hash against the last audit hash (whole-store). {ok, hash|error}."""
    try:
        return {"ok": True, "hash": _store().verify_integrity()}
    except IntegrityError as exc:
        return {"ok": False, "error": str(exc)}


# -- declaration write tools --------------------------------------------------

@mcp.tool(title='Seal an entry',
          annotations=ToolAnnotations(title='Seal an entry', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def seal() -> WriteResult:
    """Adopt the current store file as the managed baseline (validate whole store
    + record the whole-store hash)."""
    try:
        rec = _store().seal()
        return {"ok": True, "resulting_sha256": rec["resulting_sha256"]}
    except ValidationError as exc:
        return _validation_result(exc)


@mcp.tool(title='Rename an entry',
          annotations=ToolAnnotations(title='Rename an entry', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def rename(id: str, new_qualified: str, new_file: str, namespace: str, reason: str,
           force: bool = False) -> WriteResult:
    """Rename a declaration into a new qualified name/file/namespace. A terminal
    (dropped/merged) entry is refused unless force=True (reopen it instead)."""
    return _write("declarations", "rename", {"id": id, "new_qualified": new_qualified,
                  "new_file": new_file, "namespace": namespace,
                  "reason": reason, "force": force})


@mcp.tool(title='Move an entry',
          annotations=ToolAnnotations(title='Move an entry', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def move(id: str, new_file: str, reason: Optional[str] = None, force: bool = False) -> WriteResult:
    """Move a declaration to a new file (qualified name unchanged by default). A
    terminal (dropped/merged) entry is refused unless force=True."""
    params: dict[str, Any] = {"id": id, "new_file": new_file, "force": force}
    if reason is not None:
        params["reason"] = reason
    return _write("declarations", "move", params)


@mcp.tool(title='Mark present',
          annotations=ToolAnnotations(title='Mark present', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def mark_present(id: str, force: bool = False) -> WriteResult:
    """Mark a pending declaration as present (new mirrors old identity). A
    terminal (dropped/merged) entry is refused unless force=True."""
    return _write("declarations", "mark_present", {"id": id, "force": force})


@mcp.tool(title='Drop an entry',
          annotations=ToolAnnotations(title='Drop an entry', readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
def drop(id: str, reason: str, force: bool = False) -> WriteResult:
    """Record that a declaration that EXISTED at the anchor is gone at HEAD (new.*
    cleared; reason required). Requires a REAL anchored old identity — an entry
    added after the baseline never had one, so 'dropped' would be false history
    there; use `withdraw` (added in error) or `remove` (erase). Re-dropping a
    terminal entry is refused unless force=True."""
    return _write("declarations", "drop", {"id": id, "reason": reason, "force": force})


@mcp.tool(title='Withdraw an entry',
          annotations=ToolAnnotations(title='Withdraw an entry', readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
def withdraw(id: str, reason: str, force: bool = False) -> WriteResult:
    """Terminal state for an entry ADDED IN ERROR — the mirror image of `drop`.

    `drop` presupposes a prior identity ("this existed and is now gone"). An entry
    created by `add_new` for a declaration that was then reverted has none and never
    existed at HEAD, so it had no legal terminal state. `withdrawn` is that state.

    The two are kept non-overlapping by the old side: `drop` requires a REAL anchored
    identity, `withdraw` requires there is none — so neither can launder the other,
    and nobody has to invent provenance to satisfy the validator. new.qualified is
    KEPT (the name that was added in error is the substance of the record). reason
    required. Terminal; `reopen` restores it to 'new'. A withdrawn name is treated as
    GONE, so a deps edge onto it dangles, exactly as for dropped."""
    return _write("declarations", "withdraw", {"id": id, "reason": reason, "force": force})


@mcp.tool(title='Remove an entry',
          annotations=ToolAnnotations(title='Remove an entry', readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
def remove(ids, reason: str) -> WriteResult:
    """HARD-DELETE born-at-HEAD declaration entries — the missing inverse of
    `add_new` (interop #15a/#16a/#17).

    `drop` tombstones (keeps the entry, records that the decl is gone), which is
    right when there is an anchored lineage worth preserving. `remove` erases, and
    is allowed ONLY for entries that were never real at the anchor: `old` synthetic
    (born at HEAD) or, for legacy entries, absent. An anchored entry is refused —
    retire it with drop/merge instead.

    Use it for a reverted build (a new .lean file added then `git revert`ed strands
    its whole decl set) and to repair duplicate live names. `ids` takes a list, so
    a stranded set — or several duplicates — clear in ONE atomic write. Removing a
    decl that a proved claim's last live witness depends on, or that a deps edge
    references, fails the store postcondition and rolls back.
    Receipt {ok, removed, remaining, resulting_sha256}."""
    return _write("declarations", "remove", {"ids": ids, "reason": reason})


@mcp.tool(title='Reopen an entry',
          annotations=ToolAnnotations(title='Reopen an entry', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def reopen(id: str, reason: str) -> WriteResult:
    """Return a terminal (dropped/merged) entry to pending so it can be
    re-dispositioned. The sanctioned undo for a deliberate drop/merge."""
    return _write("declarations", "reopen", {"id": id, "reason": reason})


@mcp.tool(title='Merge entries',
          annotations=ToolAnnotations(title='Merge entries', readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def merge(ids: list[str], target: dict, reason: str, force: bool = False) -> WriteResult:
    """Merge several declarations into one target {qualified, file, namespace?}.
    Needs >= 2 source ids. Any terminal source is refused unless force=True."""
    return _write("declarations", "merge",
                  {"ids": ids, "target": target, "reason": reason, "force": force})


@mcp.tool(title='Split an entry',
          annotations=ToolAnnotations(title='Split an entry', readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def split(id: str, targets: list[dict], reason: str, force: bool = False) -> WriteResult:
    """Split a declaration; new.* records the primary (first) target. Needs >= 2
    targets. A terminal (dropped/merged) entry is refused unless force=True."""
    return _write("declarations", "split",
                  {"id": id, "targets": targets, "reason": reason, "force": force})


@mcp.tool(title='Add a new entry',
          annotations=ToolAnnotations(title='Add a new entry', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def add_new(new: dict, reason: str) -> WriteResult:
    """Add a genuinely-new declaration (old.* null). new={qualified, file, namespace?}."""
    return _write("declarations", "add_new", {"new": new, "reason": reason})


@mcp.tool(title='Annotate an entry',
          annotations=ToolAnnotations(title='Annotate an entry', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def annotate(id: str, object=None, domain=None, role=None) -> WriteResult:
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


@mcp.tool(title='Annotate many entries',
          annotations=ToolAnnotations(title='Annotate many entries', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def annotate_many(items: list[dict], force: bool = False) -> WriteResult:
    """Batch-annotate declaration ontology axes by explicit id — the write-side
    scale tool. `items` is a list of `{id, object?, domain?, role?, …}`. Per item:
    an omitted axis is left unchanged, a value SETS it, explicit `null` CLEARS it.
    Atomic; terse receipt `{ok, count, unchanged, resulting_sha256}`."""
    return _write("declarations", "annotate_many", {"items": items, "force": force})


@mcp.tool(title='Annotate by filter',
          annotations=ToolAnnotations(title='Annotate by filter', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def annotate_by_filter(filter: dict, tags: dict, dry_run: bool = False,
                       force: bool = False) -> WriteResult:
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


@mcp.tool(title='Set vocabulary',
          annotations=ToolAnnotations(title='Set vocabulary', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def set_vocab(vocab=None) -> WriteResult:
    """Adopt the DECLARATION controlled ontology vocab from a caller-owned config.
    `vocab` may be an inline object or a path; omit it to load the default
    tag_vocab.json from the store's data folder. Once set, `validate` REJECTS
    ontology values outside their field's list; cardinality stays a soft
    expectation surfaced by view('anomalies')."""
    source = vocab if vocab is not None else str(_store().vocab_path("declarations"))
    return _write("declarations", "set_vocab", {"vocab": source})


@mcp.tool(title='Link a claim',
          annotations=ToolAnnotations(title='Link a claim', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def link_claim(id: str, claim: str) -> WriteResult:
    """Link a declaration to a claim it witnesses (declarations.claims.witness_of).
    The claim must already exist (a dangling link is refused). If the claim is
    proved/deep and this decl is sorry_free, it becomes a live witness."""
    return _write("declarations", "link_claim", {"id": id, "claim": claim})


@mcp.tool(title='Unlink a claim',
          annotations=ToolAnnotations(title='Unlink a claim', readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
def unlink_claim(id: str, claim: str) -> WriteResult:
    """Remove a claim from a declaration's witness_of. If this was the last live
    witness of a proved/deep claim, the write is refused (the store invariant
    rolls it back) — a witness cannot be silently pulled from under a proved claim."""
    return _write("declarations", "unlink_claim", {"id": id, "claim": claim})


@mcp.tool(title='Add a citation',
          annotations=ToolAnnotations(title='Add a citation', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def add_citation(id: str, target: str) -> WriteResult:
    """Add a citation to a declaration (claims.citations)."""
    return _write("declarations", "add_citation", {"id": id, "target": target})


@mcp.tool(title='Set verification state',
          annotations=ToolAnnotations(title='Set verification state', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def set_verify(id: str, sorry_free: Optional[bool] = None, axioms=None) -> WriteResult:
    """Record the build-derived verification state on a declaration. Flipping
    sorry_free to false on the sole live witness of a proved/deep claim is refused
    (a broken proof cannot leave a proved claim standing)."""
    params: dict[str, Any] = {"id": id}
    if sorry_free is not None:
        params["sorry_free"] = sorry_free
    if axioms is not None:
        params["axioms"] = axioms
    return _write("declarations", "set_verify", params)


@mcp.tool(title='Reconcile the store',
          annotations=ToolAnnotations(title='Reconcile the store', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def reconcile(scanner_output, anchor: Optional[dict] = None) -> WriteResult:
    """Fold a fresh scan into the declarations collection, preserving curation.
    Matches scan decls to entries by fully-qualified name, updates locations, ADDS
    new decls as pending, and FLAGS vanished / phantom / resurrected names — never
    silently drops or guesses a rename. Returns a terse {ok, ..., drift} summary."""
    params: dict[str, Any] = {"scanner_output": scanner_output}
    if anchor is not None:
        params["anchor"] = anchor
    return _write("declarations", "reconcile", params)


# -- claim write tools --------------------------------------------------------

@mcp.tool(title='Add a claim',
          annotations=ToolAnnotations(title='Add a claim', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def claim_add(claim_id: str, statement: str, status: Optional[str] = None,
              object=None, domain=None, date: Optional[str] = None,
              reason: Optional[str] = None, from_claim: Optional[str] = None,
              to_claim: Optional[str] = None) -> WriteResult:
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


@mcp.tool(title='Seed claims',
          annotations=ToolAnnotations(title='Seed claims', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def claim_seed(items: list[dict], force: bool = False) -> WriteResult:
    """Bulk-add claims atomically. `items` is a list of claim_add-shaped dicts.
    Edges may reference sibling claims added in the SAME batch (the whole batch is
    one validated postcondition). Duplicate claim_id (in-batch or existing) is
    refused. Terse receipt {ok, count, resulting_sha256}."""
    return _write("claims", "seed_claims", {"items": items, "force": force})


@mcp.tool(title='Set claim status',
          annotations=ToolAnnotations(title='Set claim status', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def claim_set_status(claim_id: str, status: str, date: Optional[str] = None,
                     reason: Optional[str] = None) -> WriteResult:
    """Change a claim's status and APPEND {status, date} to its history (append-
    only provenance; downgrades are kept, never erased). proved/deep require a
    live declaration witness or the change is refused."""
    params: dict[str, Any] = {"claim_id": claim_id, "status": status}
    if date is not None:
        params["date"] = date
    if reason is not None:
        params["reason"] = reason
    return _write("claims", "set_status", params)


@mcp.tool(title='Set a claim edge',
          annotations=ToolAnnotations(title='Set a claim edge', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def claim_set_edge(claim_id: str, from_claim: Optional[str] = None,
                   to_claim: Optional[str] = None) -> WriteResult:
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


@mcp.tool(title='Drop a claim',
          annotations=ToolAnnotations(title='Drop a claim', readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
def claim_drop(claim_id: str, reason: str) -> WriteResult:
    """Remove a claim seeded in error (hard delete of the node/edge). For RETIRING
    a claim while keeping its history, use claim_set_status (e.g. a 'retracted'
    status) instead. Invariant-guarded: dropping a claim that declarations still
    witness, or that is an edge endpoint, is refused (unlink/repoint first).
    reason is required."""
    return _write("claims", "drop_claim", {"claim_id": claim_id, "reason": reason})


@mcp.tool(title='Annotate a claim',
          annotations=ToolAnnotations(title='Annotate a claim', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def claim_annotate(claim_id: str, object=None, domain=None) -> WriteResult:
    """Set the curated object/domain axes on a claim (reuses the declaration
    object/domain vocab; element-aware). Only provided axes change; [] clears."""
    params: dict[str, Any] = {"claim_id": claim_id}
    if object is not None:
        params["object"] = object
    if domain is not None:
        params["domain"] = domain
    return _write("claims", "annotate_claim", params)


@mcp.tool(title='Set claim vocabulary',
          annotations=ToolAnnotations(title='Set claim vocabulary', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def claim_set_vocab(vocab=None) -> WriteResult:
    """Adopt the CLAIMS controlled vocab (object/domain/status) from a caller-owned
    config. `vocab` may be inline or a path; omit it to load the default
    claims_vocab.json from the store's data folder. status extends its built-in
    floor (commitment/conj/corr/deep/proved); object/domain are vocab-governed."""
    source = vocab if vocab is not None else str(_store().vocab_path("claims"))
    return _write("claims", "set_vocab", {"vocab": source})


# -- deps write tools ---------------------------------------------------------

@mcp.tool(title='Import dependencies',
          annotations=ToolAnnotations(title='Import dependencies', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
def import_deps(edges) -> WriteResult:
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

@mcp.tool(title='Export the whole store',
          annotations=ToolAnnotations(title='Export the whole store', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def export_full(dest: str, head_root: Optional[str] = None) -> ExportResult:
    """Publish the COMPLETE validated store (all collections) as a deterministic
    artifact to `dest`, for the caller to commit with git. Refuses to export an
    invalid or drifted store. Returns {ok, dest, entries, export_sha256,
    source_sha256}.

    Pass `head_root` (the Lean source root) to also run the cheap HEAD-path check
    and include a `head_check` summary in the receipt, so an export can never
    SILENTLY publish a dead path (interop #17). It is a warning, not a gate — the
    export still happens; `head_check.matches` tells you whether what you just
    published still matches the source tree, and the top-level `ok` does NOT --
    it is the CALL axis and stays true for a successful export that found drift.
    `head_check` does NOT carry an `ok`: the finding is `matches`, and the only
    `ok` in the response is the top-level call status. They meant different things
    one nesting level apart, which is the collision this removal ends.

    `head_check.describes_exported_bytes` says whether the check actually saw the
    bytes that were published. The check reads the source, then the export reads
    the source again and writes; this store has no locking, so a concurrent write
    in between yields an artifact the check never examined. False means the
    head-check result is about different bytes than the artifact -- treat it as
    unchecked and re-run, not as a pass.

    ⚠ A BAD `head_root` REFUSES THE WHOLE CALL AND WRITES NOTHING. It is a
    malformed argument, not a finding: "the check could not run" reported as a
    failed check is the same true-value-wrong-object collapse this tool exists
    to avoid, and a silent SUCCESS over an artifact whose correspondence was
    never actually checked is worse than a refusal, because nothing downstream
    can distinguish it from a checked one."""
    try:
        # ⛔⛔ `head_root` IS VALIDATED **BEFORE** THE EXPORT, AND THE ORDER IS THE WHOLE POINT.
        # Caught 2026-09-10 while fixing check_head's bad-root collapse -- i.e. THIS DEFECT WAS
        # INTRODUCED BY THAT FIX and was absent before it. `head_correspondence` now RAISES on
        # a bad root, this function catches only ValidationError and IntegrityError, and the
        # export runs FIRST. So a typo'd `head_root` would have let the export SUCCEED and
        # write the artifact to disk, then escaped as an unhandled raise -- which FastMCP
        # rewrites to "Error executing tool export_full: <msg>" with error_type `unhandled` and
        # a body that is no longer JSON. The caller would read a protocol error and believe the
        # export failed, while the file was sitting in `dest`. A FALSE FAILURE on a completed
        # write is the direction that does not get re-run and discovered.
        #
        # ⚠ REFUSING UP FRONT RATHER THAN DEMOTING THE CHECK TO A WARNING IS DELIBERATE. The
        # docstring's "warning, not a gate" is about DRIFT: a real finding must not block
        # publication. A malformed argument is not a finding, and reporting `head_check.ok:
        # false` for "the check could not run" would rebuild the exact value-on-the-wrong-object
        # collapse one layer up -- indistinguishable from "the check ran and found drift".
        # ⭐ Nothing is written, so the caller fixes the path and re-exports.
        st = _store()
        # ⭐⭐ THE HEAD CHECK RUNS **BEFORE** THE WRITE, WHICH MAKES THIS A PROPERTY RATHER THAN
        # A CLOSED ROUTE. Asked by the zptester session 2026-09-10, turning this fix's own
        # route-versus-property test back on it: validating `head_root` up front closes the
        # ROUTE I found (a typo'd root raising after the export), but it does not answer
        # whether ANY OTHER post-write failure can still escape over a completed write. It
        # could: `require_source_root` is a TOCTOU check, and `st.load()` re-reads the source
        # from disk and can raise if it moves underneath us. Both windows are narrow and both
        # land in the same bad place.
        #
        # ⭐ THE ORDER REMOVES THE QUESTION INSTEAD OF NARROWING IT. `head_correspondence` reads
        # the SOURCE store, not the artifact, and `export_full` does not mutate the source --
        # `engine.py` records the export with `resulting_sha256=source_sha`, the UNCHANGED hash.
        # So the check is worth exactly the same before the write as after it, and running it
        # first means NOTHING that can raise executes after `atomic_write_bytes`. The caller can
        # no longer be told the export failed while the file sits in `dest`, by any entrance.
        head_check = None
        pre_source_sha = None
        if head_root is not None:
            # ⚠ THE SOURCE HASH IS TAKEN BEFORE THE CHECK SO THE TWO CAN BE COMPARED LATER.
            # See `describes_exported_bytes` below -- this is the first of two INDEPENDENT
            # reads of the same value, which is the only shape that catches the window.
            pre_source_sha = _store_bytes.hash_file(st.data_path)
            head_check = head_correspondence(st.load(), root=head_root, tier="paths")
            # Captured BEFORE the key is dropped below; `head_correspondence`'s own `ok` is the
            # FINDING axis and is republished under its fleet-consistent name, `matches`.
            report_matches = head_check.get("ok")
        result = {"ok": True, **st.export_full(dest)}
        if head_check is not None:
            # ⚠ `matches` IS PUBLISHED BESIDE `ok`, AND THE DUPLICATION IS DELIBERATE AND
            # TEMPORARY. This embeds `head_correspondence`'s RAW report, whose `ok` is the
            # FINDING axis, inside a response whose top-level `ok` is the CALL axis -- one key
            # carrying two axes, one nesting level apart, in a single JSON body. That is the
            # same shape as the cd1c10e defect, surviving where nobody looked for it, and it
            # was found by the zptester session ASKING whether the defect had been removed or
            # merely relocated inward. It had been relocated.
            # ⛔ NOT RENAMED OUTRIGHT: a consumer branching on `head_check.ok` would get a
            # MISSING key, which is falsy, which reads as DRIFT -- a silent wrong answer in the
            # alarming direction. `matches` is the fleet-consistent name that `check_head`
            # already publishes; `ok` stays until the consumer has moved. Client first.
            # ⛔⛔ THE REORDER CLOSED A DIFFERENT PROPERTY THAN IT SOUNDS LIKE IT CLOSED, and
            # this field is what keeps the difference from being inferred wrongly. Raised by
            # the zptester session 2026-09-10, who explicitly did NOT claim it was introduced
            # here -- it existed in BOTH orderings and the point was that "validated before the
            # write" READS as though it were closed.
            #
            # What the reorder guarantees: nothing that can raise runs after `atomic_write_bytes`.
            # What it does NOT guarantee: that the check describes the bytes actually exported.
            # `head_correspondence` reads the source, then `export_full` reads the source AGAIN
            # and writes. A source mutation in between leaves an artifact the check never saw.
            #
            # ⚠ AND THE WINDOW IS REACHABLE, NOT THEORETICAL. There is no locking anywhere in
            # `core/engine.py` or `core/store.py` -- this store is not single-writer by
            # construction, and background agents write to this checkout concurrently, which is
            # the same premise `gitRobot.stage` refuses bulk adds over.
            #
            # ⭐ SO IT IS MEASURED ON BOTH SIDES AND THE DISAGREEMENT IS THE SIGNAL, which is
            # the house rule for a value that crosses layers. `pre_source_sha` is hashed here
            # before the check; `source_sha256` is computed by `export_full` from the bytes it
            # actually exported. Equal means the check describes the artifact. Unequal means it
            # does not, and the caller is TOLD so rather than left to assume -- because a check
            # that silently failed to describe the artifact is indistinguishable from one that
            # passed, and that is the whole defect class this fleet exists to remove.
            # ⛔⛔ THE INNER `ok` IS REMOVED, NOT ALIASED, AND THE REASON IS THE COLLISION --
            # not consumer migration, which was already complete. Settled 2026-09-10 after the
            # zptester session pointed out that the measurement had stopped governing:
            #
            #   MEASURED  grep over BOTH repos -> ZERO tracked files reference `head_check`,
            #             ZERO code branches on it. Every hit is prose in gitignored notes.
            #             So the stated termination condition was ALREADY MET, and keeping the
            #             key on that condition meant publishing a measurable rule that did
            #             not decide anything -- correct, re-runnable, and decorative.
            #   THE REAL  a pinning test can tie the inner `ok` to `matches`, but it CANNOT tie
            #   REASON    the inner `ok` to the OUTER `ok`, because those genuinely mean
            #             different things: call axis outside, finding axis inside, one nesting
            #             level apart, in one body. The collision ends exactly when the inner
            #             `ok` ends and not one commit sooner.
            #
            # ⚠ THE ARGUMENT FOR KEEPING IT WAS THAT AGENT READERS HAD CITED `head_check.ok` IN
            # PROSE. That protects the class of reader LEAST able to be harmed: an agent meeting
            # a missing key re-reads the docstring, which documents `matches`; it does not hold
            # a stale expectation the way compiled code does. The compiled-consumer risk was the
            # serious one and it measured zero.
            head_check = {k: v for k, v in head_check.items() if k != "ok"}
            head_check["matches"] = report_matches
            head_check["describes_exported_bytes"] = (
                pre_source_sha == result.get("source_sha256"))
            result["head_check"] = head_check
        return result
    except OperationError as exc:
        refusal = {"ok": False, "error_type": OperationError.error_type, "error": str(exc)}
        satisfied_when = getattr(exc, "satisfied_when", None)
        if satisfied_when:
            refusal["satisfied_when"] = satisfied_when
        return refusal
    except ValidationError as exc:
        return _validation_result(exc)
    except IntegrityError as exc:
        return {"ok": False, "error_type": IntegrityError.error_type, "error": str(exc)}


@mcp.tool(title='Migrate the store in batch',
          annotations=ToolAnnotations(title='Migrate the store in batch', readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def migrate_batch(source: Optional[str] = None, reconcile: Optional[list[dict]] = None,
                  add_new: Optional[list[dict]] = None, deps=None,
                  remap_deps: bool = False, anchor: Optional[dict] = None,
                  reason: Optional[str] = None) -> WriteResult:
    """Bulk declaration IDENTITY migration (interop #14) — the one atomic op that
    transitions declarations to their HEAD identity AND fixes the deps coupling in
    a single transaction (so a rename is not blocked by the deps reference gate).

    `source` is a path to (or inline copy of) the ZP `sjv_reconcile_import` file;
    its `reconcile`/`add_new`/`anchor` are used as defaults (explicit params
    override). `reconcile` = id-keyed transitions [{id, new_qualified, new_file,
    new_namespace, new_short, disposition, reason?}] — sets new.* + disposition on
    the existing entry, PRESERVING old/ontology/claims/verify. `add_new` = new HEAD
    decls [{qualified, file, namespace, short}] added as fresh 'new' entries.

    Deps: pass `deps` (a fresh {from,to,kind?} list or path at the NEW names) to
    REPLACE the deps collection, OR `remap_deps=true` to rewrite the EXISTING deps
    endpoints old→new from this batch's rename map. Atomic: any violation (missing
    id, dangling dep, broken witness) rolls the WHOLE batch back. Terse receipt
    {ok, reconciled, added, deps, resulting_sha256}."""
    params: dict[str, Any] = {"remap_deps": remap_deps}
    if source is not None:
        params["source"] = source
    if reconcile is not None:
        params["reconcile"] = reconcile
    if add_new is not None:
        params["add_new"] = add_new
    if deps is not None:
        params["deps"] = deps
    if anchor is not None:
        params["anchor"] = anchor
    if reason is not None:
        params["reason"] = reason
    return _write_store("migrate_batch", params)


@mcp.tool(title='Apply a collection op',
          annotations=ToolAnnotations(title='Apply a collection op', readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def apply(op: str, params: dict, collection: str = "declarations") -> WriteResult:
    """LAST RESORT. Runs a registered write op on a collection with a raw params dict.

    ⛔ PREFER THE DEDICATED TOOL. Almost every op here also has its own tool — add_new,
    annotate, drop, merge, move, rename, split and the rest — and those carry a real
    inputSchema, so the shape of what you are sending is checked before it arrives. This one
    takes `params: dict` and checks nothing until the store does. Reach for it only when no
    dedicated tool covers the op.

    ⚠ DO NOT GUESS AT `op`. The set is a RUNTIME registry, so it is deliberately not listed
    here — a list in this docstring would be a second copy that drifts the moment an op is
    added. Discover it instead: an unknown op is REFUSED with the complete set named in the
    message ("Unknown operation 'x'. Known: ..."), which is a cheap, always-current probe.

    ⚠ `params` is op-specific and validated by the op, not by this signature. A bad shape
    surfaces as error_type 'validation' with the violations listed, never as a partial write:
    the op runs on an isolated deep copy and the store is only replaced if the whole result
    validates.

    This is a WRITE into a validated store — destructiveHint is set for that reason."""
    return _write(collection, op, params)


@mcp.tool(title='Apply a store-level op',
          annotations=ToolAnnotations(title='Apply a store-level op', readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False))
def apply_store(op: str, params: dict) -> WriteResult:
    """LAST RESORT, STORE-WIDE. A cross-collection op — e.g. op='migrate_batch'.

    The op receives the WHOLE store and is validated across every collection as one atomic
    transaction: either all collections end valid or nothing is written. That is the
    difference from `apply`, which is scoped to one collection.

    ⛔ The blast radius is every collection, so prefer `apply` when the change is confined to
    one, and prefer the dedicated tool over either.

    ⚠ DO NOT GUESS AT `op`. The store-level set is a runtime registry and is deliberately not
    listed here — an unknown op is refused with the complete set named in the message, which
    cannot go stale the way a list in this docstring would.

    This is a WRITE into a validated store — destructiveHint is set for that reason."""
    return _write_store(op, params)



# ── RESOURCES ─────────────────────────────────────────────────────────────────
# ⭐⭐ THE THIRD CHANNEL, AND UNTIL 2026-09-08 THIS SERVER USED NONE OF IT.
#
# An outside cold-read audit registered all seven servers to a fresh instance and found that
# THREE channels teach a caller how to use a server — server-level `instructions`, MCP
# resources, and tool docstrings — and NO SERVER USED MORE THAN ONE. Worse, every server
# ADVERTISED a `resources` capability (FastMCP does it by default) and served an empty list:
# an untrue contract of exactly the class `CLAUDE.md` now forbids, sitting one layer above
# every check in the conformance suite.
#
# ⚠ THE README WAS ALREADY THE BEST DOCUMENT IN THE PROJECT AND THE SERVER DID NOT SERVE IT.
# The auditor read it only because it called github.get_file_contents out of curiosity. A
# document a caller must find by another route is a document most callers never find — the
# same argument `verdictLedger/client/record.py` exists to warn about, one level up.
#
# ⛔ THIS IS A DOCUMENT, NOT A VOCABULARY. `CLAUDE.md`'s resource contract requires a
# vocabulary resource to be GENERATED from the constants the code imports, and forbids
# publishing one before the vocabularies are consolidated into `mcpcommon`. Serving a README
# publishes no value set, so it does not jump that queue. The dictionary is still owed.
@mcp.resource(
    "docs://sjv/readme",
    name="sjv README",
    title="structured-json-validator - the validated JSON store",
    description=("Collections, schema validation, content addressing, integrity verification and history. Served from the repository so a caller never has to find it by "
                 "another route."),
    mime_type="text/markdown",
)
def _readme() -> str:
    path = Path(__file__).resolve().parents[1] / "README.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        # ⚠ An unreadable doc renders as ITS OWN STATE, never as an empty document. A blank
        # resource reads as "this server has nothing to say", which is a different claim.
        return "README could not be read at %s: %s" % (path, exc)


@mcp.resource(
    "docs://sjv/vocabulary",
    name="fleet vocabulary",
    title="error_type, decision, row_status and exit_code - what every value MEANS",
    description=("The shared vocabularies every server on this fleet answers with, rendered "
                 "from the constants the code imports. An enum publishes the values; this "
                 "publishes what they mean and when each is the honest answer."),
    mime_type="text/markdown",
)
def _vocabulary() -> str:
    """GENERATED from mcpcommon.vocabulary, never transcribed.

    THE DUPLICATION THIS RETIRES. Measured 2026-09-08: `error_type` was defined in two
    errors.py files sharing only `usage`, while mcpcommon/iserror.py read the field on every
    refusal and owned none of it. Row statuses were string literals at each assignment site
    with no list anywhere - UNVALIDATED had shipped the day before and appeared in no
    enumeration, so a caller could not know it might arrive. And in the consumer's tree ONE
    named exit constant stood against 19 bare sys.exit() and 120 bare returns, which is how
    exit 3 acquired three incompatible meanings and how one brief came to carry 27 assertions
    about tooling behaviour that produced four bedrock findings in a single evening.

    Tim, 2026-09-08: "the standard and the definitions themselves are under the control of the
    mcp instance, and the zeroparadox framework is strictly a consumer" - and on the prose
    those consumers were maintaining by hand, "definitely kill off all of the duplication."

    ANY DOCUMENT THAT RESTATES THIS IS THE COPY THAT WILL BE WRONG. Point at this URI.
    """
    import sys
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from mcpcommon.vocabulary import render_markdown
    return render_markdown()


def main() -> None:
    # ⚠ NOT `mcp.run(transport="streamable-http")`. That builds the Starlette app and
    # starts uvicorn in one call with no seam to install middleware; `serve` does the
    # same two steps with the HTTP call log wrapped around the app. Behaviour with
    # ZPLOG_ENABLED=0 is identical to the old line.
    _serve_with_call_log(mcp, "sjv")


if __name__ == "__main__":
    main()
