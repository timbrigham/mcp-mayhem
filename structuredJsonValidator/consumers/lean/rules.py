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
#   state "set"   => identity leaf (.qualified) is non-null
#   state "null"  => every leaf in the group is null
#   state "birth" => a born-at-HEAD entry: either a SYNTHETIC old (the birth
#                    identity recorded at add_new time — interop #16a) or, for
#                    entries created before that change, all leaves null.
DISPOSITION_RULES: dict[str, tuple[str, str, bool]] = {
    "pending": ("set", "null", False),
    "present": ("set", "set", False),
    "moved": ("set", "set", False),
    "renamed": ("set", "set", True),
    "merged": ("set", "set", True),
    "split": ("set", "set", True),
    "dropped": ("set", "null", True),
    "new": ("birth", "set", True),
}


def _all_null(group: dict, leaves: tuple[str, ...]) -> bool:
    return all(group.get(leaf) is None for leaf in leaves)


def _identity_set(group: dict) -> bool:
    return group.get("qualified") is not None


def is_synthetic_old(entry: dict) -> bool:
    """Was this entry's ``old`` block synthesized from its birth identity?

    True for a declaration that never existed at the anchor: ``add_new`` records
    the name it was BORN with as ``old`` (flagged ``synthetic``) so that every
    disposition verb — which all need a prior identity to transition FROM — works
    on it (interop #15a/#16a). The flag is what keeps "born at HEAD" analytically
    distinguishable from "migrated from a real prior name".
    """
    return bool((entry.get("old") or {}).get("synthetic"))


def is_born_at_head(entry: dict) -> bool:
    """True when the entry has no anchored lineage: its ``old`` is synthetic, or
    (legacy, pre-#16a) absent entirely. These are the only entries a hard
    ``remove`` may erase — there is no prior identity a tombstone would preserve."""
    old = entry.get("old") or {}
    return bool(old.get("synthetic")) or old.get("qualified") is None


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
    if state == "birth":
        # A born-at-HEAD entry: a synthetic old (post-#16a) or a fully null one
        # (legacy). What is NOT allowed is a real, anchored old identity — that
        # would claim the decl existed at the anchor, which 'new' denies.
        if _all_null(group, leaves) or group.get("synthetic"):
            return None
        return "must be null or synthetic (a 'new' entry has no anchored identity)"
    raise ValueError(f"unknown state {state!r}")  # programming error, not data error


# -- the identity match rule (interop #5 Decision B, generalized by #14) -------
#
# Shared verbatim with the ZP loss-checker and with reconcile/deps: identity is
# the fully-qualified name; file and line are LOCATION, not identity.

# disposition -> (group holding the effective-current name, is the decl expected
# to still be PRESENT in a fresh scan?). None => not matchable.
RECONCILE_CLASS: dict[str, tuple[str, bool]] = {
    "pending": ("old", True),
    "present": ("old", True),
    "moved": ("old", True),   # a move changed the file, not the name
    "renamed": ("new", True),  # the name changed to new.qualified
    "new": ("new", True),      # add_new / merge-target / split-target
    "dropped": ("old", False),   # source name expected GONE
    "merged": ("old", False),    # merged-source name expected GONE
    "split": ("old", False),     # split-source name expected GONE
}


def effective_qualified(entry: dict) -> tuple[Optional[str], Optional[str], Optional[bool]]:
    """Return ``(group, qualified, expected_present)`` for the match rule.

    ``group`` is ``"old"`` or ``"new"`` — which side holds the effective-current
    name (and thus the location fields reconcile updates on a match).

    The effective-current name is the LATEST recorded identity: for a
    still-present entry that carries a populated ``new.qualified`` (a HEAD
    identity recorded by a rename, a split/merge target, or a bulk reorg
    migration under a ``present``/``moved`` disposition — interop #14), that new
    name wins; otherwise the name lives in the group the disposition designates.
    This is backward-compatible with Decision B: ``pending`` has a null
    ``new.qualified`` (falls back to ``old``), and a normal ``present``/``moved``
    keeps ``new == old``, so the only case this changes is a surviving entry whose
    HEAD identity genuinely differs from its old one — exactly what a reorg
    migration produces, and what deps rebuilt at HEAD names must resolve against.
    """
    cls = RECONCILE_CLASS.get(entry.get("disposition"))
    if cls is None:
        return None, None, None
    group, present = cls
    if present:
        new_qualified = (entry.get("new") or {}).get("qualified")
        if new_qualified:
            return "new", new_qualified, present
    return group, entry.get(group, {}).get("qualified"), present


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

    violations.extend(_effective_name_collisions(entries))
    violations.extend(_vocab_violations(document, entries))
    return violations


