"""Business rules for the ``claims`` collection (interop issue #12).

The claim graph is a homogeneous table: a node and an edge are ONE shape (an edge
is a claim with ``from``/``to`` populated). These rules cover what JSON Schema
cannot: ``claim_id`` uniqueness (the greppable natural key), the config-driven
enum on ``status``/``object``/``domain`` (built-in floor UNION adopted vocab,
element-aware — the same mechanism the declaration ``role`` axis uses), and
``from``/``to`` reference integrity (an edge endpoint must resolve to a real
claim — no dangling edges).

The KILLER cross-collection invariant (a ``proved``/``deep`` claim needs a live
declaration witness) is NOT here — it spans collections, so it lives at the store
level (``core.engine.Store`` cross-validators). These rules are intra-collection.
"""

from __future__ import annotations

# Built-in floor per claim axis (config EXTENDS it, never replaces — interop #11
# mechanism). ``status`` keeps a floor so it stays constrained even with no vocab
# adopted; ``object``/``domain`` have no floor (governed entirely by the vocab,
# exactly as on the declaration side).
_BUILTIN_AXIS_VALUES: dict[str, tuple[str, ...]] = {
    "status": ("commitment", "conj", "corr", "deep", "proved"),
}

# The claim axes governed by the vocab/floor enum. object/domain are LISTS
# (element-aware); status is a single scalar string.
_LIST_AXES = ("object", "domain")
_SCALAR_AXES = ("status",)


def _allowed(field: str, vocab: dict) -> tuple[set, bool]:
    """(allowed value set, is-governed) for an axis: built-in floor UNION the
    adopted vocab's values. ``is_governed`` is False only when the axis has no
    floor AND the vocab does not mention it."""
    builtins = set(_BUILTIN_AXIS_VALUES.get(field, ()))
    in_vocab = field in vocab
    allowed = builtins | set(vocab.get(field, {}).get("values", []))
    return allowed, bool(builtins) or in_vocab


def validate(document: dict) -> list[str]:
    """Return all business-rule violations for the whole claims document."""
    violations: list[str] = []
    entries = document.get("entries", [])
    vocab = document.get("vocab") or {}
    has_vocab = bool(vocab)

    # id + claim_id uniqueness (surrogate handle and greppable natural key).
    seen_id: dict[str, int] = {}
    seen_cid: dict[str, int] = {}
    claim_ids: set[str] = set()
    for idx, claim in enumerate(entries):
        eid = claim.get("id")
        if eid in seen_id:
            violations.append(
                f"entries[{idx}]: duplicate id {eid!r} (first at entries[{seen_id[eid]}])"
            )
        else:
            seen_id[eid] = idx
        cid = claim.get("claim_id")
        if cid in seen_cid:
            violations.append(
                f"entries[{idx}]: duplicate claim_id {cid!r} (first at entries[{seen_cid[cid]}])"
            )
        else:
            seen_cid[cid] = idx
        if cid is not None:
            claim_ids.add(cid)

    # per-claim enum + reference integrity.
    for idx, claim in enumerate(entries):
        cid = claim.get("claim_id", f"entries[{idx}]")

        # scalar axis (status): the value, when set, must be in floor UNION vocab.
        for field in _SCALAR_AXES:
            value = claim.get(field)
            if value is None:
                continue
            allowed, governed = _allowed(field, vocab)
            if not governed:
                if has_vocab:
                    violations.append(f"{cid}: {field} field is not in the vocab")
                continue
            if value not in allowed:
                violations.append(
                    f"{cid}: {field} value {value!r} not allowed "
                    f"(built-ins ∪ vocab: {', '.join(sorted(allowed))})"
                )

        # list axes (object/domain): element-aware.
        for field in _LIST_AXES:
            values = claim.get(field) or []
            if not values:
                continue  # empty list = unset
            allowed, governed = _allowed(field, vocab)
            if not governed:
                if has_vocab:
                    violations.append(f"{cid}: {field} field is not in the vocab")
                continue
            for value in values:
                if value not in allowed:
                    violations.append(
                        f"{cid}: {field} value {value!r} not allowed "
                        f"(built-ins ∪ vocab: {', '.join(sorted(allowed))})"
                    )

        # from/to reference integrity: a populated endpoint must resolve to a
        # real claim_id in this collection (no dangling edges — interop #12 T2).
        for endpoint in ("from", "to"):
            ref = claim.get(endpoint)
            if ref is not None and ref not in claim_ids:
                violations.append(
                    f"{cid}: {endpoint} references unknown claim_id {ref!r} (dangling edge)"
                )

    return violations
