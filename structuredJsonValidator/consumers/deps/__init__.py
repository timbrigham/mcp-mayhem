"""The ``deps`` collection (interop issue #13): the declaration-level dependency
graph — which decl compiles-depends on which — that drives the eventual Lean
source refactor (import-safe moves, "what must move together"). A DERIVED,
zero-curation collection: every edge is extracted mechanically, so the update
path is a whole-collection REPLACE on re-extract (``import_deps``). Reference
integrity (endpoints resolve to real declarations) is enforced at the store level
(see :func:`consumers.store.deps_reference_integrity`)."""

from __future__ import annotations

from pathlib import Path

from consumers.deps import operations, rules, views

SCHEMA_PATH = Path(__file__).with_name("dep.schema.json")


def empty_doc() -> dict:
    """The empty deps sub-document (no anchor/counts — deps are derived edges)."""
    return {"schema_version": "1", "entries": []}
