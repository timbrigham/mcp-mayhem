"""Operations (verbs) for the Lean-declaration consumer (spec §9).

Contract for the engine: each operation takes the current document (or ``None``
when bootstrapping) plus typed params, mutates a copy, and returns
``(document, touched_ids)``. Operations never touch the file or the audit log —
the engine does that after the result passes full validation.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional, Union

from core import query
from core.errors import OperationError, ValidationError


# -- structure helpers --------------------------------------------------------

def _mint_id() -> str:
    """Mint an opaque, permanent surrogate id (interop issue #5, Decision A).

    ``id`` is a system-generated handle, NOT a natural key derived from
    ``file``/``qualified``/``line`` — those are mutable fields, not identity, so
    an entry's id never has to change (and never gets recomputed) when a
    declaration moves or is renamed. Humans grep on ``qualified`` (a field); the
    id is only a stable handle reconcile resolves matches to.
    """
    return str(uuid.uuid4())


def _empty_old() -> dict:
    return {"qualified": None, "short": None, "kind": None, "file": None, "line": None, "prefix": None}


def _empty_new() -> dict:
    return {"qualified": None, "short": None, "file": None, "namespace": None}


def short_of(qualified: str) -> str:
    return qualified.rsplit(".", 1)[-1]


def namespace_of(qualified: str) -> str:
    return qualified.rsplit(".", 1)[0] if "." in qualified else ""


def _require_doc(document: Optional[dict]) -> dict:
    if document is None:
        raise OperationError("no document exists yet; run import_baseline first")
    return document


def _find(document: dict, entry_id: str) -> dict:
    for entry in document.get("entries", []):
        if entry.get("id") == entry_id:
            return entry
    raise OperationError(f"no entry with id {entry_id!r}")


def _distinct_files(entries: list[dict]) -> int:
    return len({e["old"]["file"] for e in entries if e.get("old", {}).get("file")})


def _sync_counts(document: dict) -> None:
    entries = document.get("entries", [])
    counts = document.setdefault("counts", {})
    counts["declarations"] = len(entries)
    counts["files"] = _distinct_files(entries)


# Terminal dispositions record a deliberate decision that spent the entry; a
# later verb must not silently reverse it (spec §7 / interop issues #4, #7,
# strict posture). ``dropped``/``merged``/``split`` are all spent: a split
# source became multiple targets exactly as a merged source folded into one.
# ``renamed``/``moved``/``present`` are NOT terminal — the entry still exists as
# one declaration and may be re-dispositioned.
_TERMINAL = ("dropped", "merged", "split")


def _guard_not_terminal(entry: dict, *, force: bool) -> None:
    """Refuse to mutate a terminal (dropped/merged/split) entry unless forced.

    Use ``reopen`` to return the entry to ``pending`` first, or pass
    ``force=True`` to override deliberately (the override, like every write, is
    recorded in the audit log via ``engine.apply``).
    """
    disp = entry.get("disposition")
    if disp in _TERMINAL and not force:
        raise OperationError(
            f"entry {entry.get('id')!r} is {disp}; reopen it first (or pass force=true)"
        )


# -- bootstrapping ------------------------------------------------------------

def _load_json_input(value, *, label: str):
    """Accept a caller-provided INPUT as an inline object or a path to read.

    Reading a caller-specified *input* file does not breach the operations
    contract (which protects the registry/audit *output* files). Resolving the
    path here (rather than at the caller) keeps the call tiny and keeps the audit
    record's ``params`` to the path, not the inflated inline payload.
    """
    if isinstance(value, str):
        try:
            with open(value, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as exc:
            raise OperationError(f"{label} file not found: {value}") from exc
        except json.JSONDecodeError as exc:
            raise OperationError(f"{label} is not valid JSON ({value}): {exc}") from exc
    return value


def _resolve_scanner_output(scanner_output: Union[str, list]) -> list:
    """Scanner dump as an inline list or a path string to read."""
    scanner_output = _load_json_input(scanner_output, label="scanner_output")
    if not isinstance(scanner_output, list):
        raise OperationError(
            f"scanner_output must be a list of declaration dicts or a path to one, "
            f"got {type(scanner_output).__name__}"
        )
    return scanner_output


def _pending_entry_from_scan(item: dict) -> dict:
    """Build one fresh ``pending`` entry (surrogate id) from a scanner fact.

    Scanner facts carry natural attributes (``qualified``, ``file``, ``line`` …)
    but NO client id — sjv mints the surrogate here (interop issue #5, Decision
    A). Shared by ``import_baseline`` (founding) and ``reconcile`` (phantoms).
    """
    old = _empty_old()
    for leaf in old:
        if leaf in item:
            old[leaf] = item[leaf]
    return {
        "id": _mint_id(),
        "old": old,
        "new": _empty_new(),
        "disposition": "pending",
        "reason": None,
        "ontology": {"object": [], "domain": [], "role": []},
        "claims": {
            "witness_of": list(item.get("witness_of", [])),
            "citations": list(item.get("citations", [])),
        },
        "verify": {
            "sorry_free": bool(item.get("sorry_free", True)),
            "axioms": item.get("axioms"),
        },
    }


def import_baseline(document, *, scanner_output: Union[str, list[dict]], anchor: dict,
                    files: Optional[int] = None, force: bool = False) -> tuple[dict, list[str]]:
    """Freeze the initial entries (all ``pending``) from a scanner dump.

    ``scanner_output`` may be an inline list of declaration dicts or a path
    string to a JSON file containing that list (the practical form for the
    one-time bulk init, where the list is too large to author inline). Each fact
    carries natural attributes (``qualified`` is the key); it does NOT carry an
    ``id`` — sjv mints an opaque surrogate per entry (interop issue #5, A).

    FOUNDING-ONCE (interop issue #5): this is REPLACE semantics — it discards the
    current registry and writes a fresh all-``pending`` set, bypassing every
    per-entry guard. That is correct for the founding write but catastrophic if
    re-run over curated work (a re-scan reflex would annihilate dispositions,
    reasons, ontology, claims). So it REFUSES a non-empty registry unless
    ``force=True``. To fold a re-scan into an existing registry while preserving
    curation, use ``reconcile``, not a forced re-import.
    """
    existing = document.get("entries") if isinstance(document, dict) else None
    if existing and not force:
        raise OperationError(
            f"import_baseline refuses to replace a non-empty registry "
            f"({len(existing)} entries) — this would discard all curation "
            f"(dispositions, reasons, ontology, claims). Pass force=true to "
            f"overwrite deliberately, or reconcile a re-scan into the existing set."
        )
    scanner_output = _resolve_scanner_output(scanner_output)
    entries = [_pending_entry_from_scan(item) for item in scanner_output]
    touched = [e["id"] for e in entries]

    document = {
        "schema_version": "1",
        "anchor": {
            "branch": anchor.get("branch"),
            "commit": anchor.get("commit"),
            "tree": anchor.get("tree"),
        },
        "counts": {
            "files": files if files is not None else _distinct_files(entries),
            "declarations": len(entries),
        },
        "entries": entries,
    }
    return document, touched


# -- reconcile (interop issue #5, Decision B) ---------------------------------
#
# The MATCH RULE, shared verbatim with the ZP loss-checker. Identity is the
# fully-qualified name; file and line are LOCATION, not identity. The surrogate
# id is the stable handle a match resolves TO; ``qualified`` is what we match ON.

# disposition -> (group holding the effective-current name, is the decl expected
# to still be PRESENT in a fresh scan?). None => not matchable.
_RECONCILE_CLASS: dict[str, tuple[str, bool]] = {
    "pending": ("old", True),
    "present": ("old", True),
    "moved": ("old", True),   # a move changed the file, not the name
    "renamed": ("new", True),  # the name changed to new.qualified
    "new": ("new", True),      # add_new / merge-target / split-target
    "dropped": ("old", False),   # source name expected GONE
    "merged": ("old", False),    # merged-source name expected GONE
    "split": ("old", False),     # split-source name expected GONE
}


def _effective_qualified(entry: dict) -> tuple[Optional[str], Optional[str], Optional[bool]]:
    """Return ``(group, qualified, expected_present)`` for the match rule.

    ``group`` is ``"old"`` or ``"new"`` — which side holds the effective-current
    name (and thus the location fields reconcile updates on a match).
    """
    cls = _RECONCILE_CLASS.get(entry.get("disposition"))
    if cls is None:
        return None, None, None
    group, present = cls
    return group, entry.get(group, {}).get("qualified"), present


def reconcile(document, *, scanner_output: Union[str, list[dict]],
              anchor: Optional[dict] = None) -> tuple[dict, list[str], dict]:
    """Fold a fresh scan into the existing registry, PRESERVING curation.

    The safe, non-destructive sibling of ``import_baseline`` (interop issue #5).
    Match rule (Decision B), identical to the ZP loss-checker:

      * identity is the fully-qualified name; ``file``/``line`` are location.
      * a scan decl whose qualified matches an entry's effective-current name is
        the SAME decl: resolve to that entry's existing surrogate id, UPDATE its
        location (``file``/``line``), and PRESERVE disposition + all curation.
        (This is the "moved / line drifted" case — an update, never drop+add.)
      * an entry whose expected-present name is ABSENT from the scan → VANISHED,
        FLAGGED (never silently dropped).
      * a scan decl matching NO entry → PHANTOM: mint a surrogate, add as
        ``pending``, FLAG.
      * a ``dropped``/``merged``/``split`` source name that REAPPEARS in the scan
        → resurrection, FLAG.

    The irreducibly ambiguous case — a qualified-name change with no recorded
    ``rename`` — is mechanically identical to delete+add. Reconcile MUST NOT
    guess: it flags the vanished name and the phantom name separately for a human
    to adjudicate (record a ``rename``, or confirm delete+add).

    Returns ``(document, touched_ids, drift_summary)``; the drift summary is
    terse (counts + the flagged lists, per issue #6), not a full dump.
    """
    doc = _require_doc(document)
    scan = _resolve_scanner_output(scanner_output)

    scan_by_q: dict[str, dict] = {}
    skipped_no_qualified = 0
    for item in scan:
        q = item.get("qualified")
        if not q:
            skipped_no_qualified += 1
            continue
        if q in scan_by_q:
            raise OperationError(
                f"scanner_output has a duplicate qualified name {q!r}; qualified "
                f"must be a unique key for reconcile to match on it"
            )
        scan_by_q[q] = item

    entries = doc.get("entries", [])
    present_index: dict[str, dict] = {}   # qualified -> entry expected present
    gone_index: dict[str, dict] = {}      # qualified -> terminal source entry
    for entry in entries:
        group, q, present = _effective_qualified(entry)
        if not q:
            continue
        (present_index if present else gone_index)[q] = entry

    touched: list[str] = []
    updated: list[str] = []
    vanished: list[dict] = []
    phantom: list[dict] = []
    resurrection: list[dict] = []

    # (1) survivors + vanished: walk expected-present entries against the scan.
    for q, entry in present_index.items():
        item = scan_by_q.get(q)
        if item is None:
            vanished.append({"id": entry["id"], "qualified": q,
                             "disposition": entry["disposition"]})
            continue
        group, _, _ = _effective_qualified(entry)
        loc = entry[group]
        changed = False
        if "file" in item and loc.get("file") != item.get("file"):
            loc["file"] = item.get("file")
            changed = True
        # ``new`` groups carry no line; only ``old`` tracks it.
        if "line" in loc and "line" in item and loc.get("line") != item.get("line"):
            loc["line"] = item.get("line")
            changed = True
        if changed:
            touched.append(entry["id"])
            updated.append(entry["id"])

    # (2) resurrection: a terminal source name reappears in the scan.
    for q, entry in gone_index.items():
        if q in scan_by_q:
            resurrection.append({"id": entry["id"], "qualified": q,
                                 "disposition": entry["disposition"]})

    # (3) phantom / new: scan decls matching no entry at all → add as pending.
    known = set(present_index) | set(gone_index)
    for q, item in scan_by_q.items():
        if q in known:
            continue
        new_entry = _pending_entry_from_scan(item)
        entries.append(new_entry)
        touched.append(new_entry["id"])
        phantom.append({"id": new_entry["id"], "qualified": q})

    if anchor is not None:
        doc["anchor"] = {"branch": anchor.get("branch"), "commit": anchor.get("commit"),
                         "tree": anchor.get("tree")}
    _sync_counts(doc)

    drift = {
        "drift": {
            "scanned": len(scan_by_q),
            "registry_entries": len(entries),
            "matched": len(present_index) - len(vanished),
            "location_updated": len(updated),
            "vanished": vanished,
            "phantom": phantom,
            "resurrection": resurrection,
            "skipped_no_qualified": skipped_no_qualified,
        }
    }
    return doc, touched, drift


# -- disposition transitions --------------------------------------------------

def mark_present(document, *, id: str, force: bool = False) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    _guard_not_terminal(entry, force=force)
    old = entry["old"]
    q = old.get("qualified")
    entry["new"] = {
        "qualified": q,
        "short": old.get("short") or (short_of(q) if q else None),
        "file": old.get("file"),
        "namespace": namespace_of(q) if q else None,
    }
    entry["disposition"] = "present"
    return doc, [id]


def move(document, *, id: str, new_file: str, new_qualified: Optional[str] = None,
         namespace: Optional[str] = None, reason: Optional[str] = None,
         force: bool = False) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    _guard_not_terminal(entry, force=force)
    q = new_qualified or entry["old"].get("qualified")
    entry["new"] = {
        "qualified": q,
        "short": short_of(q) if q else None,
        "file": new_file,
        "namespace": namespace if namespace is not None else (namespace_of(q) if q else None),
    }
    entry["disposition"] = "moved"
    if reason is not None:
        entry["reason"] = reason
    return doc, [id]


def rename(document, *, id: str, new_qualified: str, new_file: str, namespace: str,
           reason: str, short: Optional[str] = None, force: bool = False) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    _guard_not_terminal(entry, force=force)
    entry["new"] = {
        "qualified": new_qualified,
        "short": short or short_of(new_qualified),
        "file": new_file,
        "namespace": namespace,
    }
    entry["disposition"] = "renamed"
    entry["reason"] = reason
    return doc, [id]


def merge(document, *, ids: list[str], target: dict, reason: str,
          force: bool = False) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    if len(ids) < 2:
        raise OperationError("merge needs >= 2 source ids")
    # Resolve + guard every source up front so a terminal source aborts the whole
    # merge before any mutation (all-or-nothing).
    sources = [_find(doc, eid) for eid in ids]
    for entry in sources:
        _guard_not_terminal(entry, force=force)
    tq = target.get("qualified")
    new = {
        "qualified": tq,
        "short": target.get("short") or (short_of(tq) if tq else None),
        "file": target.get("file"),
        "namespace": target.get("namespace") if target.get("namespace") is not None
        else (namespace_of(tq) if tq else None),
    }
    for entry in sources:
        entry["new"] = dict(new)
        entry["disposition"] = "merged"
        entry["reason"] = reason
    return doc, list(ids)


def split(document, *, id: str, targets: list[dict], reason: str,
          force: bool = False) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    if len(targets) < 2:
        raise OperationError("split needs >= 2 targets")
    primary = targets[0]  # new.* records the primary; siblings tracked via add_new
    pq = primary.get("qualified")
    entry = _find(doc, id)
    _guard_not_terminal(entry, force=force)
    entry["new"] = {
        "qualified": pq,
        "short": primary.get("short") or (short_of(pq) if pq else None),
        "file": primary.get("file"),
        "namespace": primary.get("namespace") if primary.get("namespace") is not None
        else (namespace_of(pq) if pq else None),
    }
    entry["disposition"] = "split"
    entry["reason"] = reason
    return doc, [id]


def drop(document, *, id: str, reason: str, force: bool = False) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    _guard_not_terminal(entry, force=force)
    entry["new"] = _empty_new()
    entry["disposition"] = "dropped"
    entry["reason"] = reason
    return doc, [id]


def reopen(document, *, id: str, reason: str) -> tuple[dict, list[str]]:
    """Return a terminal (dropped/merged/split) entry to ``pending``.

    The sanctioned way to undo a deliberate drop/merge/split: it clears ``new.*``
    and resets the disposition to ``pending`` so the entry can be
    re-dispositioned by the normal verbs. Rejects entries with no prior
    declaration to revert to (e.g. ``add_new`` entries, whose ``old.*`` is null).

    SCOPE (single entry only — interop issue #7): ``reopen`` reverts exactly the
    named entry and does NOT unwind related entries. Reopening one source of a
    multi-source ``merge`` leaves the other sources still pointing at the target
    (the target is fed by one fewer source, but is not a registry entry of its
    own, so nothing dangles). Reopening a ``split`` source leaves any sibling
    ``add_new`` target entries in place — reconcile those explicitly if the whole
    split is being undone. The caller owns re-dispositioning the related entries.
    """
    doc = _require_doc(document)
    entry = _find(doc, id)
    if entry.get("disposition") not in _TERMINAL:
        raise OperationError(
            f"entry {id!r} is {entry.get('disposition')!r}, not terminal; reopen only "
            f"applies to {' or '.join(_TERMINAL)} entries"
        )
    if entry["old"].get("qualified") is None:
        raise OperationError(
            f"cannot reopen {id!r}: no prior (old) declaration to revert to"
        )
    entry["new"] = _empty_new()
    entry["disposition"] = "pending"
    entry["reason"] = reason
    return doc, [id]


def add_new(document, *, new: dict, reason: str, id: Optional[str] = None,
            witness_of: Optional[list[str]] = None, citations: Optional[list[str]] = None,
            sorry_free: bool = True, axioms=None) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    nq = new.get("qualified")
    if not nq:
        raise OperationError("add_new requires new.qualified")
    new_group = {
        "qualified": nq,
        "short": new.get("short") or short_of(nq),
        "file": new.get("file"),
        "namespace": new.get("namespace") if new.get("namespace") is not None else namespace_of(nq),
    }
    eid = id or _mint_id()  # sjv mints the surrogate (interop issue #5, A)
    entry = {
        "id": eid,
        "old": _empty_old(),
        "new": new_group,
        "disposition": "new",
        "reason": reason,
        "ontology": {"object": [], "domain": [], "role": []},
        "claims": {"witness_of": list(witness_of or []), "citations": list(citations or [])},
        "verify": {"sorry_free": bool(sorry_free), "axioms": axioms},
    }
    doc.setdefault("entries", []).append(entry)
    _sync_counts(doc)
    return doc, [eid]


# -- curation -----------------------------------------------------------------

def _to_axis_list(value) -> list:
    """Coerce a provided axis value to its canonical list form (uniform-lists
    model): a scalar becomes ``[scalar]``, ``None`` / ``[]`` become ``[]`` (unset/
    clear), a list is kept (order preserved, deduped). Callers decide when an axis
    is "provided" vs "left unchanged" — this only shapes a provided value."""
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


def annotate(document, *, id: str, object=None, domain=None, role=None) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    ont = entry["ontology"]
    # A provided axis (scalar or list) SETS it (coerced to a list); an omitted
    # axis (None) is left unchanged. Pass [] to clear.
    if object is not None:
        ont["object"] = _to_axis_list(object)
    if domain is not None:
        ont["domain"] = _to_axis_list(domain)
    if role is not None:
        ont["role"] = _to_axis_list(role)
    return doc, [id]


def _tag_vocab_violations(doc: dict, tags: dict, *, where: str = "") -> list[str]:
    """Validate a raw ``{axis: value}`` map against the adopted vocab (if any).

    Same hard-enum rule as ``rules.validate`` but on tags before they are applied,
    so a bulk op reports one clean violation per bad axis instead of one per
    affected entry. Null values (clears) and, when no vocab is set, everything,
    pass here; structural checks still run as the engine postcondition.
    """
    vocab = doc.get("vocab")
    if not vocab:
        return []
    out: list[str] = []
    for field, raw in tags.items():
        spec = vocab.get(field)
        values = _to_axis_list(raw)  # scalar or list -> list of elements
        for value in values:
            if spec is None:
                out.append(f"{where}ontology field '{field}' is not in the vocab")
                break
            if value not in spec.get("values", []):
                out.append(f"{where}ontology.{field} value {value!r} not in vocab "
                           f"(allowed: {', '.join(spec['values'])})")
    return out


def _apply_tags(entry: dict, tags: dict) -> bool:
    """Set/clear the provided ontology axes on one entry (set only the keys
    present; a value SETS as a list, ``null``/``[]`` CLEARS). Coerces scalars to
    single-element lists. Returns True if changed."""
    ont = entry["ontology"]
    changed = False
    for field, value in tags.items():
        new_value = _to_axis_list(value)
        if ont.get(field) != new_value:
            ont[field] = new_value
            changed = True
    return changed


def annotate_many(document, *, items: list, force: bool = False) -> tuple[dict, list[str], dict]:
    """Batch annotate ontology axes by explicit id (interop issue #9).

    ``items`` is a list of ``{id, object?, domain?, role?, …}``. Per item the
    ``annotate`` rule holds: an OMITTED axis is left unchanged, an axis present
    with a value SETS it, and an axis present with explicit ``null`` CLEARS it.
    Atomic: the whole batch is validated (every id exists, no duplicate ids,
    every non-null value in its field's vocab) before any write, and the engine
    postcondition re-checks the result — any failure writes nothing. Returns a
    terse receipt ``{count, unchanged}`` (per #6, no full-entry echo).
    """
    doc = _require_doc(document)
    if not isinstance(items, list) or not items:
        raise OperationError("annotate_many requires a non-empty list of items")

    seen: set = set()
    resolved: list = []
    violations: list[str] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or "id" not in item:
            raise OperationError(f"items[{i}] must be an object with an 'id'")
        eid = item["id"]
        if eid in seen:
            raise OperationError(f"duplicate id {eid!r} in items (ambiguous)")
        seen.add(eid)
        entry = _find(doc, eid)  # OperationError if missing
        tags = {k: v for k, v in item.items() if k != "id"}
        violations.extend(_tag_vocab_violations(doc, tags, where=f"items[{i}] ({eid}): "))
        resolved.append((entry, tags))
    if violations:
        raise ValidationError(violations)  # same shape as annotate's failure

    touched: list[str] = []
    unchanged = 0
    for entry, tags in resolved:
        if _apply_tags(entry, tags):
            touched.append(entry["id"])
        else:
            unchanged += 1
    return doc, touched, {"count": len(touched), "unchanged": unchanged}


def annotate_by_filter(document, *, filter: dict, tags: dict,
                       force: bool = False) -> tuple[dict, list[str], dict]:
    """Annotate every entry matching a ``find``-style filter (interop issue #9).

    ``filter`` uses the same dotted-path AND semantics as ``find`` (e.g.
    ``{"old.prefix": "ZPA"}`` or ``{"old.prefix": "ZPB", "ontology.domain": null}``
    to hit only still-untagged entries). An empty filter would match the whole
    registry and is refused unless ``force=True``. ``tags`` is the uniform
    ``{axis: value}`` set applied to every match (value SETS, explicit ``null``
    CLEARS). Tags are vocab-validated ONCE up front. Atomic; terse receipt
    ``{matched, updated}``. (A read-only ``dry_run`` preview is offered by the MCP
    tool, which never writes.)
    """
    doc = _require_doc(document)
    if not isinstance(filter, dict):
        raise OperationError("filter must be an object of dotted-path = value")
    if not filter and not force:
        raise OperationError(
            "empty filter would match the whole registry; pass force=true to confirm"
        )
    if not isinstance(tags, dict) or not tags:
        raise OperationError("tags must be a non-empty object of axis = value")
    violations = _tag_vocab_violations(doc, tags)
    if violations:
        raise ValidationError(violations)

    matches = query.find(doc.get("entries", []), **filter)
    touched = [entry["id"] for entry in matches if _apply_tags(entry, tags)]
    return doc, touched, {"matched": len(matches), "updated": len(touched)}


def link_claim(document, *, id: str, claim: str) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    witnesses = entry["claims"]["witness_of"]
    if claim not in witnesses:
        witnesses.append(claim)
    return doc, [id]


def add_citation(document, *, id: str, target: str) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    citations = entry["claims"]["citations"]
    if target not in citations:
        citations.append(target)
    return doc, [id]


def _parse_cardinality(spec) -> Optional[dict]:
    """Normalize a cardinality expectation to ``{'min': int, 'max': int|None}``.

    Accepts the object form ``{min, max}`` (ZP's form), a range/count string
    (``'1'``, ``'1..1'``, ``'0..1'``, ``'1..*'``, or prose like
    ``'1 expected (soft)'``), or ``None``. Only ``min`` is currently consulted
    (by the ``anomalies`` view); ``max`` is stored for future use. Returns
    ``None`` when no expectation is expressed.
    """
    if spec is None:
        return None
    if isinstance(spec, dict):
        lo, hi = spec.get("min", 0), spec.get("max", None)
        mn = int(lo) if isinstance(lo, int) or (isinstance(lo, str) and lo.isdigit()) else 0
        mx = int(hi) if isinstance(hi, int) or (isinstance(hi, str) and hi.isdigit()) else None
        return {"min": mn, "max": mx}
    if isinstance(spec, str):
        s = spec.strip()
        if not s:
            return None
        if ".." in s:
            lo, hi = s.split("..", 1)
            lo_tok = (lo.strip().split() or ["0"])[0]
            hi_tok = (hi.strip().split() or [""])[0]
            return {"min": int(lo_tok) if lo_tok.isdigit() else 0,
                    "max": int(hi_tok) if hi_tok.isdigit() else None}
        tok = s.split()[0]
        return {"min": int(tok) if tok.isdigit() else 0, "max": None}
    return None


def set_vocab(document, *, vocab) -> tuple[dict, list[str]]:
    """Adopt the controlled ontology vocabulary (interop tag-vocab work item).

    ``vocab`` is a caller-provided config (ZP-owned) — an inline object or a path
    to a JSON file — mapping each ontology FIELD to its allowed values. Each
    field maps to either a bare ``[values]`` list or an object
    ``{values:[...], cardinality?, glosses?}``; sjv reads only ``values`` (the
    HARD enum) and ``cardinality`` (a SOFT expectation surfaced by the
    ``anomalies`` view, never enforced). ``cardinality`` may be an object
    ``{min, max}`` or a range/count string. Values are stored de-duplicated and
    alphabetized for clean diffs.

    Two config shapes are accepted: axes under a ``fields`` key (with sibling
    metadata like status/purpose/glosses, all ignored), or a bare
    ``{field: ...}`` map. Top-level ``_``-prefixed keys are skipped as markers.

    The field SET is whatever the config declares — sjv does NOT hardcode
    object/domain/role (config-driven, per the decision). Once a vocab is set,
    ``validate`` REJECTS any ontology value outside its field's list and any
    populated ontology field absent from the vocab. Enforcement is opt-in: with
    no vocab set, ontology values are unconstrained (beyond the schema), so ZP
    ratifies values first, then adopts. Because the postcondition validates the
    whole registry, adopting a vocab that existing curation violates is refused —
    fix the data (or the vocab) first.
    """
    doc = _require_doc(document)
    raw = _load_json_input(vocab, label="vocab")
    if not isinstance(raw, dict) or not raw:
        raise OperationError(
            "vocab must be a non-empty object mapping ontology fields to allowed values"
        )
    field_map = raw["fields"] if isinstance(raw.get("fields"), dict) else raw
    normalized: dict[str, dict] = {}
    for field, spec in field_map.items():
        if field.startswith("_"):  # a draft marker / note, not a field
            continue
        if isinstance(spec, list):
            values, cardinality = spec, None
        elif isinstance(spec, dict):
            values, cardinality = spec.get("values"), spec.get("cardinality")
        else:
            raise OperationError(
                f"vocab field {field!r} must map to a list of values or an object with 'values'"
            )
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise OperationError(f"vocab field {field!r} 'values' must be a list of strings")
        normalized[field] = {
            "values": sorted(set(values)),
            "cardinality": _parse_cardinality(cardinality),
        }
    if not normalized:
        raise OperationError("vocab has no fields")
    doc["vocab"] = normalized
    return doc, []


OPERATIONS = {
    "import_baseline": import_baseline,
    "reconcile": reconcile,
    "mark_present": mark_present,
    "move": move,
    "rename": rename,
    "merge": merge,
    "split": split,
    "drop": drop,
    "reopen": reopen,
    "add_new": add_new,
    "annotate": annotate,
    "annotate_many": annotate_many,
    "annotate_by_filter": annotate_by_filter,
    "link_claim": link_claim,
    "add_citation": add_citation,
    "set_vocab": set_vocab,
}
