"""Projections over the claim graph (interop issue #12 T7).

Both views are PURE JOINS of already-validated store state: the store enforces
the witness invariant on every write, so by the time a view renders, no
``proved``/``deep`` claim can lack a live witness — the gate runs before the
projection by construction (spec §5: views cannot drift from the source). Output
is deterministic (claims sorted by ``claim_id``) so published diagrams diff
cleanly.

These are CROSS-COLLECTION views: they declare a ``store`` parameter, so
``Store.export_view`` hands them the whole envelope to join claims × declarations.
"""

from __future__ import annotations

from typing import Optional

_STATUS_ORDER = ["proved", "deep", "corr", "conj", "commitment"]
_LIVE = {"proved", "deep"}


def _witness_index(store: Optional[dict]) -> dict[str, dict]:
    """claim_id -> {'total': n, 'live': n} derived from declarations[*].claims.
    witness_of joined with verify.sorry_free. Witnesses are DERIVED, never stored
    on the claim (interop #12 T3 — one source for the link: the declaration)."""
    index: dict[str, dict] = {}
    decls = (((store or {}).get("collections") or {}).get("declarations") or {}).get("entries", [])
    for d in decls:
        sorry_free = bool((d.get("verify") or {}).get("sorry_free", False))
        for cid in (d.get("claims") or {}).get("witness_of") or []:
            slot = index.setdefault(cid, {"total": 0, "live": 0})
            slot["total"] += 1
            if sorry_free:
                slot["live"] += 1
    return index


def status_table(document: dict, *, store: Optional[dict] = None, **_params) -> str:
    """Dated status table: one row per claim (sorted by claim_id) with its current
    status, the date it was reached, and its DERIVED live-witness count."""
    index = _witness_index(store)
    claims = sorted(document.get("entries", []), key=lambda c: str(c.get("claim_id", "")))
    lines = ["| claim_id | status | date | live witnesses |", "|---|---|---|---|"]
    tally = {s: 0 for s in _STATUS_ORDER}
    for c in claims:
        cid = c.get("claim_id")
        status = c.get("status")
        if status in tally:
            tally[status] += 1
        live = index.get(cid, {}).get("live", 0)
        lines.append(f"| {cid} | {status if status is not None else '_(unset)_'} "
                     f"| {c.get('date') or ''} | {live} |")
    summary = ", ".join(f"{s}={tally[s]}" for s in _STATUS_ORDER)
    lines.append(f"| **total {len(claims)}** | {summary} | | |")
    return "\n".join(lines)


def claim_graph(document: dict, *, store: Optional[dict] = None, **_params) -> str:
    """Claim-graph diagram as a deterministic Mermaid ``graph LR`` block: each
    node at its TRUE status, each edge (a claim with ``from``/``to`` populated)
    drawn between endpoints. Nodes and edges sorted by claim_id for stable diffs."""
    index = _witness_index(store)
    claims = sorted(document.get("entries", []), key=lambda c: str(c.get("claim_id", "")))
    nodes = [c for c in claims if c.get("from") is None and c.get("to") is None]
    edges = [c for c in claims if c.get("from") is not None or c.get("to") is not None]

    def _nid(cid: str) -> str:
        # Mermaid-safe node id: keep it stable + deterministic from the claim_id.
        return "n_" + "".join(ch if ch.isalnum() else "_" for ch in str(cid))

    lines = ["```mermaid", "graph LR"]
    for c in nodes:
        cid = c.get("claim_id")
        live = index.get(cid, {}).get("live", 0)
        badge = f"{cid}<br/>{c.get('status')} - {live}w"
        lines.append(f'  {_nid(cid)}["{badge}"]')
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        label = f"{e.get('claim_id')}: {e.get('status')}"
        if src is not None and dst is not None:
            lines.append(f'  {_nid(src)} -->|{label}| {_nid(dst)}')
        else:  # half-edge (only one endpoint) — render as a dangling annotation
            endpoint = src if src is not None else dst
            lines.append(f'  {_nid(endpoint)} -.->|{label}| {_nid(endpoint)}')
    lines.append("```")
    return "\n".join(lines)


VIEWS = {
    "status": status_table,
    "graph": claim_graph,
}
