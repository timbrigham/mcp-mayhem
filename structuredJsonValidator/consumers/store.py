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

import re
from pathlib import Path

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
from consumers.lean.operations import (
    _effective_qualified,
    _ensure_old_identity,
    _load_json_input,
    _mint_id,
    _synthetic_old,
    _sync_counts,
    namespace_of,
    short_of,
)
from consumers.lean import rules as decl_rules
from consumers.lean import views as decl_views
from consumers.deps.operations import _edge_entry
from core.engine import CollectionSpec, Store
from core.errors import OperationError
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


# =============================================================================
# HEAD correspondence (interop issue #16b / #17) ------------------------------
# =============================================================================
#
# `validate` checks that the store is internally well-formed. It cannot check
# that the store still describes REALITY — and a registry whose whole job is to
# track a Lean source tree can drift from HEAD while every internal gate stays
# green. Three separate incidents shipped that way: entries naming a declaration
# that no longer exists, and then entries naming a FILE that no longer exists.
#
# This is deliberately NOT a validate rule. `validate` is a pure function of the
# store document — it must stay deterministic, filesystem-free, and runnable on
# an export. HEAD correspondence needs a working tree to compare against, so it
# is a separate read-only report the consumer runs (ideally pre-export).

_DECL_KEYWORDS = ("theorem", "lemma", "def", "abbrev", "instance",
                  "structure", "class", "inductive")
_DECL_RE = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*"
    r"(?:(?:private|protected|noncomputable|partial|unsafe|scoped|local|nonrec)\s+)*"
    r"(?:" + "|".join(_DECL_KEYWORDS) + r")\s+"
    r"([^\s({\[:⦃⟨]+)",
    re.MULTILINE,
)
_BLOCK_COMMENT_RE = re.compile(r"/-.*?-/", re.DOTALL)
_LINE_COMMENT_RE = re.compile("--[^" + chr(10) + "]*")


def _declared_names(text: str) -> set:
    """Short names declared in one Lean file.

    Comments are stripped FIRST: not doing so is the exact bug the ZP trust-root
    check caught (prose lines beginning "theorem …" became phantom declarations).
    Returns both the raw captured token and its last dotted segment, so a decl
    written as ``ZPSemilattice.bot_le`` inside a namespace matches an entry whose
    short name is ``bot_le``.
    """
    text = _BLOCK_COMMENT_RE.sub(" ", text)
    text = _LINE_COMMENT_RE.sub(" ", text)
    names = set()
    for token in _DECL_RE.findall(text):
        names.add(token)
        names.add(token.rsplit(".", 1)[-1])
    return names


def head_correspondence(store_doc: dict, *, root=".", tier: str = "paths",
                        limit: int = 25) -> dict:
    """Report where the declarations collection has drifted from the source tree.

    Two tiers, cheapest first (interop #17's scoping):

      * ``paths`` — every live entry's ``new.file`` resolves on disk. A stat call
        per entry, no Lean parsing, zero tuning. This is the tier that catches a
        reverted file: the whole declaration set points at a path that is gone.
      * ``names`` — additionally, each live entry's short name is actually
        declared in that file. Strictly stronger, and the tier that catches the
        other observed shape (a live FILE with a dead NAME, from a theorem split).
        Heuristic by nature — it reads the source, it does not elaborate it — so
        a miss is reported as drift to investigate, not as a proof of absence.

    Only entries expected to still exist are checked (``dropped``/``merged``/
    ``split`` sources name something that is *supposed* to be gone), and only
    those carrying a HEAD identity — a still-``pending`` entry's ``old.file`` is
    an anchor-era path and is stale by design.

    Also reports duplicate live names. Those are a hard ``validate`` violation
    now; surfacing them here lets a store be AUDITED before the stricter rules
    are adopted, which matters because a store already holding duplicates cannot
    be written to until they are repaired (one ``remove`` call).

    Read-only, terse (counts + a bounded sample, per issue #6).
    """
    if tier not in ("paths", "names"):
        raise OperationError(f"tier must be 'paths' or 'names', got {tier!r}")
    root = Path(root)
    entries = (store_doc.get("collections", {}).get("declarations", {})
               .get("entries", []))

    checked = 0
    missing_files: list[dict] = []
    missing_names: list[dict] = []
    by_file: dict = {}
    seen_names: dict = {}
    duplicates: list[dict] = []
    file_cache: dict = {}

    for entry in entries:
        group, qualified, present = _effective_qualified(entry)
        if not qualified or not present:
            continue
        if qualified in seen_names:
            duplicates.append({"qualified": qualified, "ids": [seen_names[qualified],
                                                               entry.get("id")]})
        else:
            seen_names[qualified] = entry.get("id")
        if group != "new":
            continue  # still at its anchor identity; nothing to check against HEAD
        rel = (entry.get("new") or {}).get("file")
        if not rel:
            continue
        checked += 1
        path = root / rel
        if not path.exists():
            missing_files.append({"id": entry.get("id"), "qualified": qualified, "file": rel})
            by_file[rel] = by_file.get(rel, 0) + 1
            continue
        if tier == "names":
            if rel not in file_cache:
                try:
                    file_cache[rel] = _declared_names(path.read_text(encoding="utf-8"))
                except OSError:
                    file_cache[rel] = None
            declared = file_cache[rel]
            if declared is None:
                continue
            short = (entry.get("new") or {}).get("short") or qualified.rsplit(".", 1)[-1]
            if short not in declared and qualified not in declared:
                missing_names.append({"id": entry.get("id"), "qualified": qualified,
                                      "file": rel})

    report = {
        "tier": tier,
        "root": str(root),
        "checked": checked,
        "resolved": checked - len(missing_files),
        "unresolvable_files": len(missing_files),
        "duplicate_live_names": len(duplicates),
        "ok": not missing_files and not duplicates and not missing_names,
        "missing_files": missing_files[:limit],
        "missing_files_by_file": dict(sorted(by_file.items())),
        "duplicates": duplicates[:limit],
    }
    if tier == "names":
        report["undeclared_names"] = len(missing_names)
        report["undeclared"] = missing_names[:limit]
    return report


