"""Every gate record carries how long THAT gate ran, and says what the number prices.

⭐ Added 2026-10-03. Three consumer commits made a 300s client give up while every gate record but
one read a clean exit 0 — and nothing on this side could say whether the HOOK was slow or the CALL
was. A commit runs pre-commit twice (this gate, then git's own hook inside `git commit`), so the
number must price the gate phase alone and say so.
"""

from core import gates as gates_mod


def _hook(repo, body: bytes):
    entry = repo / "tools" / "verify" / "hooks.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes(body)


def test_a_gate_reports_its_own_duration(robot, repo):
    """The value, not presence: a 1.5 s hook must not report 0 or None, nor the whole call."""
    _hook(repo, b"import sys, time\ntime.sleep(1.5)\nsys.exit(0)\n")
    res = robot.gates.run("pre-commit")
    assert res.passed
    assert res.seconds is not None and 1.4 <= res.seconds < 15, res.seconds
    rec = res.record()
    assert rec["seconds"] == res.seconds
    assert "this gate phase only" in rec["seconds_prices"]


def test_a_gate_that_never_launched_has_no_duration(robot, repo):
    """⛔ None, not 0 — 0 would claim an instant pass for a gate that never ran."""
    res = robot.gates.run("pre-commit")          # no tools/verify/hooks.py in this fixture
    assert res.ran is False
    assert res.seconds is None
    assert res.record()["seconds"] is None


def test_a_timed_out_gate_still_says_how_long_it_ran(robot, repo, monkeypatch):
    _hook(repo, b"import time\ntime.sleep(30)\n")
    monkeypatch.setitem(gates_mod.PHASE_TIMEOUT, "pre-commit", 1)
    res = robot.gates.run("pre-commit")
    assert res.exit_code == 124
    assert res.seconds is not None and 0.9 <= res.seconds < 15, res.seconds


def test_the_commit_receipt_carries_the_gate_duration(robot, repo, tmp_path, fake_gate):
    (repo / "d.txt").write_bytes(b"d")
    robot.stage(["d.txt"])
    msg = tmp_path / "m.txt"
    msg.write_bytes(b"m\n")
    out = robot.commit(str(msg))
    g = out["gates"][0]
    assert isinstance(g["seconds"], float), g
    row = [r for r in robot.audit.read() if r["op"] == "commit"][-1]
    assert row["gates"][0]["seconds"] == g["seconds"], "the audit row must carry what the receipt does"