def _effective_name_collisions(entries: list[dict]) -> list[str]:
    """The effective-current qualified name must be UNIQUE among the entries that
    are expected to still exist (interop #17, 2026-08-08 ask 1).

    Two live entries naming the same declaration means the registry asserts one
    Lean decl twice — the failure mode that let an unretirable ``add_new`` be
    "retargeted" onto an existing name and still validate green. Lean enforces
    globally-unique FQNs, so a duplicate is always a registry defect.

    Only the expected-PRESENT class is checked. ``merged`` sources deliberately
    share their target's ``new.qualified`` (that is what a merge records), and
    ``dropped``/``split`` sources name something that is gone — none of those are
    live claims about a current declaration.
    """
    seen: dict[str, str] = {}
    out: list[str] = []
    for idx, entry in enumerate(entries):
        _, qualified, present = effective_qualified(entry)
        if not qualified or not present:
            continue
        eid = entry.get("id", f"entries[{idx}]")
        if qualified in seen:
            out.append(
                f"{eid}: duplicate effective-current qualified {qualified!r} "
                f"(also live on {seen[qualified]}) — one declaration, two live entries"
            )
        else:
            seen[qualified] = eid
    return out


# Built-in floor values per ontology axis (interop 2026-07-02: role config-driven).
# The effective allowed set for an axis is these UNION the adopted vocab's values
# — config EXTENDS the built-ins, it does not replace them. So adding a value to
# ANY axis (incl. role) is a `set_vocab`, not a schema/code change. Axes with no
# built-ins (object/domain) are governed entirely by the vocab. role keeps a floor
# so it stays constrained even if no vocab is adopted (safety).
_BUILTIN_AXIS_VALUES: dict[str, tuple[str, ...]] = {
    "role": ("bridge", "commitment", "core", "face", "infra", "no-go", "scaffolding", "schema"),
}


def _vocab_violations(document: dict, entries: list[dict]) -> list[str]:
    """Ontology enum enforcement: each element of each axis must be in that axis's
    (built-in floor) UNION (adopted vocab values).

    An axis with neither a built-in floor nor a vocab entry is unconstrained —
    EXCEPT that once a vocab IS adopted, a populated axis missing from it is
    flagged ('field not in the vocab'), preserving the config-drives-the-field-set
    contract. Empty lists are unset (skipped); cardinality is soft (anomalies
    view), not enforced here.
    """
    vocab = document.get("vocab") or {}
    has_vocab = bool(vocab)
    out: list[str] = []
    for idx, entry in enumerate(entries):
        eid = entry.get("id", f"entries[{idx}]")
        for field, values in (entry.get("ontology") or {}).items():
            values = values or []
            if not values:
                continue  # empty list = unset
            builtins = set(_BUILTIN_AXIS_VALUES.get(field, ()))
            in_vocab = field in vocab
            if not builtins and not in_vocab:
                # governed by neither: unconstrained, unless a vocab is adopted
                # and simply omits this field (then it's an unknown field).
                if has_vocab:
                    out.append(f"{eid}: ontology field '{field}' is not in the vocab")
                continue
            allowed = builtins | set(vocab.get(field, {}).get("values", []))
            for value in values:
                if value not in allowed:
                    out.append(
                        f"{eid}: ontology.{field} value {value!r} not allowed "
                        f"(built-ins ∪ vocab: {', '.join(sorted(allowed))})"
                    )
    return out
