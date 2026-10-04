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


# =================================================================================================
# THE STREAM CACHE — process-wide, per stream path. Tim, 2026-10-04: "the time is a factor of the
# storage of the verdict ledger. It's getting massive."
#
# ⛔ MEASURED THAT DAY: one `append` cost a median 15,080 ms (n=34) — validate re-parsed the whole
# 8,410-record stream FOUR times, the dedupe a fifth, and the receipt's `still_stale` disclosure
# then built a full inventory whose `_subject_index` folded every record again. 30 `inventory`
# calls inside one consumer routing-control run cost 268.7 s. Every cost was O(stream), per call.
#
# ⭐ THE DESIGN: records.jsonl STAYS THE ONLY TRUTH. This holds what a full pass would compute —
# the parsed records and every derived index — and keeps it current by folding ONLY the bytes
# appended since the last read. It is DISPOSABLE: any doubt rebuilds it from the file.
#   · a change is noticed by (size, mtime_ns); nothing changed -> no I/O at all
#   · on any change the ALREADY-INDEXED PREFIX is re-hashed; if it differs from what was indexed
#     (an out-of-band edit — Tim's emergency-restoration case) the whole cache rebuilds
#   · new records fold COPY-ON-WRITE into new structures, then publish atomically, so a reader
#     iterating the previous state can never see it change underneath it
#   · a corrupt line raises `Unavailable` exactly as the full pass did, and nothing is cached
#
# ⛔⛔ AND THE WRITER LOCK LIVES HERE, BECAUSE IT WAS PER-INSTANCE AND THEREFORE NO LOCK AT ALL.
# The server builds a fresh Ledger — and Store — for EVERY call, so `threading.Lock()` on the
# instance never serialised two appends arriving on two calls: exactly the torn-line race the
# module docstring says the lock exists to prevent. Found 2026-10-04 while building this, the
# same per-instance shape found in gitRobot the same night.
# =================================================================================================

_CACHES: dict = {}
_CACHES_LOCK = threading.Lock()


def _cache_for(path: Path) -> "_StreamCache":
    key = str(Path(path).resolve())
    with _CACHES_LOCK:
        c = _CACHES.get(key)
        if c is None:
            c = _CACHES[key] = _StreamCache(Path(key))
        return c


class _State:
    """One immutable-by-convention snapshot of everything a full pass derives."""
    __slots__ = ("records", "ids", "by_id", "tips", "config_shas", "steps_timing",
                 "genesis", "subject", "subject_n")

    def __init__(self):
        self.records: list = []
        self.ids: set = set()
        self.by_id: dict = {}
        self.tips: dict = {}
        self.config_shas: set = set()
        self.steps_timing: set = set()
        self.genesis: Optional[dict] = None
        # inventory._subject_index's 6-tuple, folded lazily, and HOW MANY of THIS state's records
        # it covers. ⚠ The count lives ON the state, never on the cache: a cache-level counter was
        # shared by every snapshot, so asking an older snapshot for its index could re-point the
        # counter and leave the current state folding the wrong slice. Per-state, every snapshot
        # is self-consistent by construction (and the fold is idempotent besides).
        self.subject = None
        self.subject_n = 0


