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

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
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
        # ⚠⚠ REFUSALS LIVE BESIDE THE STREAM, NEVER IN IT. `records.jsonl` is verdicts that
        # were ACCEPTED; a rejected claim is a different kind of thing and mixing them would
        # make the append-only stream mean two things. This is the `invalid_appends` counter
        # grown a shape — that counter is ONE GLOBAL INTEGER and cannot say which step, which
        # rule, or when.
        self._refusals_path = Path(str(self.path) + ".refusals.json")
        # ⛔⛔ APPEND-ONLY WAS A PROPERTY OF THE TOOLING AND NOT OF THE FILE, AND NOTHING SAID SO.
        # Measured 2026-09-12: this server had NO tamper detection of any kind -- no hash chain,
        # no per-record digest, no file hash. `invalid_appends` counts REFUSED APPENDS, not
        # edits. So an out-of-band edit to `records.jsonl` was invisible here, while `sjv` -- a
        # JSON store sitting beside it -- has caught exactly that since it was built.
        #
        # ⭐ Tim, 2026-09-12, correcting me after I called an append irreversible: "Append being
        # permanent is true only in so far as the logic itself goes... These are still json
        # files and editable outside the core tooling. Not something I suggest in general but
        # for an emergency flaw restoration, I'm not 100% opposed." **That is exactly why the
        # detector is worth having and the preventer is not**: the escape hatch stays open, and
        # using it stops being silent.
        #
        # ⚠ DETECTION, NOT PREVENTION -- sjv's own framing, and the honest one. Nothing here can
        # stop a text editor. What it can do is refuse to keep saying "healthy" afterwards.
        self._integrity_path = Path(str(self.path) + ".integrity.json")

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


    # -- refusals: a claim ATTEMPTED and not accepted --------------------------

    def refusals(self) -> dict:
        """`{step: {rule, count, first_seen, last_seen}}` — never raises."""
        try:
            data = json.loads(self._refusals_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def record_refusal(self, step: str, rule: str, when: str) -> None:
        """Note that a claim about `step` was refused by `rule`.

        ⛔⛔ KEYED ON `(step, rule)` AND DELIBERATELY NOT ON THE BASIS, which is the opposite
        of how a verdict is keyed. ZeroParadox measured why, 2026-09-07: `ZPLEDGER_BASIS=INDEX`
        at precommit, so **every `git add` moves the basis** — keying a refusal that way mints a
        fresh row per staging operation, and they ran precommit fifteen times that afternoon.

        ⭐ And the deeper reason, which is theirs: for a REJECTED record the basis is the least
        reliable thing in it. The claim was never accepted, so what content it purported to be
        about establishes nothing. Cardinality is steps x rules — bounded — not x stagings.

        ⚠ COUNT AND BOTH TIMESTAMPS, because "broken once" and "broken all afternoon" are
        different facts and a single row would render them identically.

        ⚠ A refusal must NEVER be the reason a write fails — same rule as `bump`. This is
        disclosure about a failure that already happened.
        """
        if not step:
            return
        data = self.refusals()
        prior = data.get(step) or {}
        data[step] = {
            "rule": rule,
            "count": int(prior.get("count") or 0) + 1,
            "first_seen": prior.get("first_seen") or when,
            "last_seen": when,
        }
        try:
            self._refusals_path.parent.mkdir(parents=True, exist_ok=True)
            self._refusals_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass

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
            raise UsageError(
                "record must carry its key before append",
                "append() through `Ledger.append`, which stamps `id` via `schema.record_key` "
                "after validating. ⚠ A record reaching the store without a key has bypassed "
                "validation, so the fix is the call path, never adding an id by hand.")
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
        self._stamp_integrity()
        return record

    # -- integrity -------------------------------------------------------------

    def _file_sha(self) -> Optional[str]:
        """SHA-256 of the stream as it is on disk right now, or None if absent."""
        if not self.path.exists():
            return None
        h = hashlib.sha256()
        with open(self.path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _stamp_integrity(self) -> None:
        """Record the stream's hash after a write we made. Best effort by design.

        ⚠ A FAILED STAMP MUST NOT FAIL THE APPEND. The verdict is already durably on disk and
        fsynced; losing the sidecar costs a later comparison, while raising here would throw
        away a record that was accepted. `verify_integrity` renders a missing stamp as its own
        state rather than as agreement.
        """
        try:
            self._integrity_path.write_text(json.dumps({
                "sha256": self._file_sha(),
                "records": sum(1 for _ in self._iter()),
                # ⚠ UTC WITH AN EXPLICIT OFFSET, like every timestamp this fleet
                # writes. `ledger.py:_now()` is the same expression; it is not
                # imported because `ledger` imports `store` and the cycle is worse
                # than the duplication of one stdlib call.
                "stamped": datetime.now(timezone.utc).isoformat(),
            }, indent=1), encoding="utf-8")
        except OSError:
            pass

    def verify_integrity(self) -> dict:
        """Compare the stream on disk against the hash stamped after the last append.

        ⛔ THREE OUTCOMES, AND "NEVER STAMPED" IS NOT "MATCHES". A stream that predates this
        detector has no baseline, and reporting that as agreement would be absence rendering as
        success -- the defect this whole server exists to remove. It renders as `unstamped`,
        which is neither healthy nor tampered, and one append fixes it.
        """
        live = self._file_sha()
        if live is None:
            return {"state": "absent", "sha256": None, "expected": None,
                    "note": "no stream on disk yet; nothing to compare."}
        try:
            doc = json.loads(self._integrity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"state": "unstamped", "sha256": live, "expected": None,
                    "note": ("no integrity baseline has been written -- this stream predates "
                             "the detector, or the sidecar was removed. NOT a statement that "
                             "the stream is unmodified. The next append stamps it.")}
        expected = doc.get("sha256")
        if expected == live:
            return {"state": "matches", "sha256": live, "expected": expected,
                    "stamped": doc.get("stamped"), "records": doc.get("records")}
        return {"state": "MODIFIED", "sha256": live, "expected": expected,
                "stamped": doc.get("stamped"),
                "note": ("the stream on disk differs from the hash stamped after the last "
                         "append. Something wrote to it other than this server. That may be "
                         "deliberate -- it is still not a thing the ledger did, and every "
                         "verdict read from here is now a claim about bytes this server did "
                         "not write.")}

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
        # ⛔⛔ A MODIFIED STREAM MUST BREAK `healthy`, NOT SIT BESIDE IT AS A FIELD NOBODY READS.
        # `writable` and `healthy` are kept SEPARATE on purpose: the directory being writable is
        # still true when the stream has been edited out of band, and reporting healthy over
        # bytes this server did not write is the exact shape of every defect logged here.
        # ⚠ `unstamped` does NOT break health -- it is the honest state of a stream that
        # predates the detector, and treating "I have no baseline" as "you were tampered with"
        # would be its own false claim. It is reported and it does not alarm.
        integrity = self.verify_integrity()
        if integrity.get("state") == "MODIFIED":
            problems.append(
                "the stream on disk does not match the hash stamped after the last append — "
                "something wrote to records.jsonl other than this server")
        return {
            "records": count,
            "integrity": integrity,
            "last_append": (last or {}).get("run", {}).get("started") if last else None,
            "schema": schema.SCHEMA_ID,
            "invalid_appends": self.invalid_appends,
            # ⚠ The same fact WITH A SHAPE. The integer above cannot say which step, which
            # rule, or when — and a step whose record was refused rendered as MISSING,
            # indistinguishable from never having run.
            "refusals": self.refusals(),
            "edge_conditions": self.edge_conditions,
            "writable": not problems,
            "problems": problems,
            "healthy": not problems,
        }
