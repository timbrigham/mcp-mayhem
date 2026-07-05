"""Composition root for the multi-collection store (interop issue #12, Option B).

Wires the generic :class:`core.engine.Store` with two collections that share all
the same machinery but keep their own schema/rules/ops/views:

  * ``declarations`` — the existing 1012-decl registry, its sub-document shape
    UNCHANGED (so every declaration op and business rule is reused verbatim);
  * ``claims`` — the claim graph (nodes + edges as one shape).

Plus the KILLER cross-collection invariant (:func:`witness_invariant`): a
``proved``/``deep`` claim is valid ONLY if some declaration witnesses it with a
live (``sorry_free``) proof. It runs on EVERY write — a declaration write that
removes the last live witness fails the same store postcondition a bad claim
write would (interop #12 T4). Integrity is whole-store (one hash chain).
"""

from __future__ import annotations

from consumers import claims as claims_pkg
from consumers import deps as deps_pkg
from consumers import lean as lean_pkg
from consumers.claims import operations as claim_ops
from consumers.claims import rules as claim_rules
from consumers.claims import views as claim_views
from consumers.deps import operations as dep_ops
from consumers.deps import rules as dep_rules
from consumers.deps import views as dep_views
from consumers.lean import operations as decl_ops
from consumers.lean.operations import _effective_qualified
from consumers.lean import rules as decl_rules
from consumers.lean import views as decl_views
from core.engine import CollectionSpec, Store
from core.schema import load_schema


def _declarations_empty_doc() -> dict:
    """Pre-founding declarations sub-document (import_baseline REPLACES it)."""
    return {
        "schema_version": "1",
        "anchor": {"branch": None, "commit": None, "tree": None},
        "counts": {"files": 0, "declarations": 0},
        "entries": [],
    }


# Statuses that assert a live proof exists, and thus REQUIRE a witnessing
# declaration. conj / corr / commitment make no such claim and need no witness.
_LIVE_STATUSES = {"proved", "deep"}


def witness_invariant(store_doc: dict) -> list[str]:
    """The killer invariant (interop #12 T4), spanning both collections.

    A claim with ``status ∈ {proved, deep}`` is valid ONLY if ≥1 declaration has
    ``claims.witness_of`` containing that claim's ``claim_id`` AND
    ``verify.sorry_free == true``. Also flags a declaration whose ``witness_of``
    references a claim_id that does not exist (dangling link, T3). Witnesses are
    DERIVED here from the declaration side — never stored on the claim — so adding
    a witness never edits the claim (one source for the link).
    """
    colls = store_doc.get("collections") or {}
    decls = (colls.get("declarations") or {}).get("entries", [])
    claim_entries = (colls.get("claims") or {}).get("entries", [])
    claim_ids = {c.get("claim_id") for c in claim_entries if c.get("claim_id") is not None}

    live_witnessed: set[str] = set()
    out: list[str] = []
    for d in decls:
        sorry_free = bool((d.get("verify") or {}).get("sorry_free", False))
        for cid in (d.get("claims") or {}).get("witness_of") or []:
            if cid not in claim_ids:
                out.append(
                    f"[declarations] {d.get('id')!r}: claims.witness_of references "
                    f"unknown claim_id {cid!r} (dangling link)"
                )
            if sorry_free:
                live_witnessed.add(cid)

    for c in claim_entries:
        cid = c.get("claim_id")
        status = c.get("status")
        if status in _LIVE_STATUSES and cid not in live_witnessed:
            out.append(
                f"[claims] {cid!r}: status {status!r} requires ≥1 declaration with "
                f"claims.witness_of containing {cid!r} AND verify.sorry_free=true "
                f"(no live witness found)"
            )
    return out


def _declaration_endpoints(decls: list[dict]) -> set:
    """The set of effective-current qualified names a dependency edge may point at:
    the reconcile match-key (Decision B) for every declaration that is expected to
    still exist in source (pending/present/moved → old.qualified, renamed/new →
    new.qualified). Dropped/merged/split source names are GONE, so an edge onto one
    is dangling. Reuses ``_effective_qualified`` verbatim so deps and reconcile
    agree on identity."""
    valid: set = set()
    for entry in decls:
        _group, qualified, present = _effective_qualified(entry)
        if qualified and present:
            valid.add(qualified)
    return valid


