"""Two audit appends must never be inside the file at the same time.

Measured 2026-11-11 14:32:09 UTC: two `ledger_subjects` calls 2 ms apart both wrote at the same
end offset of git_ops.jsonl. One row was lost and a 4-byte `}}` fragment was left on a line of
its own, after which every full read of the audit raised `JSONDecodeError`.

⚠ The OS-level race is too narrow to reproduce on demand, so the first test checks the property
the fix provides, MUTUAL EXCLUSION, directly. It holds every write open long enough that any
overlap is certain, using a separate AuditLog per thread the way the per-call engine does.
The second test is a real-file stress run with a FLOOR on the parsed count, so a run that wrote
nothing cannot pass.
"""

import json
import threading
import time

from core.audit import AuditLog
import mcpcommon.appendlog as audit_mod  # the gate AuditLog writes through


def _row(log: AuditLog, i: int) -> None:
    log.append(actor="mcp", op="ledger_subjects", args={"i": i}, decision="allowed")


def test_no_two_appends_are_in_the_file_at_once(tmp_path, monkeypatch):
    path = tmp_path / "git_ops.jsonl"
    real_open = open
    inside = 0
    peak = 0
    guard = threading.Lock()

    class _Slow:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            nonlocal inside, peak
            with guard:
                inside += 1
                peak = max(peak, inside)
            self.fh.__enter__()
            return self

        def write(self, s):
            time.sleep(0.02)
            return self.fh.write(s)

        def __exit__(self, *exc):
            nonlocal inside
            r = self.fh.__exit__(*exc)
            with guard:
                inside -= 1
            return r

    def slow_open(p, mode="r", *a, **kw):
        fh = real_open(p, mode, *a, **kw)
        return _Slow(fh) if "a" in mode else fh

    monkeypatch.setattr(audit_mod, "open", slow_open, raising=False)

    n = 12
    threads = [threading.Thread(target=_row, args=(AuditLog(path), i)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak == 1, f"{peak} appends were inside the audit file at once"
    rows = AuditLog(path).read()
    assert len(rows) == n


def test_concurrent_appends_all_parse(tmp_path):
    path = tmp_path / "git_ops.jsonl"
    n_threads, per = 16, 40

    def burst(t):
        for i in range(per):
            _row(AuditLog(path), t * 1000 + i)

    threads = [threading.Thread(target=burst, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == n_threads * per          # floor AND exact: nothing lost
    ids = {json.loads(l)["args"]["i"] for l in lines}
    assert len(ids) == n_threads * per