# =============================================================================
# Store-level (cross-collection) operations (interop issue #14) ----------------
# =============================================================================

_MIGRATE_NEW_LEAVES = ("qualified", "short", "file", "namespace")


def _apply_reconcile_item(entry: dict, item: dict, *, default_reason) -> tuple:
    """Transition ONE existing declaration entry to its HEAD identity in place.

    Sets ``new.{qualified,short,file,namespace}`` and ``disposition`` on the
    id-matched entry; PRESERVES ``old``, ``ontology``, ``claims`` and ``verify``
    untouched (the whole point — a re-import would orphan that curation).

    Returns ``(deps_remap_source_name, changed)``.

    The remap source is the entry's CURRENT EFFECTIVE name — ``new.qualified``
    when populated, else ``old.qualified`` — not its frozen anchor name (interop
    #15b). Live deps edges key on whatever the declaration is called NOW, so
    remapping from ``old.qualified`` silently matched nothing whenever an
    already-``present``/reconciled entry was renamed again, and every edge on it
    dangled the moment the rename landed. An explicit ``old_qualified`` on the
    item overrides (the import may already carry the current effective name).

    A born-at-HEAD target is backfilled with its synthetic ``old`` first
    (interop #15a), so a reconcile item may retarget an ``add_new`` entry — which
    the original op refused outright.
    """
    nq = item.get("new_qualified")
    if not nq:
        raise OperationError(f"reconcile item for id {item.get('id')!r} needs new_qualified")
    disposition = item.get("disposition")
    if not disposition:
        raise OperationError(f"reconcile item for id {item.get('id')!r} needs a disposition")

    _, current_q, _ = _effective_qualified(entry)
    remap_from = item.get("old_qualified") or current_q
    _ensure_old_identity(entry)

    before = (dict(entry.get("new") or {}), entry.get("disposition"))
    entry["new"] = {
        "qualified": nq,
        "short": item.get("new_short") or short_of(nq),
        "file": item.get("new_file"),
        "namespace": item.get("new_namespace") if item.get("new_namespace") is not None
        else namespace_of(nq),
    }
    entry["disposition"] = disposition
    reason = item.get("reason", default_reason)
    if reason is not None:
        entry["reason"] = reason
    changed = before != (entry["new"], entry["disposition"])
    return remap_from, changed


