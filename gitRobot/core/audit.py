"""Append-only operation log — one record per mutating call, ALLOWED OR REFUSED.

⚠ The "or refused" half is the point, and it comes from a defect measured in the
consumer project: its push gate spends real time and real money per run and
writes no file at all when everything passes, because it only writes on a
finding. Afterwards, *"judged clean"* and *"never ran"* are indistinguishable —
and that is exactly the state in which a control quietly stops working.

So: every Tier 1 and Tier 2 call appends a line, whatever the outcome. A refusal
is as much a fact about what happened as a push is.

Tier 3 reads are NOT audited. They change nothing, and the volume would bury the
signal this log exists to keep.

Same shape and discipline as the sibling registry's audit sidecar: JSONL, one
record per line, never mutated, never rewritten.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def append(
        self,
        *,
        actor: str,
        op: str,
        args: Any,
        decision: str,
        head: Optional[str] = None,
        branch: Optional[str] = None,
        tree: Optional[dict] = None,
        gates: Optional[list[dict]] = None,
        reason: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> dict:
        """Append one immutable record and return it.

        ``decision`` is one of ``allowed`` / ``refused`` / ``failed``:
        allowed = the mutation ran; refused = policy said no and nothing ran;
        failed = policy allowed it and git or a gate rejected it.
        """
        record = {
            "ts": _now_iso(),
            "actor": actor,
            "op": op,
            "args": args,
            "decision": decision,
            "head": head,
            "branch": branch,
            "tree": tree,
            "gates": gates or [],
            "reason": reason,
            "detail": detail,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def read(self, limit: Optional[int] = None) -> list[dict]:
        if not self.path.exists():
            return []
        records: list[dict] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records[-limit:] if limit else records

    def last_where(self, **match: Any) -> Optional[dict]:
        """The most recent record matching every given field. Used by the push
        gate to find a passing preflight for the current HEAD."""
        for record in reversed(self.read()):
            if all(record.get(k) == v for k, v in match.items()):
                return record
        return None
