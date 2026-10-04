"""In-memory state must be visible to EVERY GitRobot on a repo, because the server makes one per call.

⛔ Measured 2026-10-04 by ZeroParadox, live: both first attest() calls answered "no armed
attestation" while the commit that armed it was still in flight. `server._robot()` builds a FRESH
GitRobot for every MCP call, and the attestation, the merge lock and the running-merge/commit state
all lived on `self`. Every earlier test drove ONE instance — a control testing a proxy (an object)
for the property (state across calls). These use TWO instances on one repo, as the server does.
"""

import threading

import pytest

from core.engine import GitRobot
from core.errors import RefusalError


def _twin(robot, repo, tmp_path):
    """A second instance on the same repo and audit log: what the next MCP call gets."""
    return GitRobot(repo, data_path=tmp_path / "git_ops.jsonl", actor="test",
                    scratch=tmp_path / "scratch")


def test_an_attestation_armed_by_one_call_is_answered_by_another(robot, repo, tmp_path,
                                                                committed_gate, monkeypatch):
    other = _twin(robot, repo, tmp_path)
    (repo / "a.txt").write_bytes(b"a")
    robot.stage(["a.txt"])
    real, seen = robot.git.run, {}

    def spy(args, **kw):
        if args and args[0] == "commit":
            rid = (kw.get("env_extra") or {}).get("GITROBOT_RUN_ID")
            seen["ans"] = other.attest(rid, real(["write-tree"]).stdout.strip())
        return real(args, **kw)

    monkeypatch.setattr(robot.git, "run", spy)
    m = tmp_path / "m.txt"
    m.write_bytes(b"m\n")
    robot.commit(str(m))
    assert seen["ans"]["attested"] is True, seen["ans"]


def test_a_running_commit_is_visible_to_another_calls_status(robot, repo, tmp_path,
                                                            committed_gate, monkeypatch):
    other = _twin(robot, repo, tmp_path)
    (repo / "b.txt").write_bytes(b"b")
    robot.stage(["b.txt"])
    real, seen = robot.gates.run, {}

    def peek(phase, **kw):
        seen["flight"] = other.in_flight()["commit"]
        return real(phase, **kw)

    monkeypatch.setattr(robot.gates, "run", peek)
    m = tmp_path / "m.txt"
    m.write_bytes(b"m\n")
    robot.commit(str(m))
    assert seen["flight"]["state"] == "running", seen["flight"]


def test_the_merge_lock_holds_across_calls(robot, repo, tmp_path, committed_gate, monkeypatch):
    import subprocess
    other = _twin(robot, repo, tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=repo, check=True)
    (repo / "s.txt").write_bytes(b"s")
    subprocess.run(["git", "add", "s.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "side"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "illustrated"], cwd=repo, check=True)
    real, seen = robot.gates.run, {}

    def peek(phase, **kw):
        seen["flight"] = other.in_flight()["merge"]
        with pytest.raises(RefusalError) as exc:
            other.merge("side", reason="second call, other instance")
        seen["second"] = str(exc.value)
        return real(phase, **kw)

    monkeypatch.setattr(robot.gates, "run", peek)
    out = robot.merge("side", reason="first call")
    assert out["merged"] is True
    assert seen["flight"]["state"] == "running", seen["flight"]
    assert "another merge() is running" in seen["second"]
