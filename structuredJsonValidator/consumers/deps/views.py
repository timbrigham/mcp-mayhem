"""Projections over the declaration dependency graph (interop issue #13).

Only a convenience ``cycles`` view — acyclicity is deliberately NOT a store
invariant (Lean ``mutual`` blocks are legitimate, and full topological validation
on every write is expensive). This view SURFACES any directed cycle (a strongly-
connected component with >1 node, or a self-loop) so ZP can inspect the expected
``mutual`` blocks; it gates nothing. Output is deterministic (components and their
members sorted) for clean diffs.
"""

from __future__ import annotations


def _tarjan_sccs(nodes: list, adj: dict) -> list[list]:
    """Iterative Tarjan strongly-connected components. Iterative (not recursive)
    so a large graph can't blow the Python stack. Deterministic given sorted
    inputs."""
    index_of: dict = {}
    low: dict = {}
    on_stack: set = set()
    stack: list = []
    sccs: list[list] = []
    counter = 0

    for root in nodes:
        if root in index_of:
            continue
        # work stack of (node, neighbor-iterator-position)
        work = [(root, 0)]
        while work:
            node, pi = work[-1]
            if pi == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            neighbors = adj.get(node, ())
            if pi < len(neighbors):
                work[-1] = (node, pi + 1)
                nxt = neighbors[pi]
                if nxt not in index_of:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
            else:
                if low[node] == index_of[node]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    sccs.append(sorted(comp))
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
    return sccs


def cycles(document: dict, **_params) -> str:
    """List directed cycles: non-trivial SCCs (size > 1) and self-loops. These are
    the expected ``mutual`` blocks; the view is informational, not a gate."""
    edges = document.get("entries", [])
    adj: dict = {}
    nodes: set = set()
    self_loops: set = set()
    for e in edges:
        frm, to = e.get("from"), e.get("to")
        nodes.add(frm)
        nodes.add(to)
        if frm == to:
            self_loops.add(frm)
        adj.setdefault(frm, [])
        if to not in adj[frm]:
            adj[frm].append(to)
    for k in adj:
        adj[k].sort()

    sccs = [c for c in _tarjan_sccs(sorted(nodes), adj) if len(c) > 1]
    sccs.sort()

    total_cyclic = len(sccs) + len(self_loops)
    lines = [f"dependency cycles: {total_cyclic} "
             f"({len(sccs)} multi-node SCC(s), {len(self_loops)} self-loop(s)) "
             f"over {len(nodes)} nodes / {len(edges)} edges"]
    if not total_cyclic:
        lines.append("_(acyclic — no mutual blocks)_")
        return "\n".join(lines)
    lines.append("")
    for cid in sorted(self_loops):
        lines.append(f"- self-loop: {cid}")
    for i, comp in enumerate(sccs, 1):
        lines.append(f"- SCC {i} ({len(comp)} nodes): {', '.join(comp)}")
    return "\n".join(lines)


VIEWS = {
    "cycles": cycles,
}