def deps_reference_integrity(store_doc: dict) -> list[str]:
    """Cross-collection reference integrity for the ``deps`` graph (interop #13 D3).

    Every dependency edge's ``from`` and ``to`` must resolve to an effective-current
    declaration qualified; a dangling endpoint (a name no declaration currently
    carries) is a validation violation — surfaced, never silently kept. This is the
    ONLY store-level gate deps need (deps carry no epistemic status, so there is no
    witness invariant; acyclicity is deliberately NOT enforced)."""
    colls = store_doc.get("collections") or {}
    decls = (colls.get("declarations") or {}).get("entries", [])
    edges = (colls.get("deps") or {}).get("entries", [])
    if not edges:
        return []
    valid = _declaration_endpoints(decls)
    out: list[str] = []
    for edge in edges:
        for endpoint in ("from", "to"):
            ref = edge.get(endpoint)
            if ref is not None and ref not in valid:
                out.append(
                    f"[deps] {edge.get('id')!r}: {endpoint} references unknown "
                    f"declaration qualified {ref!r} (dangling edge)"
                )
    return out


def build_store(data_path, *, audit_path=None, actor: str = "cli") -> Store:
    """Wire the generic :class:`Store` with the declarations + claims + deps
    collections and the cross-collection invariants (witness + deps reference)."""
    declarations = CollectionSpec(
        schema=load_schema(lean_pkg.SCHEMA_PATH),
        business_validator=decl_rules.validate,
        operations=decl_ops.OPERATIONS,
        views=decl_views.VIEWS,
        empty_doc=_declarations_empty_doc,
        entries_key="entries",
        id_key="id",
    )
    claims = CollectionSpec(
        schema=load_schema(claims_pkg.SCHEMA_PATH),
        business_validator=claim_rules.validate,
        operations=claim_ops.OPERATIONS,
        views=claim_views.VIEWS,
        empty_doc=claims_pkg.empty_doc,
        entries_key="entries",
        id_key="id",
    )
    deps = CollectionSpec(
        schema=load_schema(deps_pkg.SCHEMA_PATH),
        business_validator=dep_rules.validate,
        operations=dep_ops.OPERATIONS,
        views=dep_views.VIEWS,
        empty_doc=deps_pkg.empty_doc,
        entries_key="entries",
        id_key="id",
    )
    return Store(
        data_path=data_path,
        collections={"declarations": declarations, "claims": claims, "deps": deps},
        cross_validators=[witness_invariant, deps_reference_integrity],
        audit_path=audit_path,
        actor=actor,
    )


def wrap_legacy(bare_declarations_doc: dict) -> dict:
    """Lift a legacy single-collection declarations document into the v2 store
    envelope (declarations = the bare doc verbatim, other collections = empty). The
    one-time migration for an existing registry; ZP re-seals the result."""
    return {
        "store_version": Store.STORE_VERSION,
        "collections": {
            "declarations": bare_declarations_doc,
            "claims": claims_pkg.empty_doc(),
            "deps": deps_pkg.empty_doc(),
        },
    }


def backfill_missing_collections(store_doc: dict) -> list[str]:
    """Add an empty sub-document for any store-configured collection absent from an
    existing v2 envelope (e.g. `deps`, introduced after the store was first
    migrated). PRESERVES every existing collection untouched. Returns the list of
    collection names that were added (empty if nothing was missing)."""
    empties = {"declarations": _declarations_empty_doc,
               "claims": claims_pkg.empty_doc, "deps": deps_pkg.empty_doc}
    colls = store_doc.setdefault("collections", {})
    added: list[str] = []
    for name, factory in empties.items():
        if name not in colls:
            colls[name] = factory()
            added.append(name)
    return added
