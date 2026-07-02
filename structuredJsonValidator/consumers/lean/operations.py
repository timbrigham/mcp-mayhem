"""Operations (verbs) for the Lean-declaration consumer (spec §9).

Contract for the engine: each operation takes the current document (or ``None``
when bootstrapping) plus typed params, mutates a copy, and returns
``(document, touched_ids)``. Operations never touch the file or the audit log —
the engine does that after the result passes full validation.
"""

from __future__ import annotations

import json
from typing import Optional, Union

from core.errors import OperationError


# -- structure helpers --------------------------------------------------------

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


# Terminal dispositions record a deliberate decision; a later verb must not
# silently reverse it (spec §7 / interop issue #4, strict posture).
_TERMINAL = ("dropped", "merged")


def _guard_not_terminal(entry: dict, *, force: bool) -> None:
    """Refuse to mutate a terminal (dropped/merged) entry unless forced.

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


def import_baseline(document, *, scanner_output: Union[str, list[dict]], anchor: dict,
                    files: Optional[int] = None) -> tuple[dict, list[str]]:
    """Freeze the initial entries (all ``pending``) from a scanner dump.

    ``scanner_output`` may be an inline list of declaration dicts or a path
    string to a JSON file containing that list (the practical form for the
    one-time bulk init, where the list is too large to author inline).

    Idempotent: rebuilt deterministically from the same input yields the same
    document. ``scanner_output`` items carry the old-decl fields; new.* is null.
    """
    scanner_output = _resolve_scanner_output(scanner_output)
    entries: list[dict] = []
    touched: list[str] = []
    for item in scanner_output:
        old = _empty_old()
        for leaf in old:
            if leaf in item:
                old[leaf] = item[leaf]
        eid = f"{old['file']}::{old['qualified']}::L{old['line']}"
        entries.append({
            "id": eid,
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
        })
        touched.append(eid)

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
    """Return a terminal (dropped/merged) entry to ``pending``.

    The sanctioned way to undo a deliberate drop/merge: it clears ``new.*`` and
    resets the disposition to ``pending`` so the entry can be re-dispositioned by
    the normal verbs. Rejects entries with no prior declaration to revert to
    (e.g. ``add_new`` entries, whose ``old.*`` is null).
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
    eid = id or f"{new_group['file']}::{nq}::Lnew"
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
