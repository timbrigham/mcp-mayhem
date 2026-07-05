"""Operations (verbs) for the ``claims`` collection (interop issue #12).

Same engine contract as the declaration verbs: each op takes the collection's
sub-document, mutates a copy, and returns ``(document, touched_ids[, extra])``.
Surrogate ids are sjv-minted (Decision A), receipts are terse (#6), batch ops are
atomic (#9) — the whole-store postcondition in ``core.engine.Store`` re-validates
every write, including the cross-collection witness invariant, so nothing that
would break the graph is ever written.

Dates are DATA, not derived: the caller (ZP owns the claim provenance) passes the
``date`` a status was reached, keeping writes deterministic.
"""

from __future__ import annotations

import uuid
from typing import Optional

from core import query
from core.errors import OperationError


def _mint_id() -> str:
    """Opaque, permanent surrogate id (Decision A — same as the declaration side).
    Humans grep on ``claim_id``; the surrogate is only a stable handle."""
    return str(uuid.uuid4())


def _to_list(value) -> list:
    """Coerce an axis value to canonical list form: scalar -> [scalar], None/[]
    -> [] (unset), a list is kept (order preserved, deduped)."""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    seen, out = set(), []
    for v in value:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _require_doc(document: Optional[dict]) -> dict:
    if document is None:
        raise OperationError("no claims document exists yet")
    return document


def _find_by_claim_id(document: dict, claim_id: str) -> dict:
    for claim in document.get("entries", []):
        if claim.get("claim_id") == claim_id:
            return claim
    raise OperationError(f"no claim with claim_id {claim_id!r}")


def _build_claim(*, claim_id: str, statement: str, object=None, domain=None,
                 status: Optional[str] = None, from_=None, to=None,
                 date: Optional[str] = None, reason: Optional[str] = None,
                 id: Optional[str] = None) -> dict:
    if not claim_id or not isinstance(claim_id, str):
        raise OperationError("a claim requires a non-empty string claim_id")
    if statement is None:
        raise OperationError("a claim requires a statement")
    history = [{"status": status, "date": date}] if status is not None else []
    return {
        "id": id or _mint_id(),
        "claim_id": claim_id,
        "statement": statement,
        "object": _to_list(object),
        "domain": _to_list(domain),
        "status": status,
        "from": from_,
        "to": to,
        "date": date,
        "history": history,
        "reason": reason,
    }


# -- creation -----------------------------------------------------------------

def add_claim(document, *, claim_id: str, statement: str, object=None, domain=None,
              status: Optional[str] = None, date: Optional[str] = None,
              reason: Optional[str] = None, id: Optional[str] = None,
              **edge) -> tuple[dict, list[str]]:
    """Add one claim (a NODE, or an EDGE when ``from``/``to`` are given — one
    shape, no separate type). ``status`` seeds the ``history`` provenance. A
    duplicate ``claim_id`` is refused up front; enum + reference integrity are
    enforced by the store postcondition.

    ``from``/``to`` are accepted via ``**edge`` because ``from`` is a Python
    keyword; pass them as ``{"from": "...", "to": "..."}`` in params.
    """
    doc = _require_doc(document)
    for existing in doc.get("entries", []):
        if existing.get("claim_id") == claim_id:
            raise OperationError(f"claim_id {claim_id!r} already exists")
    unknown = set(edge) - {"from", "to"}
    if unknown:
        raise OperationError(f"unexpected params for add_claim: {', '.join(sorted(unknown))}")
    claim = _build_claim(
        claim_id=claim_id, statement=statement, object=object, domain=domain,
        status=status, from_=edge.get("from"), to=edge.get("to"), date=date,
        reason=reason, id=id,
    )
    doc.setdefault("entries", []).append(claim)
    return doc, [claim["id"]]


def seed_claims(document, *, items: list, force: bool = False) -> tuple[dict, list[str], dict]:
    """Bulk-add claims atomically (interop #6/#9 discipline). ``items`` is a list
    of ``add_claim``-shaped dicts (each ``{claim_id, statement, object?, domain?,
    status?, from?, to?, date?, reason?, id?}``). Duplicate ``claim_id`` within
    the batch or against the existing set is refused. Because the whole batch is
    validated as one store postcondition, edges may reference sibling claims added
    in the SAME batch. Terse receipt ``{count}``."""
    doc = _require_doc(document)
    if not isinstance(items, list) or not items:
        raise OperationError("seed_claims requires a non-empty list of items")
    existing = {c.get("claim_id") for c in doc.get("entries", [])}
    batch_ids: set = set()
    built: list[dict] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise OperationError(f"items[{i}] must be an object")
        cid = item.get("claim_id")
        if cid in existing:
            raise OperationError(f"items[{i}]: claim_id {cid!r} already exists")
        if cid in batch_ids:
            raise OperationError(f"items[{i}]: duplicate claim_id {cid!r} in batch")
        batch_ids.add(cid)
        params = dict(item)
        params["from_"] = params.pop("from", None)
        params["to"] = params.pop("to", None)
        built.append(_build_claim(**params))
    doc.setdefault("entries", []).extend(built)
    return doc, [c["id"] for c in built], {"count": len(built)}


