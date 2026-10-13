"""Verbs for the ``incidents`` collection: the only way entries change.

  * ``add_incident``: record an incident, status ``open`` (or ``wontfix``); never ``guarded``.
  * ``set_guarded``: mark it guarded, which requires the guard commit, the regression test's
    node id and when it was guarded, all together.
  * ``annotate``: append a dated note. Notes are never edited or removed.
  * ``correct_guard``: replace a wrong guard, moving the old one into ``guard_history``.
"""

from __future__ import annotations

from typing import Any, Optional

from core.errors import OperationError


def _require(document: Optional[dict]) -> dict:
    if document is None:
        raise OperationError("no incidents document exists yet")
    return document


def _find(doc: dict, incident_id: str) -> dict:
    for inc in doc.get("entries", []):
        if inc.get("id") == incident_id:
            return inc
    raise OperationError(f"no incident {incident_id!r}")


def _next_id(doc: dict) -> str:
    nums = [int(e["id"].split("-")[1]) for e in doc.get("entries", [])
            if str(e.get("id", "")).startswith("INC-")]
    return f"INC-{(max(nums) + 1 if nums else 1):04d}"


def add_incident(document, *, detected_at: str, detected_by: str, tool: str, operation: str,
                 args: Any, harm: str, pattern_id: str, observed_at: Optional[str] = None,
                 session: Optional[str] = None, status: str = "open",
                 note: Optional[str] = None, note_at: Optional[str] = None):
    doc = _require(document)
    if status not in ("open", "wontfix"):
        raise OperationError("add_incident records 'open' or 'wontfix'; use set_guarded to "
                             "record a guard, which needs its commit, test and time")
    if note is not None and note_at is None:
        raise OperationError("a note needs note_at (a UTC timestamp)")
    entry = {
        "id": _next_id(doc), "observed_at": observed_at, "detected_at": detected_at,
        "detected_by": detected_by, "session": session, "tool": tool, "operation": operation,
        "args": args, "harm": harm, "pattern_id": pattern_id, "status": status,
        "guard_commit": None, "regression_test": None, "guarded_at": None,
        "notes": [{"at": note_at, "text": note}] if note is not None else [],
    }
    doc.setdefault("entries", []).append(entry)
    return doc, [entry["id"]]


def set_guarded(document, *, id: str, guard_commit: str, regression_test: str,
                guarded_at: str):
    doc = _require(document)
    if not (guard_commit and regression_test and guarded_at):
        raise OperationError("set_guarded requires guard_commit, regression_test and guarded_at")
    inc = _find(doc, id)
    # A recorded guard is evidence; rewriting it in place would erase what was claimed before.
    if inc.get("status") != "open":
        raise OperationError(f"{id} is {inc.get('status')!r}; only an open incident can be "
                             f"marked guarded. To correct a recorded guard, annotate it.")
    inc.update(status="guarded", guard_commit=guard_commit, regression_test=regression_test,
               guarded_at=guarded_at)
    return doc, [id]


def annotate(document, *, id: str, text: str, at: str):
    doc = _require(document)
    _find(doc, id).setdefault("notes", []).append({"at": at, "text": text})
    return doc, [id]


def correct_guard(document, *, id: str, guard_commit: str, regression_test: str,
                  guarded_at: str, superseded_entry_point: str, reason: str, at: str):
    """Replace a recorded guard that was the wrong one (e.g. it covers a different entry point
    from the one the incident happened through). The old guard is not erased: it moves into the
    append-only `guard_history` with the entry point it covered, why it was superseded and
    when, so a reader can still reconstruct what was claimed before."""
    doc = _require(document)
    if not all((guard_commit, regression_test, guarded_at, superseded_entry_point, reason, at)):
        raise OperationError("correct_guard requires guard_commit, regression_test, guarded_at, "
                             "superseded_entry_point, reason and at")
    inc = _find(doc, id)
    if inc.get("status") != "guarded":
        raise OperationError(f"{id} is {inc.get('status')!r}; correct_guard replaces an existing "
                             f"guard. Use set_guarded to record a first one.")
    inc.setdefault("guard_history", []).append({
        "guard_commit": inc["guard_commit"], "regression_test": inc["regression_test"],
        "guarded_at": inc["guarded_at"], "entry_point": superseded_entry_point,
        "reason": reason, "superseded_at": at})
    inc.update(guard_commit=guard_commit, regression_test=regression_test, guarded_at=guarded_at)
    return doc, [id]


OPERATIONS = {"add_incident": add_incident, "set_guarded": set_guarded, "annotate": annotate,
              "correct_guard": correct_guard}
