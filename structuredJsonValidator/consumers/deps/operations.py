"""Operations for the ``deps`` collection (interop issue #13).

Two verbs, both metadata-free directed edges:

  * ``import_deps`` — the primary path: a whole-collection REPLACE from a freshly
    extracted edge set (derived data, zero curation — a re-extract is total and
    authoritative, so unlike ``import_baseline`` there is no curation to protect).
  * ``add_dep`` — append a single edge (ergonomics / tests).

Both mint surrogate ids and rely on the store's cross-collection reference
validator (``consumers.store.deps_reference_integrity``) to reject a dangling
endpoint as the whole-store postcondition.
"""

from __future__ import annotations

import uuid
from typing import Optional, Union

from core.errors import OperationError

# deps use a DETERMINISTIC content-derived surrogate (uuid5), NOT random uuid4.
# Rationale: deps are DERIVED, whole-collection REPLACED on re-extract, and their
# ids are referenced by nothing (edges reference declaration `qualified`, not dep
# ids). A deterministic id makes a re-extract of the same source byte-identical —
# a true no-op on state, with clean export diffs — which is exactly the
# "reproducible-from-source id" fallback the Issue 5 Part 2 discussion flagged for
# derived data. Identity of an edge is its (from, to, kind) triple.
_DEP_NAMESPACE = uuid.UUID("d7e5a1c2-0000-4000-8000-00000000d135")


def _dep_id(frm: str, to: str, kind: Optional[str]) -> str:
    return str(uuid.uuid5(_DEP_NAMESPACE, f"{frm}\x1f{to}\x1f{kind}"))


def _require_doc(document: Optional[dict]) -> dict:
    if document is None:
        raise OperationError("no deps document exists yet")
    return document


def _resolve_edges(edges: Union[str, list]) -> list:
    """Edge set as an inline list of ``{from, to, kind?}`` or a path to a JSON
    file containing that list (the practical form at 5k–30k edges)."""
    from consumers.lean.operations import _load_json_input

    edges = _load_json_input(edges, label="edges")
    if not isinstance(edges, list):
        raise OperationError(
            f"edges must be a list of {{from, to, kind?}} dicts or a path to one, "
            f"got {type(edges).__name__}"
        )
    return edges


def _edge_entry(item: dict) -> dict:
    frm, to = item.get("from"), item.get("to")
    if not frm or not to:
        raise OperationError("each dep edge requires non-empty 'from' and 'to'")
    kind = item.get("kind")
    if kind not in ("type", "proof", None):
        raise OperationError(f"dep 'kind' must be 'type', 'proof', or null; got {kind!r}")
    return {"id": _dep_id(frm, to, kind), "from": frm, "to": to, "kind": kind}


def import_deps(document, *, edges: Union[str, list]) -> tuple[dict, list[str], dict]:
    """Whole-collection REPLACE from a freshly extracted edge set (interop #13).

    ``edges`` is an inline list of ``{from, to, kind?}`` or a path to a JSON file.
    This DISCARDS the current deps collection and writes the new set — the correct
    semantics for derived, zero-curation data (there is nothing to preserve). The
    ``import_baseline`` footgun (Issue 5) does not apply, but the receipt reports
    how many edges were replaced so the wholesale swap is visible/deliberate.

    Identical ``(from, to)`` edges are de-duplicated (a re-extract of the same
    source yields the same deduped set → a deterministic no-op on state). Endpoint
    reference integrity is enforced by the store postcondition (a dangling
    ``from``/``to`` fails validate → rollback). Returns
    ``(document, touched_ids, {replaced, imported, deduped})``.
    """
    doc = _require_doc(document)
    raw = _resolve_edges(edges)
    old_count = len(doc.get("entries", []))

    new_entries: list[dict] = []
    seen: set = set()
    deduped = 0
    for item in raw:
        if not isinstance(item, dict):
            raise OperationError("each dep edge must be an object")
        entry = _edge_entry(item)
        key = (entry["from"], entry["to"], entry["kind"])
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        new_entries.append(entry)

    doc["entries"] = new_entries
    touched = [e["id"] for e in new_entries]
    return doc, touched, {"replaced": old_count, "imported": len(new_entries), "deduped": deduped}


def add_dep(document, *, from_: str = None, to: str = None, kind: Optional[str] = None,
            **alias) -> tuple[dict, list[str]]:
    """Append a single dependency edge (ergonomics / tests). Endpoints reference
    the effective-current declaration qualified; the store postcondition rejects a
    dangling one. Accepts ``from``/``to`` (``from`` via ``**alias`` since it is a
    Python keyword) or ``from_``/``to``."""
    doc = _require_doc(document)
    frm = alias.get("from", from_)
    dst = alias.get("to", to)
    unknown = set(alias) - {"from", "to"}
    if unknown:
        raise OperationError(f"unexpected params for add_dep: {', '.join(sorted(unknown))}")
    entry = _edge_entry({"from": frm, "to": dst, "kind": kind})
    entries = doc.setdefault("entries", [])
    if any(e.get("id") == entry["id"] for e in entries):
        return doc, []  # identical edge already present — idempotent no-op
    entries.append(entry)
    return doc, [entry["id"]]


OPERATIONS = {
    "import_deps": import_deps,
    "add_dep": add_dep,
}
