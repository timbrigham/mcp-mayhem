"""Business rules for the Lean-declaration consumer (spec §7).

These are the cross-field / conditional / uniqueness constraints that basic JSON
Schema cannot express cleanly, so they live in code. They are consumer-specific
by design: the generic core knows nothing about ``disposition`` or the per-
disposition old/new table (spec §13/§14 — keep Lean specifics out of the tool).
"""

from __future__ import annotations

from typing import Optional

OLD_LEAVES = ("qualified", "short", "kind", "file", "line", "prefix")
NEW_LEAVES = ("qualified", "short", "file", "namespace")

# disposition -> (old_state, new_state, reason_required)
#   state "set"  => identity leaf (.qualified) is non-null
#   state "null" => every leaf in the group is null
DISPOSITION_RULES: dict[str, tuple[str, str, bool]] = {
    "pending": ("set", "null", False),
    "present": ("set", "set", False),
    "moved": ("set", "set", False),
    "renamed": ("set", "set", True),
    "merged": ("set", "set", True),
    "split": ("set", "set", True),
    "dropped": ("set", "null", True),
    "new": ("null", "set", True),
}


def _all_null(group: dict, leaves: tuple[str, ...]) -> bool:
    return all(group.get(leaf) is None for leaf in leaves)


def _identity_set(group: dict) -> bool:
    return group.get("qualified") is not None


def _check_group(group: dict, leaves: tuple[str, ...], state: str) -> Optional[str]:
    if state == "set":
        if not _identity_set(group):
            return "qualified must be set (non-null)"
        return None
    if state == "null":
        if not _all_null(group, leaves):
            nonnull = [leaf for leaf in leaves if group.get(leaf) is not None]
            return f"all leaves must be null, but {', '.join(nonnull)} are set"
        return None
    raise ValueError(f"unknown state {state!r}")  # programming error, not data error


def validate(document: dict) -> list[str]:
    """Return all business-rule violations for the whole document."""
    violations: list[str] = []
    entries = document.get("entries", [])

    # counts.declarations must equal the number of entries.
    declared = document.get("counts", {}).get("declarations")
    if declared is not None and declared != len(entries):
        violations.append(
            f"counts.declarations ({declared}) != number of entries ({len(entries)})"
        )

    # id uniqueness (primary key). Not expressible in JSON Schema.
    seen: dict[str, int] = {}
    for idx, entry in enumerate(entries):
        eid = entry.get("id")
        if eid in seen:
            violations.append(
                f"entries[{idx}]: duplicate id {eid!r} (first seen at entries[{seen[eid]}])"
            )
        else:
            seen[eid] = idx

    # per-disposition old/new/reason constraints.
    for idx, entry in enumerate(entries):
        disposition = entry.get("disposition")
        rule = DISPOSITION_RULES.get(disposition)
        eid = entry.get("id", f"entries[{idx}]")
        if rule is None:
            # Unknown disposition is caught structurally by the enum; skip here.
            continue
        old_state, new_state, reason_required = rule
        old = entry.get("old", {})
        new = entry.get("new", {})

        old_err = _check_group(old, OLD_LEAVES, old_state)
        if old_err:
            violations.append(f"{eid}: disposition '{disposition}' requires old.{old_err}")
        new_err = _check_group(new, NEW_LEAVES, new_state)
        if new_err:
            violations.append(f"{eid}: disposition '{disposition}' requires new.{new_err}")

        if reason_required:
            reason = entry.get("reason")
            if not (isinstance(reason, str) and reason.strip()):
                violations.append(
                    f"{eid}: disposition '{disposition}' requires a non-empty reason"
                )

    violations.extend(_vocab_violations(document, entries))
    return violations


def _vocab_violations(document: dict, entries: list[dict]) -> list[str]:
    """Config-driven ontology enum (interop tag-vocab work item).

    Opt-in: only enforced once a ``vocab`` has been adopted (``set_vocab``). For
    every populated ontology field, the field must be in the vocab and its value
    must be one of that field's allowed values. A null (unset) axis is always
    fine. Cardinality is NOT enforced here — it is a soft expectation surfaced by
    the ``anomalies`` view.
    """
    vocab = document.get("vocab")
    if not vocab:
        return []
    out: list[str] = []
    for idx, entry in enumerate(entries):
        eid = entry.get("id", f"entries[{idx}]")
        for field, values in (entry.get("ontology") or {}).items():
            # Every axis is a list (uniform-lists model); an empty list is unset.
            for value in (values or []):
                spec = vocab.get(field)
                if spec is None:
                    out.append(f"{eid}: ontology field '{field}' is not in the vocab")
                    break
                allowed = spec.get("values", [])
                if value not in allowed:
                    out.append(
                        f"{eid}: ontology.{field} value {value!r} not in vocab "
                        f"(allowed: {', '.join(allowed)})"
                    )
    return out