def _new_head_entry(item: dict, *, default_reason) -> dict:
    """Build a fresh ``new`` (old.* null) declaration entry for a genuinely-new
    HEAD decl (interop #14 ``add_new``). Disposition is ``new`` — the structurally
    valid representation of a decl with no anchor identity (``pending`` requires
    ``old.qualified`` set, which a brand-new decl does not have)."""
    nq = item.get("qualified")
    if not nq:
        raise OperationError("add_new item needs a qualified name")
    new_group = {
        "qualified": nq,
        "short": item.get("short") or short_of(nq),
        "file": item.get("file"),
        "namespace": item.get("namespace") if item.get("namespace") is not None
        else namespace_of(nq),
    }
    return {
        "id": _mint_id(),
        # Birth identity recorded as a synthetic old, exactly as add_new does
        # (interop #16a) — otherwise a bulk migration keeps minting entries that
        # can never afterwards be renamed, merged, split or retired.
        "old": _synthetic_old(new_group, kind=item.get("kind")),
        "new": new_group,
        "disposition": "new",
        "reason": item.get("reason", default_reason) or "ontology-revamp: new HEAD declaration",
        "ontology": {"object": [], "domain": [], "role": []},
        "claims": {"witness_of": list(item.get("witness_of", [])),
                   "citations": list(item.get("citations", []))},
        "verify": {"sorry_free": bool(item.get("sorry_free", True)), "axioms": item.get("axioms")},
    }


def _replace_deps(deps_doc: dict, edges) -> tuple[int, int, int]:
    """Whole-collection REPLACE of the deps edge set (same semantics as
    ``import_deps``). Returns ``(replaced, imported, deduped)``."""
    raw = _load_json_input(edges, label="deps")
    if not isinstance(raw, list):
        raise OperationError(
            f"deps must be a list of {{from, to, kind?}} dicts or a path to one, "
            f"got {type(raw).__name__}"
        )
    old_count = len(deps_doc.get("entries", []))
    new_entries: list[dict] = []
    seen: set = set()
    deduped = 0
    for item in raw:
        if not isinstance(item, dict):
            raise OperationError("each dep edge must be an object")
        edge = _edge_entry(item)
        key = (edge["from"], edge["to"], edge["kind"])
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        new_entries.append(edge)
    deps_doc["entries"] = new_entries
    return old_count, len(new_entries), deduped


def _remap_deps(deps_doc: dict, name_map: dict) -> int:
    """Rewrite existing deps endpoints through an ``old_qualified -> new_qualified``
    map (an endpoint absent from the map is left as-is — e.g. a decl whose name did
    not change). Recomputes each edge's deterministic id and de-duplicates. Returns
    the number of edges whose ``from``/``to`` changed."""
    entries = deps_doc.get("entries", [])
    remapped = 0
    rebuilt: list[dict] = []
    seen: set = set()
    for edge in entries:
        new_from = name_map.get(edge.get("from"), edge.get("from"))
        new_to = name_map.get(edge.get("to"), edge.get("to"))
        if new_from != edge.get("from") or new_to != edge.get("to"):
            remapped += 1
        rebuilt_edge = _edge_entry({"from": new_from, "to": new_to, "kind": edge.get("kind")})
        key = (rebuilt_edge["from"], rebuilt_edge["to"], rebuilt_edge["kind"])
        if key in seen:
            continue
        seen.add(key)
        rebuilt.append(rebuilt_edge)
    deps_doc["entries"] = rebuilt
    return remapped


