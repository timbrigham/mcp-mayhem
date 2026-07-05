"""Business rules for the ``deps`` collection (interop issue #13).

Minimal by design: ``deps`` is a DERIVED, zero-curation collection (every edge is
extracted mechanically from the Lean environment), so there is no per-disposition
table, no vocab, no terminal-state machine. The only intra-collection rule is
surrogate-id uniqueness. The one real validation — that ``from``/``to`` resolve to
a real declaration — is CROSS-collection and lives at the store level
(``consumers.store.deps_reference_integrity``).
"""

from __future__ import annotations


def validate(document: dict) -> list[str]:
    """Return all business-rule violations for the whole deps document."""
    violations: list[str] = []
    seen: dict[str, int] = {}
    for idx, edge in enumerate(document.get("entries", [])):
        eid = edge.get("id")
        if eid in seen:
            violations.append(
                f"entries[{idx}]: duplicate id {eid!r} (first at entries[{seen[eid]}])"
            )
        else:
            seen[eid] = idx
    return violations