class _StreamCache:
    def __init__(self, path: Path):
        self.path = path
        self.writer_lock = threading.Lock()      # THE writer lock — see the banner above
        self._refresh_lock = threading.Lock()
        self._sig = None                         # (size, mtime_ns) the state reflects
        self._offset = 0                         # bytes consumed
        self._lines = 0                          # physical lines consumed, for error messages
        self._prefix_sha: Optional[str] = None   # sha256 of bytes [0, _offset)
        self.state = _State()
        # The stream as THIS process last stamped it: (size, mtime_ns, sha256 hasher, records).
        # Lets an append stamp by extending a hash instead of re-reading ~250 MB, and tells the
        # pre-append check whether anything touched the file since. None = unknown (restart).
        self.stamp_known = None

    def current(self) -> _State:
        """The state for the file as it is NOW. Raises Unavailable on a corrupt line."""
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            with self._refresh_lock:
                self._reset()
            return self.state
        sig = (st.st_size, st.st_mtime_ns)
        if sig == self._sig:
            return self.state
        with self._refresh_lock:
            if sig == self._sig:
                return self.state
            data = self.path.read_bytes()
            prefix_ok = (self._prefix_sha is not None and len(data) >= self._offset
                         and hashlib.sha256(data[:self._offset]).hexdigest() == self._prefix_sha)
            if not prefix_ok:
                self._reset()
            new_recs, consumed, new_lines = self._parse(data, self._offset, self._lines)
            self.state = self._fold(self.state, new_recs)
            self._offset = consumed
            self._lines = new_lines
            self._prefix_sha = hashlib.sha256(data[:consumed]).hexdigest()
            # ⚠ the signature of the bytes READ, not a fresh stat: a write landing between the
            # stat and the read must be seen as a change on the next call, never skipped
            self._sig = (len(data), st.st_mtime_ns) if consumed == len(data) else None
            return self.state

    def _reset(self) -> None:
        self._sig, self._offset, self._lines, self._prefix_sha = None, 0, 0, None
        self.state = _State()

    def _parse(self, data: bytes, start: int, lineno0: int):
        """Records in data[start:], exactly as `Store._iter` would yield them."""
        out = []
        pos, lineno = start, lineno0
        n = len(data)
        while pos < n:
            nl = data.find(b"\n", pos)
            end = n if nl == -1 else nl + 1
            raw = data[pos:end]
            lineno += 1
            line = raw.decode("utf-8").strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise Unavailable(
                        f"stream is corrupt at line {lineno} of {self.path}: {exc}. "
                        f"Records before it are intact; the tail needs repair.") from exc
            pos = end
        return out, pos, lineno

    @staticmethod
    def _fold(prev: _State, new: list) -> _State:
        """prev + new, COPY-ON-WRITE: prev's structures are never mutated."""
        if not new:
            return prev
        s = _State()
        s.records = prev.records + new
        s.ids = set(prev.ids)
        s.by_id = dict(prev.by_id)
        s.tips = dict(prev.tips)
        s.config_shas = set(prev.config_shas)
        s.steps_timing = set(prev.steps_timing)
        s.genesis = prev.genesis
        s.subject, s.subject_n = prev.subject, prev.subject_n   # extended lazily
        copied = set()
        for r in new:
            rid = r.get("id")
            s.ids.add(rid)
            s.by_id.setdefault(rid, r)           # FIRST occurrence, as `Store.get` returns
            key = (r.get("step"), (r.get("basis") or {}).get("value"))
            rev = r.get("revision", 0)
            entry = s.tips.get(key)
            if key not in copied:
                entry = ({"latest": None, "revisions": {}} if entry is None else
                         {"latest": entry["latest"], "revisions": dict(entry["revisions"])})
                s.tips[key] = entry
                copied.add(key)
            entry["revisions"][rev] = r
            if entry["latest"] is None or rev >= entry["latest"].get("revision", 0):
                entry["latest"] = r
            if (r.get("cost") or {}).get("seconds") is not None:
                s.steps_timing.add(r.get("step"))
            run = r.get("run") or {}
            s.config_shas.add(run.get("config_sha") or run.get("policy_sha"))
            if s.genesis is None and r.get("step") == GENESIS_STEP:
                s.genesis = r
        return s

    def subject_index(self, state: _State):
        """inventory._subject_index over `state.records`, folded incrementally and shared."""
        from core import inventory as _inv
        with self._refresh_lock:
            base, done = state.subject, (state.subject_n if state.subject is not None else 0)
            if base is not None and done == len(state.records):
                return base
            idx = _inv._subject_index_fold(base, state.records[done:])
            state.subject, state.subject_n = idx, len(state.records)
            return idx


class _Records(list):
    """A records snapshot that knows which cache state it came from, so `_subject_index` can
    reuse the shared fold instead of re-walking every record."""
    __slots__ = ("_cache", "_state")


