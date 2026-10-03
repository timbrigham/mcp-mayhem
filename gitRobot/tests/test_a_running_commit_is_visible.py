"""A commit that is running SAYS SO — the same visibility merge got in 060c77f, minus the lock.

⭐ Tim, 2026-10-03: "Sure, I like consistency." Before this a commit wrote its only audit row at the
end, so a restart's in-flight check could not see one — measured that day: the audit read idle
while a consumer `hooks.py pre-commit` ran as a gitRobot child.

⚠ UNLIKE MERGE, NO LOCK. Concurrent commits in different worktrees are routine (a consumer corpus
agent and the main checkout committing at once), so a second commit must NOT be refused.
"""

import threading
from pathlib import Path

import pytest


def _stage(robot, repo, name="c.txt"):
    (repo / name).write_bytes(name.encode())
    robot.stage([name])


def _msg(tmp_path):
    m = tmp_path / "m.txt"
    m.write_bytes(b"m\n")
    return str(m)


def test_started_row_precedes_the_gate_and_the_terminal_row_pairs_by_run_id(
        robot, repo, tmp_path, fake_gate, monkeypatch):
    _stage(robot, repo)
    real, seen = robot.gates.run, {}

    def peek(phase, **kw):
        seen["row"] = [r for r in robot.audit.read() if r.get("op") == "commit"][-1]
        seen["flight"] = robot.in_flight()["commit"]
        return real(phase, **kw)

    monkeypatch.setattr(robot.gates, "run", peek)
    out = robot.commit(_msg(tmp_path))

    assert seen["row"]["decision"] == "started", "the started row must exist BEFORE the gate"
    assert seen["flight"]["state"] == "running", seen["flight"]
    rows = [r for r in robot.audit.read() if r.get("op") == "commit"]
    assert rows[-1]["decision"] == "allowed"
    assert rows[-1]["run_id"] == rows[-2]["run_id"] == seen["row"]["run_id"] == out["run_id"]
    assert robot.commit_status()["state"] == "concluded"


def test_a_failing_gate_row_carries_the_run_id(robot, repo, tmp_path, fake_gate):
    from core.errors import RefusalError
    fake_gate(1)
    _stage(robot, repo)
    with pytest.raises(RefusalError):
        robot.commit(_msg(tmp_path))
    rows = [r for r in robot.audit.read() if r.get("op") == "commit"]
    assert rows[-1]["decision"] == "refused" and rows[-2]["decision"] == "started"
    assert rows[-1]["run_id"] == rows[-2]["run_id"]
    assert robot.commit_status()["state"] == "concluded"


def test_a_commit_that_dies_mid_gate_reads_died(robot, repo, tmp_path, fake_gate, monkeypatch):
    _stage(robot, repo)

    def die(phase, **kw):
        raise RuntimeError("process killed mid-gate (simulated restart)")

    monkeypatch.setattr(robot.gates, "run", die)
    with pytest.raises(RuntimeError):
        robot.commit(_msg(tmp_path))
    st = robot.commit_status()
    assert st["state"] == "died", st
    assert robot.in_flight()["commit"]["state"] == "died"


def test_concurrent_commits_are_NOT_serialised(robot, repo, tmp_path, fake_gate, monkeypatch):
    """⚠ The difference from merge. Two commits in flight at once must both run; a lock here
    would stall a consumer's parallel worktree commits behind each other."""
    from core.engine import GitRobot
    wt = Path(robot.worktree("add", ref="HEAD")["path"])
    real = robot.gates.run
    both_in, release = threading.Barrier(2, timeout=30), threading.Event()
    seen = {}

    def slow(phase, **kw):
        both_in.wait()                       # deadlocks (and times out) if commits serialise
        seen.setdefault("flight", robot.in_flight()["commit"])
        assert release.wait(30)
        return real(phase, **kw)

    monkeypatch.setattr(robot.gates, "run", slow)
    import core.engine as engine_mod

    class SlowGates(engine_mod.Gates):
        def run(self, phase, **kw):
            return slow(phase, **kw)

    monkeypatch.setattr(engine_mod, "Gates", SlowGates)
    (wt / "w.txt").write_bytes(b"w")
    robot.stage(["w.txt"], worktree=str(wt))
    _stage(robot, repo, "main.txt")
    results = {}
    ts = [threading.Thread(target=lambda: results.update(main=robot.commit(_msg(tmp_path)))),
          threading.Thread(target=lambda: results.update(
              wt=robot.commit(_msg(tmp_path), worktree=str(wt))))]
    for t in ts:
        t.start()
    try:
        for _ in range(300):
            if "flight" in seen:
                break
            threading.Event().wait(0.05)
    finally:
        release.set()
        for t in ts:
            t.join(60)
    assert seen["flight"]["state"] == "running"
    assert results["main"]["decision"] == "allowed" and results["wt"]["decision"] == "allowed"
    robot.worktree("remove", name=str(wt))
