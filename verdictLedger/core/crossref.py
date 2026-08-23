"""P1–P4: join what was DECIDED against what was DONE.

`gitRobot` keeps `git_ops.jsonl` — every mutating call, allowed or refused. This
ledger keeps the verdicts. Neither alone proves anything; joined, they do.

⭐ P4 closes `GRB-2` from the other side. A `preflight` whose transport dropped left
no verdict AND no audit row, so "it failed" and "it never ran" were
indistinguishable. With two streams that must agree, a missing row on one side is
detectable from the other — neither store can be fixed into silence, because the
other one still remembers.

⚠⚠ AN ABSENT OR EMPTY AUDIT STREAM IS A FINDING, NOT A CLEAN BILL. The two paths
are configured independently (`ZPLEDGER_GITOPS` here, `GITROBOT_DATA` there). If
they drift, a naive join finds zero violations and reports clean — the empty-stream
fail-open, one level up. So "no data" is reported as its own state and never as
"no violations".

⚠ It lives HERE and not in gitRobot: a store must not be the sole auditor of its
own completeness.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def default_gitops_path() -> Path:
    return Path(os.environ.get(
        "ZPLEDGER_GITOPS",
        Path(__file__).resolve().parents[2] / "gitRobot" / "data" / "git_ops.jsonl"))


def _genesis_floor(records: list) -> Optional[str]:
    """The timestamp from which the four properties apply.

    ⚠ A point in TIME, not a commit match. gitRobot stamps the CURRENT head on
    every audit row including refusals, so matching on the genesis sha flipped the
    floor open on the first row and claimed every prior mutation as an orphan —
    48 unactionable findings on the first run, which is precisely the warning
    people learn to scroll past.
    """
    for r in records:
        if r.get("step") == "genesis":
            return (r.get("run") or {}).get("started")
    return None


def check(*, records: list, gitops_path=None, genesis: Optional[str] = None,
          since: Optional[str] = None) -> dict:
    path = Path(gitops_path or default_gitops_path())
    ops = _read_jsonl(path)

    if not path.exists():
        return {"ok": False, "no_data": True, "gitops_path": str(path),
                "note": ("gitRobot's audit stream is NOT PRESENT at this path. This is a "
                         "finding, not a pass: the two paths are configured independently "
                         "(ZPLEDGER_GITOPS / GITROBOT_DATA) and a drift would otherwise "
                         "report clean."),
                "violations": []}
    if not ops:
        return {"ok": False, "no_data": True, "gitops_path": str(path),
                "note": ("gitRobot's audit stream is EMPTY. Zero violations here means "
                         "zero data, which is not the same as agreement."),
                "violations": []}

    mutations = [o for o in ops if o.get("decision") == "allowed"
                 and o.get("op") in ("commit", "push", "tag_create")]
    if since:
        mutations = [o for o in mutations if (o.get("ts") or "") >= since]

    # The genesis floor: crossref claims nothing before recording began.
    floor = _genesis_floor(records)
    if floor:
        mutations = [o for o in mutations if (o.get("ts") or "") >= floor]
    violations = []

    record_bases = {(r.get("basis") or {}).get("value") for r in records}
    record_inventories = {(r.get("run") or {}).get("id") for r in records}

    for op in mutations:
        head = op.get("head")
        inv = (op.get("args") or {}).get("inventory_id") or op.get("inventory_id")
        tree = (op.get("args") or {}).get("tree")

        # P1 — a mutation whose content no step examined.
        if op["op"] == "commit":
            if tree is None and inv is None:
                violations.append({
                    "property": "P1", "op": op["op"], "head": head, "ts": op.get("ts"),
                    "detail": ("the commit row records neither its tree nor an "
                               "inventory id, so no join to a verdict is possible. "
                               "gitRobot must capture both.")})
            elif tree is not None and tree not in record_bases:
                violations.append({
                    "property": "P1", "op": op["op"], "head": head, "ts": op.get("ts"),
                    "detail": f"no record has basis {tree[:12]}… — code landed that "
                              f"no step examined"})

        # P2 — a push covered by working-tree records instead of the pushed range.
        if op["op"] == "push" and inv is None:
            violations.append({
                "property": "P2", "op": op["op"], "head": head, "ts": op.get("ts"),
                "detail": ("the push row names no inventory, so the scope it was "
                           "judged on cannot be checked against the range it pushed "
                           "(SCOPE-1)")})

        # P4, mutation -> record direction.
        if inv is not None and inv not in record_inventories:
            violations.append({
                "property": "P4", "op": op["op"], "head": head, "ts": op.get("ts"),
                "detail": f"names inventory/run {inv!r}, which the ledger has never seen"})

    # P3 — a verdict about a commit that does not exist.
    heads = {o.get("head") for o in ops}
    for r in records:
        basis = r.get("basis") or {}
        if basis.get("kind") == "ref" and basis.get("value") not in heads and r.get("step") != "genesis":
            violations.append({
                "property": "P3", "record": r.get("id"), "step": r.get("step"),
                "detail": f"basis ref {str(basis.get('value'))[:12]}… appears in no "
                          f"audit row — a verdict about nothing"})

    return {"ok": not violations, "no_data": False, "gitops_path": str(path),
            "mutations_checked": len(mutations), "records_checked": len(records),
            "genesis": genesis, "genesis_floor": floor,
            "note": (None if floor else
                     "NO GENESIS RECORD — the floor is unset, so every historical "
                     "mutation is reported. Seed one with genesis(<sha>)."),
            "violations": violations}
