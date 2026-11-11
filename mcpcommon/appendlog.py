"""The ONE way any server in this fleet appends a line to a file.

⛔⛔ WHY THIS EXISTS. Measured 2026-11-11 14:32:09 UTC on gitRobot: two `ledger_subjects` calls
2 ms apart each opened `git_ops.jsonl` in append mode and wrote at the SAME end offset. On Windows,
append mode is seek-to-end-then-write, which is not atomic across separate handles. The 850-byte
row overwrote the 854-byte row and left that row's last 4 bytes, `}}\\r\\n`, as a line of its own.
One audit row was lost, and every full read of the log raised `JSONDecodeError` until the fragment
was removed by hand (#sudo, Tim, same day).

The servers run sync tool handlers on a thread pool (`anyio.to_thread`), so ANY handler that
appends can overlap any other. gitRobot's `tool_calls.jsonl` writer already had a lock. Its audit
log, one file over and the more important of the two, did not. A per-site lock is a rule with one
copy per site, and the copy that was missing is the one that broke. So the lock lives HERE, once,
and `verdictLedger/tests/test_one_append_path.py` fails when any server appends some other way.

SCOPE: one lock per resolved path, per PROCESS. Tim, 2026-11-11: every writer of these files is
inside its own server process, so a cross-process lock is not needed. If that ever stops being
true, this is the one place to change.

Bytes, not text: the caller's line is written exactly as given, so no platform newline translation
happens here (text mode on Windows had been turning `\\n` into `\\r\\n` in some logs and not
others).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def lock_for(path: str | os.PathLike) -> threading.Lock:
    """The process-wide lock for this file. Exposed for callers that must hold it across a
    read-then-append (e.g. a header written only if absent); otherwise use `append_line`."""
    key = os.path.normcase(str(Path(path).resolve()))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def append_line(path: str | os.PathLike, line: str | bytes, *, fsync: bool = False,
                _locked: bool = False) -> None:
    """Append `line` to `path` as one write, under the file's lock.

    `line` must already end with its newline; it is written byte-for-byte. `fsync=True` for
    files whose durability is the product (the verdict ledger). `_locked=True` only when the
    caller already holds `lock_for(path)`.
    """
    data = line.encode("utf-8") if isinstance(line, str) else line
    p = Path(path)
    if _locked:
        _write(p, data, fsync)
        return
    with lock_for(p):
        _write(p, data, fsync)


def _write(p: Path, data: bytes, fsync: bool) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab") as fh:  # appendlog: the one sanctioned append
        fh.write(data)
        if fsync:
            fh.flush()
            os.fsync(fh.fileno())