class Store:
    def __init__(self, path, *, soft_seconds: float = 5.0, hard_seconds: float = 30.0):
        self.path = Path(path)
        self.soft = soft_seconds
        self.hard = hard_seconds
        self._cache = _cache_for(self.path)
        # ⛔ THE PROCESS-WIDE writer lock for this stream — see the banner above _CACHES.
        self._lock = self._cache.writer_lock
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
        # served from the stream cache: same records, same order, same Unavailable on a
        # corrupt line — without re-parsing the whole file on every pass
        return iter(self._cache.current().records)

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

    def clear_refusal(self, step: str) -> bool:
        """Drop `step`'s refusal entry. True if one was there.

        ⛔⛔ THIS IS THE PRECONDITION `_sync_can_push` NAMED AND NOBODY HAD BUILT. That function
        has said since 2026-09-13: *"`refusals` DELIBERATELY NOT PASSED HERE... nothing ever
        clears it... Clear entries on a later accepted record first, then pass it."* Without
        clearing, wiring the sidecar into the push path would render nearly every row REFUSED
        with "do not re-run" — the wrong remedy for a step that simply has not run.

        ⭐ AN ACCEPTED RECORD IS THE EVIDENCE THAT THE EMITTER WAS FIXED. A refusal says a claim
        about this step was malformed; a later record the ledger ACCEPTED for the same step is
        the emitter demonstrating it no longer is. Nothing else can retire the entry honestly —
        time cannot, and a human clearing it by hand is the self-exemption this fleet refuses
        everywhere else.

        ⚠ KEYED ON STEP ALONE, matching `record_refusal`. Their 2026-09-07 measurement is why:
        `ZPLEDGER_BASIS=INDEX` means every `git add` moves the basis, so a basis-keyed refusal
        mints a row per staging operation. The clear must use the same key as the write or
        entries would accumulate under keys nothing retires.
        """
        data = self.refusals()
        if step not in data:
            return False
        data.pop(step, None)
        try:
            self._refusals_path.parent.mkdir(parents=True, exist_ok=True)
            self._refusals_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            return False      # same rule as `bump`: never the reason a write fails
        return True

    @property
    def invalid_appends(self) -> int:
        return self._counters().get("invalid_appends", 0)

    @property
    def edge_conditions(self) -> int:
        return self._counters().get("edge_conditions", 0)

    def records(self) -> list[dict]:
        state = self._cache.current()
        out = _Records(state.records)            # a fresh list: callers may extend/sort it
        out._cache, out._state = self._cache, state
        return out

    def subject_index(self, records=None):
        """The shared incremental `_subject_index` for `records` if it is a snapshot of the
        current state, else None (the caller then computes it from its own list)."""
        if isinstance(records, _Records) and len(records) == len(records._state.records):
            return records._cache.subject_index(records._state)
        return None

    def ids(self) -> set:
        return set(self._cache.current().ids)

    def get(self, record_id: str) -> Optional[dict]:
        return self._cache.current().by_id.get(record_id)

    def tips(self) -> dict:
        """``(step, basis.value)`` -> ``{latest, revisions}``.

        The TIP is the highest revision for a key. Every revision is kept; only the
        latest is operative (§4c). Chains never cross bases, so this is a group-by
        rather than a traversal.

        ⚠ Served from the stream cache and SHARED with other callers — read it, never
        mutate it. (Folded copy-on-write, so a later append never changes what you hold.)
        """
        return self._cache.current().tips

    def steps_timing(self) -> set:
        """Every step that has EVER reported `cost.seconds` — V22's memory.

        ⭐⭐ THE RATCHET IS DERIVED, NEVER DECLARED, and that choice is the whole design.
        Tim ruled 2026-09-26 that a save must not complete without a wall clock. Turning that
        into a hard rule the same day would have refused every append from ~30 gating steps —
        all 22 emit call sites route through one function in the consumer's `common.py`
        (`required.v2.json` says so in terms) — so every step would read MISSING and no push
        could happen until a file in another repo changed. **A rule that locks the fleet to
        acquire a field is a rule that gets switched off.**

        So the obligation is per-step and earned: a step that has PROVED it can report a
        wall clock may never stop. A step that never has is untouched and records exactly as
        before. There is no flag day, no outage, and no way to regress.

        ⛔ AND IT IS DERIVED FROM THE STREAM RATHER THAN LISTED IN CONFIG BECAUSE A LIST WOULD
        BE THE SECOND COPY. `config.py` forbids exactly that shape: the stream already carries
        which steps have reported, so a hand-maintained roster of converted steps could only
        ever disagree with it — and the disagreement would read as a policy decision.

        ⚠ THE CONSEQUENCE FOR AN EMITTER, AND IT IS THE ONE TRAP HERE: once a step reports
        seconds ONCE, EVERY emit path for that step must report it. A checker that passes a
        clock on its pass path and not on its fail path ratchets itself on the first pass and
        is refused on the next failure. Convert a step whole, not by branch.
        """
        return set(self._cache.current().steps_timing)

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
        return set(self._cache.current().config_shas)

    def genesis(self) -> Optional[dict]:
        return self._cache.current().genesis

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
            # ⛔⛔ CHECK, WRITE AND STAMP ALL HAPPEN UNDER THE WRITER LOCK. Measured 2026-10-04:
            # the stamp used to run AFTER the lock was released and re-hashed the whole ~250 MB
            # stream, so five agents appending within 6 s let an OLDER stamp land after NEWER rows
            # — the stamp lagged 5 records and the ledger reported MODIFIED with no outside writer
            # (proved from the 16:07Z/17:13Z git backups: byte-exact prefixes, every row
            # server-keyed). And every append re-stamped UNCONDITIONALLY, so a REAL out-of-band
            # edit would have been erased by the next append — a detector that forgets.
            pre = self._integrity_precheck()
            line = schema.serialise(record) + "\n"
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
            self._stamp_after_write(pre, line.encode("utf-8"))
        except OSError as exc:
            raise Unavailable(f"could not append to {self.path}: {exc}") from exc
        finally:
            self._lock.release()
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

    def _breaches_path(self) -> Path:
        return Path(str(self.path) + ".integrity-breaches.json")

    def breaches(self) -> list:
        try:
            data = json.loads(self._breaches_path().read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _record_breach(self, *, expected, found, size, stamped) -> None:
        """⭐ STICKY. A mismatch found at append time is written here and stays reported until a
        HUMAN acknowledges it (`acknowledge_breaches`). The next stamp never clears it — that was
        the defect: the evidence of an out-of-band edit lived only in a stamp the next append
        overwrote."""
        entries = self.breaches()
        entries.append({"detected": datetime.now(timezone.utc).isoformat(),
                        "expected_sha256": expected, "found_sha256": found,
                        "stream_bytes": size, "last_stamp": stamped, "acknowledged": None})
        try:
            self._breaches_path().write_text(json.dumps(entries, indent=1), encoding="utf-8")
        except OSError:
            pass

    def acknowledge_breaches(self, who: str, reason: str) -> int:
        """A HUMAN accepts the recorded breaches. Returns how many were acknowledged. The entries
        stay in the file — acknowledged, never deleted — so the history survives."""
        if not (who or "").strip() or not (reason or "").strip():
            raise UsageError("acknowledging an integrity breach needs a person and a reason",
                             "pass who=<the person accepting it> and reason=<why the bytes are "
                             "trusted>; an unattributed acknowledgement is indistinguishable "
                             "from the detector being switched off")
        entries, n = self.breaches(), 0
        for e in entries:
            if not e.get("acknowledged"):
                e["acknowledged"] = {"who": who, "reason": reason,
                                     "when": datetime.now(timezone.utc).isoformat()}
                n += 1
        self._breaches_path().write_text(json.dumps(entries, indent=1), encoding="utf-8")
        return n

    def _integrity_precheck(self):
        """Called UNDER the writer lock, before writing. Returns the hash state to extend, or
        None when stamping is impossible (the append still proceeds — a failed stamp must never
        lose an accepted record)."""
        try:
            known = self._cache.stamp_known
            try:
                st = os.stat(self.path)
            except FileNotFoundError:
                return {"hasher": hashlib.sha256(), "records": 0}
            if known and (st.st_size, st.st_mtime_ns) == (known[0], known[1]):
                return {"hasher": known[2].copy(), "records": known[3]}
            # Unknown state (a restart, or the file changed since OUR last stamp): hash it all
            # ONCE and compare with the stamp on disk.
            h = hashlib.sha256()
            with open(self.path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            live = h.hexdigest()
            try:
                doc = json.loads(self._integrity_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            if doc and doc.get("sha256") and doc["sha256"] != live:
                self._record_breach(expected=doc.get("sha256"), found=live, size=st.st_size,
                                    stamped=doc.get("stamped"))
            return {"hasher": h, "records": len(self._cache.current().records)}
        except Exception:                                   # noqa: BLE001 — never fail the append
            return None

    def _stamp_after_write(self, pre, line_bytes: bytes) -> None:
        """UNDER the writer lock: extend the hash with exactly the bytes written, and stamp.

        ⚠ A FAILED STAMP MUST NOT FAIL THE APPEND. The verdict is already durably on disk and
        fsynced; losing the sidecar costs a later comparison, while raising here would throw
        away a record that was accepted. `verify_integrity` renders a missing stamp as its own
        state rather than as agreement."""
        if pre is None:
            self._cache.stamp_known = None
            return
        try:
            h = pre["hasher"]
            h.update(line_bytes)
            count = pre["records"] + 1
            st = os.stat(self.path)
            self._integrity_path.write_text(json.dumps({
                "sha256": h.hexdigest(),
                "records": count,
                # ⚠ UTC WITH AN EXPLICIT OFFSET, like every timestamp this fleet
                # writes. `ledger.py:_now()` is the same expression; it is not
                # imported because `ledger` imports `store` and the cycle is worse
                # than the duplication of one stdlib call.
                "stamped": datetime.now(timezone.utc).isoformat(),
            }, indent=1), encoding="utf-8")
            self._cache.stamp_known = (st.st_size, st.st_mtime_ns, h.copy(), count)
        except Exception:                                   # noqa: BLE001
            self._cache.stamp_known = None

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
        # ⭐ STICKY: an unacknowledged breach keeps the state MODIFIED even when a later stamp
        # matches the file again — the next append must never be what clears the evidence.
        open_breaches = [b for b in self.breaches() if not b.get("acknowledged")]
        if open_breaches:
            return {"state": "MODIFIED", "sha256": live, "expected": expected,
                    "stamped": doc.get("stamped"), "breaches": open_breaches,
                    "note": (f"{len(open_breaches)} unacknowledged integrity breach(es): at append "
                             f"time the stream did not match the hash this server last stamped. "
                             f"Later stamps do NOT clear this. A person reviews the bytes and "
                             f"runs `python -m core.cli integrity-ack --who <name> --reason <why>`.")}
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
