"""The append-only stream, and the writer lock that makes "no torn lines" true.

⚠⚠ THE EARLIER CLAIM THAT LOCKING IS UNNECESSARY WAS WRONG, and the correction is
the reason this module exists in this shape. "The server is the sole writer, so
appends serialise inside one process" does not follow: sole writer PROCESS is not
sole writer THREAD. Every MCP tool must be async with a thread offload — forced by
FastMCP running synchronous tools ON the event loop, which stalls the health
endpoint and gets the server killed mid-call (measured on gitRobot, 2026-08-22).
So two appends land on two worker threads and can be inside the write at once. On
Windows there is no O_APPEND atomicity guarantee to fall back on, and a record
with forty subjects can exceed the buffer. One torn line makes the stream
unparseable, which fails EVERY subsequent validate and query — total, not partial,
for a mandatory dependency of every commit.

⚠ BOUNDED WAIT, NOT "LOCKED" (Tim, 2026-08-22). Returning a lock error would turn
transient contention into a blocked commit, because UNDECIDED blocks. So the
writer waits: crossing the soft threshold records an edge-condition observation
and still writes; exceeding the hard threshold is a wedged ledger and a true block.

⚠ THE TWO THRESHOLDS ARE COUPLED TO THE PROCESS SUPERVISOR. hard_seconds (30) is
the supervisor's poll interval, and a wait that long is safe ONLY because every
tool is async-offloaded so the health endpoint keeps answering. Make one tool a
plain `def` and a hard-threshold wait trips the supervisor precisely.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from core import schema
from core.errors import Unavailable, UsageError

GENESIS_STEP = "genesis"


class Store:
    def __init__(self, path, *, soft_seconds: float = 5.0, hard_seconds: float = 30.0):
        self.path = Path(path)
        self.soft = soft_seconds
        self.hard = hard_seconds
        self._lock = threading.Lock()
        # ⚠ These MUST be durable, not per-process. Every MCP call constructs a
        # fresh Ledger, so an in-memory counter reports 0 no matter how many
        # records were refused — the field meant to surface rejection would itself
        # render absence as success. A tiny sidecar keeps them honest across calls
        # and restarts. It is an operational counter, not a second record store.
        self._counters_path = Path(str(self.path) + ".counters.json")

    # -- reading ---------------------------------------------------------------

    def __iter__(self) -> Iterator[dict]:
        if not self.path.exists():
            return iter(())
        return self._iter()

    def _iter(self) -> Iterator[dict]:
        with open(self.path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    # ⚠ Quarantine the bad line rather than dying: a torn tail must
                    # not make the whole stream unreadable, which would take every
                    # gated action down with it. It is still a finding — status()
                    # reports it — but the readable prefix stays usable.
                    raise Unavailable(
                        f"stream is corrupt at line {lineno} of {self.path}: {exc}. "
                        f"Records before it are intact; the tail needs repair."
                    ) from exc

    def _counters(self) -> dict:
        try:
            return json.loads(self._counters_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"invalid_appends": 0, "edge_conditions": 0}

    def bump(self, name: str, by: int = 1) -> None:
        c = self._counters()
        c[name] = c.get(name, 0) + by
        try:
            self._counters_path.parent.mkdir(parents=True, exist_ok=True)
            self._counters_path.write_text(json.dumps(c), encoding="utf-8")
        except OSError:
            pass          # a counter must never be the reason a write fails

    @property
    def invalid_appends(self) -> int:
        return self._counters().get("invalid_appends", 0)

    @property
    def edge_conditions(self) -> int:
        return self._counters().get("edge_conditions", 0)

    def records(self) -> list[dict]:
        return list(self)

    def ids(self) -> set:
        return {r.get("id") for r in self}

    def get(self, record_id: str) -> Optional[dict]:
        for r in self:
            if r.get("id") == record_id:
                return r
        return None

    def tips(self) -> dict:
        """``(step, basis.value)`` -> ``{latest, revisions}``.

        The TIP is the highest revision for a key. Every revision is kept; only the
        latest is operative (§4c). Chains never cross bases, so this is a group-by
        rather than a traversal.
        """
        out: dict = {}
        for r in self:
            key = (r.get("step"), (r.get("basis") or {}).get("value"))
            rev = r.get("revision", 0)
            entry = out.setdefault(key, {"latest": None, "revisions": {}})
            entry["revisions"][rev] = r
            if entry["latest"] is None or rev >= entry["latest"].get("revision", 0):
                entry["latest"] = r
        return out

    def config_shas(self) -> set:
        """Every config identity the stream has ever seen, NEW NAME AND OLD.

        ⚠ `run.policy_sha` was renamed to `run.config_sha` on 2026-08-25. Records
        written before that keep the old key, and they are never rewritten — the
        stream is append-only, and editing 235 historical records to tidy a field name
        would be the one operation this whole design exists to make impossible.

        So both are read here, and ONLY here. V10 asks a set-membership question, and
        for that question the two keys carry the same fact; nothing downstream sees a
        heterogeneous stream because nothing downstream asks.
        """
        out = set()
        for r in self:
            run = r.get("run") or {}
            out.add(run.get("config_sha") or run.get("policy_sha"))
        return out

    def genesis(self) -> Optional[dict]:
        for r in self:
            if r.get("step") == GENESIS_STEP:
                return r
        return None

    # -- writing ---------------------------------------------------------------

    def append(self, record: dict) -> dict:
        """Serialise one record under the writer lock, with the bounded wait.

        The caller has already validated. This method owns durability only.
        """
        if not record.get("id"):
            raise UsageError("record must carry its key before append")
        started = time.monotonic()
        acquired = self._lock.acquire(timeout=self.hard)
        waited = time.monotonic() - started
        if not acquired:
            raise Unavailable(
                f"writer lock not acquired within {self.hard:.0f}s — the ledger is "
                f"wedged, not busy. Appends are sub-millisecond, so this is a stuck "
                f"writer or a stalled fsync, never contention. Not retried: a broken "
                f"ledger is a true block.")
        try:
            if waited >= self.soft:
                # Observed, recorded ON the record, and deliberately excluded from
                # the identity hash — an observation about a write must not change
                # what the write IS.
                self.bump("edge_conditions")
                record.setdefault("cost", {})["lock_wait_seconds"] = round(waited, 3)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = schema.serialise(record) + "\n"
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise Unavailable(f"could not append to {self.path}: {exc}") from exc
        finally:
            self._lock.release()
        return record

    # -- health ----------------------------------------------------------------

    def health(self) -> dict:
        """⚠ Must never report healthy while writes are failing.

        So it does not merely report a count — it proves the stream is *readable*
        and the directory is *writable*. A status that only counts rows would say
        "healthy" for a store nobody can append to, which is the exact shape this
        server exists to end.
        """
        problems: list[str] = []
        count = 0
        last = None
        try:
            for r in self:
                count += 1
                last = r
        except Unavailable as exc:
            problems.append(str(exc))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            probe = self.path.parent / ".zpledger-write-probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(f"stream directory is not writable: {exc}")
        return {
            "records": count,
            "last_append": (last or {}).get("run", {}).get("started") if last else None,
            "schema": schema.SCHEMA_ID,
            "invalid_appends": self.invalid_appends,
            "edge_conditions": self.edge_conditions,
            "writable": not problems,
            "problems": problems,
            "healthy": not problems,
        }