# -- status transitions (provenance-preserving) -------------------------------

def set_status(document, *, claim_id: str, status: str, date: Optional[str] = None,
               reason: Optional[str] = None) -> tuple[dict, list[str]]:
    """Change a claim's ``status`` and APPEND ``{status, date}`` to its ``history``
    (interop #12 T5 — provenance is append-only; a downgrade such as
    proved→retracted is kept, never erased). Updates the top-level ``date`` (the
    date the current status was reached). The new value must clear the enum; if it
    is ``proved``/``deep`` the store's witness invariant must also be satisfied,
    else the write rolls back."""
    doc = _require_doc(document)
    claim = _find_by_claim_id(doc, claim_id)
    claim["status"] = status
    claim["date"] = date
    claim["history"].append({"status": status, "date": date})
    if reason is not None:
        claim["reason"] = reason
    return doc, [claim["id"]]


def set_edge(document, *, claim_id: str, **edge) -> tuple[dict, list[str]]:
    """Set (or clear with ``null``) the ``from``/``to`` endpoints on an existing
    claim, turning a node into an edge (or re-pointing one). Endpoints are
    reference-checked by the store postcondition. Pass endpoints as
    ``{"from": "...", "to": "..."}``."""
    doc = _require_doc(document)
    unknown = set(edge) - {"from", "to"}
    if unknown:
        raise OperationError(f"unexpected params for set_edge: {', '.join(sorted(unknown))}")
    if not edge:
        raise OperationError("set_edge needs at least one of from/to")
    claim = _find_by_claim_id(doc, claim_id)
    for endpoint in ("from", "to"):
        if endpoint in edge:
            claim[endpoint] = edge[endpoint]
    return doc, [claim["id"]]


# -- removal ------------------------------------------------------------------

def drop_claim(document, *, claim_id: str, reason: str) -> tuple[dict, list[str]]:
    """Remove a claim seeded in error (a hard delete of the node/edge). Distinct
    from a status downgrade — use ``set_status`` (e.g. to a 'retracted' status)
    when a claim is being RETIRED with its history kept; ``drop_claim`` is for a
    claim that should never have existed.

    Invariant-guarded by the store postcondition, so it is safe by construction:
    dropping a claim that declarations still witness leaves those ``witness_of``
    links dangling (validate fails → rollback), and dropping an edge endpoint
    leaves the edge's ``from``/``to`` dangling (also rolled back). Unlink the
    witnesses / repoint the edges first. ``reason`` is required (recorded in the
    audit log)."""
    doc = _require_doc(document)
    if not (isinstance(reason, str) and reason.strip()):
        raise OperationError("drop_claim requires a non-empty reason")
    entries = doc.get("entries", [])
    for i, claim in enumerate(entries):
        if claim.get("claim_id") == claim_id:
            removed = entries.pop(i)
            return doc, [removed["id"]]
    raise OperationError(f"no claim with claim_id {claim_id!r}")


# -- curation -----------------------------------------------------------------

def annotate_claim(document, *, claim_id: str, object=None, domain=None) -> tuple[dict, list[str]]:
    """Set the curated ``object``/``domain`` axes on a claim (only the provided
    ones; a value SETS as a list, ``[]``/``null`` CLEARS, omitted is unchanged).
    Reuses the declaration object/domain vocab (element-aware enum in rules)."""
    doc = _require_doc(document)
    claim = _find_by_claim_id(doc, claim_id)
    if object is not None:
        claim["object"] = _to_list(object)
    if domain is not None:
        claim["domain"] = _to_list(domain)
    return doc, [claim["id"]]


# -- vocab (shared mechanism with the declaration collection) -----------------

def set_vocab(document, *, vocab) -> tuple[dict, list[str]]:
    """Adopt the claims collection's controlled vocab (object/domain/status).
    Same config shape + semantics as the declaration ``set_vocab`` (interop #8):
    an inline object or a path, each field mapping to ``[values]`` or
    ``{values, cardinality?}``. ``status`` extends its built-in floor; object/
    domain are governed entirely by the vocab."""
    from consumers.lean.operations import set_vocab as _lean_set_vocab

    return _lean_set_vocab(document, vocab=vocab)


OPERATIONS = {
    "add_claim": add_claim,
    "seed_claims": seed_claims,
    "set_status": set_status,
    "set_edge": set_edge,
    "drop_claim": drop_claim,
    "annotate_claim": annotate_claim,
    "set_vocab": set_vocab,
}
