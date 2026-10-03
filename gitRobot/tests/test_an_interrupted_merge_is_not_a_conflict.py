"""A merge that dies mid-gate is VISIBLE, and its leftover MERGE_HEAD is never called a conflict.

⛔ MEASURED 2026-10-03 12:37:56Z. A gitRobot restart killed a consumer merge during the pre-commit
gate. It had already run `merge --no-commit`, so MERGE_HEAD existed; merge wrote no audit row until
its end, so the dead call left NO trace; `in_flight` did not track merge, so the restart had nothing
to check. The retry 3 s later met "MERGE_HEAD exists", fell into the CONFLICT branch, aborted the
dead call's state by accident, and reported "did not apply cleanly" — the wrong remedy.

The kill is simulated by a gate that RAISES: the call dies after `merge --no-commit` and before any
terminal row, which is exactly the state a killed process leaves on disk.
"""

import subprocess

import pytest

from core.errors import RefusalError


def _git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), check=check, capture_output=True,
                          text=True).stdout.strip()


def _side(repo):
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "theirs.txt").write_bytes(b"from side\n")
    _git(repo, "add", "theirs.txt")
    _git(repo, "commit", "-qm", "side change")
    _git(repo, "checkout", "-q", "illustrated")


def _merge_head(repo):
    return subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=str(repo),
                          capture_output=True).returncode == 0


def _kill_mid_gate(robot, monkeypatch):
    """Run merge('side') and die inside the gate, as a restart would."""
    real = robot.gates.run

    def die(phase, **kw):
        raise RuntimeError("process killed mid-gate (simulated restart)")

    monkeypatch.setattr(robot.gates, "run", die)
    with pytest.raises(RuntimeError):
        robot.merge("side", reason="this call will die")
    monkeypatch.setattr(robot.gates, "run", real)


def test_a_dead_merge_is_visible_as_died(robot, repo, committed_gate, monkeypatch):
    _side(repo)
    _kill_mid_gate(robot, monkeypatch)

    assert _merge_head(repo), "fixture: the dead call must leave MERGE_HEAD, as the real one did"
    rows = [r for r in robot.audit.read() if r.get("op") == "merge"]
    assert rows and rows[-1]["decision"] == "started", "a dead merge must leave a started row"
    flight = robot.in_flight()["merge"]
    assert flight["state"] == "died", flight
    assert robot.merge_status()["merge_head_present"] is True


def test_the_next_merge_recovers_a_clean_interrupted_one_and_says_so(robot, repo,
                                                                      committed_gate,
                                                                      monkeypatch):
    """⭐ Lossless recovery: the dead call's started row recorded a clean tree, so aborting its
    MERGE_HEAD restores exactly the HEAD it began from. Then the merge proceeds normally."""
    _side(repo)
    pre = robot.git.head()
    _kill_mid_gate(robot, monkeypatch)

    out = robot.merge("side", reason="retry after the restart")

    assert out["decision"] == "allowed" and out["merged"] is True, out
    rec = out["recovered_interrupted_merge"]
    assert rec["aborted"] is True and rec["started_head"] == pre == rec["head_after_abort"]
    assert not _merge_head(repo)
    assert robot.in_flight()["merge"]["state"] == "concluded"


def test_an_interrupted_merge_over_uncommitted_work_refuses_and_is_not_aborted(
        robot, repo, committed_gate, monkeypatch):
    """⛔ `merge --abort` cannot always reconstruct pre-merge uncommitted changes. If the dead
    call began over any, nothing is aborted — and the message must NOT be a content conflict."""
    _side(repo)
    (repo / "tracked.txt").write_bytes(b"UNCOMMITTED WORK\n")     # unstaged, unrelated path
    _kill_mid_gate(robot, monkeypatch)

    with pytest.raises(RefusalError) as exc:
        robot.merge("side", reason="retry over dirty work")

    msg = str(exc.value)
    assert "ALREADY IN PROGRESS" in msg and "NOT a content conflict" in msg
    assert "did not apply cleanly" not in msg
    assert _merge_head(repo), "a refusal must leave the interrupted merge for a human"
    assert (repo / "tracked.txt").read_bytes() == b"UNCOMMITTED WORK\n"


def test_a_merge_head_gitrobot_did_not_start_is_never_aborted(robot, repo, committed_gate):
    """A human's in-progress merge has no gitRobot `started` row. Not ours to undo."""
    _side(repo)
    _git(repo, "merge", "--no-ff", "--no-commit", "side")
    assert _merge_head(repo)

    with pytest.raises(RefusalError) as exc:
        robot.merge("side", reason="a human is mid-merge")

    assert "not this server's to undo" in str(exc.value)
    assert _merge_head(repo)