def migrate_batch(store_doc, *, source=None, reconcile=None, add_new=None,
                  deps=None, remap_deps: bool = False, anchor=None,
                  reason=None) -> tuple[dict, list[str], dict]:
    """Bulk declaration identity migration (interop issue #14).

    The successor to Issue 9 (bulk annotate) and Issue 13 (bulk deps replace): a
    bulk IDENTITY migration that transitions each existing declaration to its
    current HEAD identity WITHOUT dropping curation, and resolves the deps
    coupling in the SAME atomic transaction. It is a store-level op (it touches
    both ``declarations`` and ``deps``), so a rename that would otherwise be
    blocked by the Issue-13 deps reference gate lands together with the matching
    deps update — no intermediate dangling state.

    Inputs (all optional; supply what applies):
      * ``source`` — a path to (or inline copy of) ZP's ``sjv_reconcile_import``
        file; its ``reconcile`` / ``add_new`` / ``anchor`` are used as defaults.
        Explicit ``reconcile`` / ``add_new`` / ``anchor`` params override it. This
        keeps the founding call tiny for a ~370 KB import.
      * ``reconcile`` — id-keyed transitions ``[{id, new_qualified, new_file,
        new_namespace, new_short, disposition, reason?}]``. Each sets ``new.*`` +
        ``disposition`` on the existing entry (id matched), PRESERVING ``old`` /
        ``ontology`` / ``claims`` / ``verify``. Missing id → error; duplicate id in
        the batch → error (whole batch rolls back — atomic, per #6/#9).
      * ``add_new`` — genuinely-new HEAD decls ``[{qualified, file, namespace,
        short, kind?}]`` added as fresh ``new`` entries (``old.*`` null).
      * ``deps`` — a fresh edge set (list or path) whose endpoints are the NEW
        qualified names → whole-collection REPLACE of ``deps`` (derived data).
      * ``remap_deps`` — instead of a fresh set, rewrite the EXISTING deps
        endpoints old→new using this batch's rename map (convenient when the
        current edges reference the pre-migration names). Ignored if ``deps`` is
        given. If neither is set the deps collection is left as-is (the reference
        gate will then reject the whole batch if any edge now dangles — the safe
        default).
      * ``anchor`` — update the declarations anchor to the migrated commit.

    Atomicity is the store postcondition: the whole store (schema + per-collection
    rules + the witness invariant + the deps reference gate) is validated after
    the op; ANY violation rolls the entire batch back (M4). Returns a terse
    receipt — no per-entry echo.
    """
    if source is not None:
        loaded = _load_json_input(source, label="source")
        if not isinstance(loaded, dict):
            raise OperationError("source must be an object (or a path to one)")
        if reconcile is None:
            reconcile = loaded.get("reconcile")
        if add_new is None:
            add_new = loaded.get("add_new")
        if anchor is None:
            anchor = loaded.get("anchor")

    reconcile = reconcile or []
    add_new = add_new or []
    if not isinstance(reconcile, list) or not isinstance(add_new, list):
        raise OperationError("reconcile and add_new must be lists")
    if not reconcile and not add_new:
        raise OperationError("migrate_batch needs a non-empty reconcile or add_new list")

    colls = store_doc.setdefault("collections", {})
    decl_doc = colls.setdefault("declarations", _declarations_empty_doc())
    entries = decl_doc.setdefault("entries", [])
    index = {e.get("id"): e for e in entries}

    touched: list[str] = []
    reconciled_ids: list[str] = []
    unchanged = 0
    name_map: dict[str, str] = {}

    # (1) id-keyed identity transitions (curation preserved).
    seen_ids: set = set()
    for i, item in enumerate(reconcile):
        if not isinstance(item, dict) or "id" not in item:
            raise OperationError(f"reconcile[{i}] must be an object with an 'id'")
        eid = item["id"]
        if eid in seen_ids:
            raise OperationError(f"duplicate id {eid!r} in reconcile (ambiguous)")
        seen_ids.add(eid)
        entry = index.get(eid)
        if entry is None:
            raise OperationError(f"no declaration with id {eid!r} to migrate")
        remap_from, changed = _apply_reconcile_item(entry, item, default_reason=reason)
        if remap_from and remap_from != item["new_qualified"]:
            name_map[remap_from] = item["new_qualified"]
        reconciled_ids.append(eid)
        if changed:
            touched.append(eid)
        else:
            # Already at the requested identity. A partial migration is sticky
            # (rename is one-way), so re-applying the same import file must be a
            # NO-OP, not a batch-failing error (ZP-side finding, 2026-07-06).
            unchanged += 1

    # (2) genuinely-new HEAD declarations.
    added = 0
    for item in add_new:
        if not isinstance(item, dict):
            raise OperationError("each add_new item must be an object")
        new_entry = _new_head_entry(item, default_reason=reason)
        entries.append(new_entry)
        touched.append(new_entry["id"])
        added += 1

    _sync_counts(decl_doc)
    if anchor is not None:
        decl_doc["anchor"] = {"branch": anchor.get("branch"), "commit": anchor.get("commit"),
                              "tree": anchor.get("tree")}

    # (3) resolve the deps coupling in the same transaction.
    deps_doc = colls.setdefault("deps", deps_pkg.empty_doc())
    extra: dict = {"reconciled": len(reconciled_ids), "unchanged": unchanged,
                   "added": added}
    if deps is not None:
        replaced, imported, deduped = _replace_deps(deps_doc, deps)
        touched.extend(e["id"] for e in deps_doc.get("entries", []))
        extra["deps"] = {"mode": "replace", "replaced": replaced,
                         "imported": imported, "deduped": deduped}
    elif remap_deps:
        remapped = _remap_deps(deps_doc, name_map)
        touched.extend(e["id"] for e in deps_doc.get("entries", []))
        extra["deps"] = {"mode": "remap", "remapped": remapped,
                         "edges": len(deps_doc.get("entries", []))}

    return store_doc, touched, extra


STORE_OPERATIONS = {
    "migrate_batch": migrate_batch,
}


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
        store_operations=STORE_OPERATIONS,
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
