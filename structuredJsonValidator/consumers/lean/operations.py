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

from core.errors import OperationError


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

def _resolve_scanner_output(scanner_output: Union[str, list]) -> list:
    """Accept the scanner dump as an inline list or a path string to read.

    Reading a caller-specified *input* file does not breach the operations
    contract (which protects the registry/audit *output* files). Resolving the
    path here rather than at the caller keeps the founding import a tiny call and
    keeps the audit record's ``params`` to the path, not a 1k-element inline list.
    """
    if isinstance(scanner_output, str):
        try:
            with open(scanner_output, encoding="utf-8") as f:
                scanner_output = json.load(f)
        except FileNotFoundError as exc:
            raise OperationError(f"scanner_output file not found: {scanner_output}") from exc
        except json.JSONDecodeError as exc:
            raise OperationError(f"scanner_output is not valid JSON ({scanner_output}): {exc}") from exc
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
        "ontology": {"object": None, "domain": None, "role": None},
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
        "ontology": {"object": None, "domain": None, "role": None},
        "claims": {"witness_of": list(witness_of or []), "citations": list(citations or [])},
        "verify": {"sorry_free": bool(sorry_free), "axioms": axioms},
    }
    doc.setdefault("entries", []).append(entry)
    _sync_counts(doc)
    return doc, [eid]


# -- curation -----------------------------------------------------------------

def annotate(document, *, id: str, object=None, domain=None, role=None) -> tuple[dict, list[str]]:
    doc = _require_doc(document)
    entry = _find(doc, id)
    ont = entry["ontology"]
    if object is not None:
        ont["object"] = object
    if domain is not None:
        ont["domain"] = domain
    if role is not None:
        ont["role"] = role
    return doc, [id]


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
    "link_claim": link_claim,
    "add_citation": add_citation,
}
