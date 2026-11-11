"""Every server appends to a file through `mcpcommon/appendlog.py`, and only through it.

Measured 2026-11-11 14:32:09 UTC: two gitRobot calls 2 ms apart appended to `git_ops.jsonl` at
the same offset. One row was lost and a `}}` fragment broke every full read of the audit. The
sibling `tool_calls.jsonl` writer had a lock; the audit writer did not. Tim's ruling the same day:
route every append through one locking gate. This test is what keeps it ONE: it fails on any
append-mode open anywhere in server code except the gate itself.

Lives in verdictLedger's suite beside the other fleet-wide checks because there is no repo-level
suite, and this one is the cheap one to run.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", ".claude", ".mcp-local", "tests", "__pycache__", ".venv", "venv",
             "examples", ".pytest_cache"}

# An append-mode open: open(...,"a"/"ab"/"a+"/"a+b"/"at"...) or Path.open("ab"), or mode=.
APPEND_OPEN = re.compile(
    r"""(?:\bopen|\.open)\s*\([^)]*?['"]a[bt+]*b?['"]""")
O_APPEND = re.compile(r"\bos\.O_APPEND\b")  # code, not prose that mentions it

# (file, text that must appear on the line, why). Scoped to the LINE'S CONTENT, never the
# whole file, so an exemption cannot cover a second append added beside it.
EXEMPT = [
    ("mcpcommon/appendlog.py", "appendlog: the one sanctioned append",
     "the gate itself"),
    ("publishRobot/publish_core/engine.py", 'queue.lock", "a+b"',
     "a cross-process LOCK FILE: opened to take msvcrt/fcntl locks, never written to"),
]


def _server_sources() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in rel):
            continue
        out.append(p)
    return out


def _append_sites() -> list[tuple[str, int, str]]:
    hits = []
    for p in _server_sources():
        rel = p.relative_to(ROOT).as_posix()
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            code = line.split("#", 1)[0] if "appendlog:" not in line else line
            if APPEND_OPEN.search(code) or O_APPEND.search(code):
                hits.append((rel, n, line.strip()))
    return hits


def _exempt(rel: str, line: str) -> bool:
    return any(rel == f and needle in line for f, needle, _ in EXEMPT)


def test_the_scan_sees_the_fleet():
    # ⚠ FLOOR: a scan that found nothing passes the next test vacuously.
    files = _server_sources()
    assert len(files) > 50, f"only {len(files)} source files scanned from {ROOT}"
    sites = _append_sites()
    rels = {r for r, _, _ in sites}
    # The gate's own open MUST be found, or the pattern has stopped matching appends at all.
    assert "mcpcommon/appendlog.py" in rels, sites


def test_no_append_outside_the_gate():
    bad = [s for s in _append_sites() if not _exempt(s[0], s[2])]
    assert not bad, (
        "append-mode open outside mcpcommon/appendlog.py — route it through "
        "append_line() (or lock_for() + append_line(_locked=True) for read-then-append):\n"
        + "\n".join(f"  {r}:{n}: {t}" for r, n, t in bad))


def test_every_exemption_still_matches_a_line():
    # One-directional exemptions sit forever after their line is gone.
    sites = _append_sites()
    for f, needle, why in EXEMPT:
        assert any(r == f and needle in t for r, _, t in sites), f"stale exemption: {f} ({why})"


def test_the_gate_serialises_concurrent_appends(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT))
    from mcpcommon.appendlog import append_line

    path = tmp_path / "log.jsonl"
    n_threads, per = 16, 40

    def burst(t):
        for i in range(per):
            append_line(path, f'{{"t": {t}, "i": {i}, "pad": "{"x" * 700}"}}\n')

    threads = [threading.Thread(target=burst, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    import json
    lines = [l for l in path.read_bytes().split(b"\n") if l]
    assert len(lines) == n_threads * per
    assert len({(d["t"], d["i"]) for d in map(json.loads, lines)}) == n_threads * per