def test_a_refusal_after_a_dead_merge_does_not_make_it_look_concluded(
        robot, repo, committed_gate, monkeypatch):
    """⛔ PAIRED BY RUN_ID, NOT ORDER. The dirty-case refusal is a merge row written AFTER the dead
    run's started row. Under order-pairing it would read as that run's terminal row, and the NEXT
    retry would blame "a human merge" instead of naming the interrupted one."""
    _side(repo)
    (repo / "tracked.txt").write_bytes(b"UNCOMMITTED WORK\n")
    _kill_mid_gate(robot, monkeypatch)
    with pytest.raises(RefusalError):
        robot.merge("side", reason="first retry")

    assert robot.merge_status()["state"] == "died"
    with pytest.raises(RefusalError) as exc:
        robot.merge("side", reason="second retry")
    assert "interrupted merge (run" in str(exc.value), str(exc.value)


def test_a_concurrent_call_from_another_thread_is_refused_and_never_owns_the_run(
        robot, repo, committed_gate, monkeypatch):
    """The real shape of concurrency: two MCP calls on two worker threads. The busy refusal must
    not carry the running merge's run_id, or a first run that then dies would read concluded."""
    import threading
    _side(repo)
    real = robot.gates.run
    in_gate, release = threading.Event(), threading.Event()

    def slow_gate(phase, **kw):
        in_gate.set()
        assert release.wait(30)
        return real(phase, **kw)

    monkeypatch.setattr(robot.gates, "run", slow_gate)
    result = {}
    t = threading.Thread(target=lambda: result.update(
        out=robot.merge("side", reason="thread one")))
    t.start()
    assert in_gate.wait(30), "the first merge never reached its gate"
    try:
        with pytest.raises(RefusalError) as exc:
            robot.merge("side", reason="thread two")
        assert "another merge() is running" in str(exc.value)
        busy = [r for r in robot.audit.read() if r.get("op") == "merge"][-1]
        started = [r for r in robot.audit.read()
                   if r.get("op") == "merge" and r.get("decision") == "started"][-1]
        assert busy["decision"] == "refused"
        assert busy.get("run_id") != started["run_id"], \
            "the busy refusal claimed the running merge's run_id"
    finally:
        release.set()
        t.join(60)
    assert result["out"]["merged"] is True


def test_every_terminal_merge_row_carries_its_run_id(robot, repo, committed_gate):
    _side(repo)
    robot.merge("side", reason="pairing")
    rows = [r for r in robot.audit.read() if r.get("op") == "merge"]
    started, terminal = rows[-2], rows[-1]
    assert started["decision"] == "started" and terminal["decision"] == "allowed"
    assert started["run_id"] and terminal["run_id"] == started["run_id"]


def test_a_running_merge_is_in_flight_and_blocks_a_second(robot, repo, committed_gate,
                                                          monkeypatch):
    """⭐ Visible WHILE it runs (what the restart needed to see), and a second merge refuses
    rather than meeting the first's MERGE_HEAD and aborting it."""
    _side(repo)
    real = robot.gates.run
    seen = {}

    def gate_peeks(phase, **kw):
        seen["flight"] = robot.in_flight()["merge"]
        seen["last_row"] = [r for r in robot.audit.read() if r.get("op") == "merge"][-1]
        with pytest.raises(RefusalError) as exc:
            robot.merge("side", reason="concurrent second call")
        seen["second"] = str(exc.value)
        seen["busy_row"] = [r for r in robot.audit.read() if r.get("op") == "merge"][-1]
        return real(phase, **kw)

    monkeypatch.setattr(robot.gates, "run", gate_peeks)
    out = robot.merge("side", reason="first call")

    assert out["merged"] is True
    assert seen["flight"]["state"] == "running", seen["flight"]
    assert seen["last_row"]["decision"] == "started", "the started row must precede the gate"
    assert "another merge() is running" in seen["second"]
    # ⚠ RE-ENTRANT — same thread as the running merge, so the owner-thread check cannot help
    # here; only `own_run=False` on the busy refusal keeps it from becoming run 1's terminal row.
    assert seen["busy_row"]["decision"] == "refused"
    assert seen["busy_row"].get("run_id") != seen["last_row"]["run_id"]
