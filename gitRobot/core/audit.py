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
import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).resolve().parents[2]
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))
from mcpcommon.vocabulary import DECISIONS as _DECISIONS

from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# ⛔⛔ EVERY AUDIT ROW PASSES THROUGH `append`, WHICH IS WHY THE CHECK LIVES HERE AND NOT AT THE
# TWENTY-ODD CALL SITES. Measured 2026-09-10: `mcpcommon.vocabulary.DECISIONS` published four
# values while this server emitted FIVE -- `started`, written by both `preflight` and `push` and
# read back by `preflight_status`, appeared in no published list. Nothing could catch it because
# NOTHING BOUND THE TABLE TO THE CODE; the consolidation that fixed `error_type` did not reach
# `decision`, and the two look identical sitting in one dict.
#
# ⭐ Same shape as `_kind()` in errors.py, deliberately: raise rather than coerce, so a value this
# fleet has not published cannot reach an audit row that a caller will later enumerate.
def _decision(name: str) -> str:
    """The shared value, and a hard failure if this server invents one nobody published."""
    if name not in _DECISIONS:
        raise AssertionError(
            "decision %r is not in mcpcommon.vocabulary.DECISIONS. Add it there so every caller "
            "can enumerate what an audit row may say, rather than defining it here." % name)
    return name



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
        alternative: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> dict:
        decision = _decision(decision)
        """Append one immutable record and return it.

        ``decision`` is one of ``started`` / ``allowed`` / ``refused`` / ``failed``:
        started = the work was launched and its outcome is not yet known;
        allowed = it ran; refused = policy said no and nothing ran;
        failed = policy allowed it and git or a gate rejected it.

        ⚠ ``started`` exists because an outcome-only log cannot distinguish a run
        that FAILED from one that never happened. A long gate run was killed
        mid-flight by the process supervisor and left no trace at all — §7's own
        lesson ("judged clean" vs "never ran") recurring one door over. A start
        row plus ``pid`` makes an interrupted run detectable afterwards instead of
        invisible: a ``started`` row with no matching outcome, written by a pid
        that is no longer this process, is a run that died.

        ``alternative`` is persisted so a refusal's long form survives a restart —
        ``explain`` must not degrade to "the durable copy is the audit record"
        when the audit record is where it should have been all along.
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
            "alternative": alternative,
            "run_id": run_id,
            "pid": os.getpid(),
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
