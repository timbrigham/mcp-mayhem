"""attest(): gitRobot vouches, in memory, single-use, for exactly the tree its own gate passed.

⭐ Tim, 2026-10-03. A commit ran the consumer's ~5-minute pre-commit pipeline twice: gitRobot's
gate, then the installed hook inside `git commit`. The hook may skip its second run ONLY on a
`yes` from attest(). Every test here is about when the answer must be NO.

The hook's side is simulated by spying on `git commit`: at that moment the attestation is armed,
exactly as when the real hook would call in.
"""

import pytest


def _stage(robot, repo, name="a.txt", body=b"a"):
    (repo / name).write_bytes(body)
    robot.stage([name])


def _msg(tmp_path):
    m = tmp_path / "m.txt"
    m.write_bytes(b"m\n")
    return str(m)


def _spy_commit(robot, monkeypatch, during):
    """Run `during(run_id, tree)` at the moment `git commit` executes — the hook's moment."""
    real = robot.git.run
    seen = {}

    def spy(args, **kw):
        if args and args[0] == "commit":
            env = kw.get("env_extra") or {}
            rid = env.get("GITROBOT_RUN_ID")
            tree = real(["write-tree"]).stdout.strip()
            seen["env"] = env
            seen["answers"] = during(rid, tree)
        return real(args, **kw)

    monkeypatch.setattr(robot.git, "run", spy)
    return seen


def test_yes_once_for_the_exact_tree_during_the_commit(robot, repo, tmp_path, committed_gate,
                                                       monkeypatch):
    _stage(robot, repo)
    seen = _spy_commit(robot, monkeypatch,
                       lambda rid, tree: [robot.attest(rid, tree), robot.attest(rid, tree)])
    out = robot.commit(_msg(tmp_path))
    assert out["decision"] == "allowed"
    assert seen["env"]["GITROBOT_OP"] == "commit"
    first, second = seen["answers"]
    assert first["attested"] is True, first
    assert second["attested"] is False and "single-use" in second["why"]
    rows = [r for r in robot.audit.read() if r["op"] == "attest"]
    assert [r["decision"] for r in rows[-2:]] == ["allowed", "refused"], "every answer is audited"


def test_after_the_commit_returns_nothing_is_armed(robot, repo, tmp_path, committed_gate,
                                                   monkeypatch):
    _stage(robot, repo)
    seen = _spy_commit(robot, monkeypatch, lambda rid, tree: (rid, tree))
    robot.commit(_msg(tmp_path))
    rid, tree = seen["answers"]
    late = robot.attest(rid, tree)
    assert late["attested"] is False and "no armed attestation" in late["why"]


def test_a_different_tree_is_no(robot, repo, tmp_path, committed_gate, monkeypatch):
    _stage(robot, repo)
    seen = _spy_commit(robot, monkeypatch, lambda rid, tree: robot.attest(rid, "0" * 40))
    robot.commit(_msg(tmp_path))
    assert seen["answers"]["attested"] is False
    assert "differs" in seen["answers"]["why"]


def test_tools_verify_changed_on_disk_after_the_gate_is_no(robot, repo, tmp_path,
                                                           committed_gate, monkeypatch):
    """The gate EXECUTED tools/verify from disk; if those bytes moved, a different check ran."""
    _stage(robot, repo)
    hooks = repo / "tools" / "verify" / "hooks.py"

    def tamper_then_ask(rid, tree):
        hooks.write_bytes(hooks.read_bytes() + b"\n# edited after the gate\n")
        return robot.attest(rid, tree)

    seen = _spy_commit(robot, monkeypatch, tamper_then_ask)
    robot.commit(_msg(tmp_path))
    assert seen["answers"]["attested"] is False
    assert "tools/verify changed" in seen["answers"]["why"]


def test_a_failed_gate_arms_nothing(robot, repo, tmp_path, committed_gate, fake_gate):
    from core.errors import RefusalError
    fake_gate(1)
    _stage(robot, repo)
    with pytest.raises(RefusalError):
        robot.commit(_msg(tmp_path))
    assert robot._attestations == {}


def test_a_commit_that_ran_no_gate_is_never_attested(robot, repo, tmp_path, committed_gate,
                                                     monkeypatch):
    """⛔ THE CASE THE PASSED-GATE CHECK ACTUALLY GUARDS. A failing gate raises before arming,
    so "armed on a failure" cannot happen — but `run_gate=False` (and non-main repos) commit with
    NO gate at all, and a `yes` there would vouch for a check that never ran. Found 2026-10-03
    when the mutant removing the check SURVIVED the failing-gate test."""
    _stage(robot, repo)
    seen = _spy_commit(robot, monkeypatch, lambda rid, tree: robot.attest(rid, tree))
    robot.commit(_msg(tmp_path), run_gate=False)
    assert seen["answers"]["attested"] is False, seen["answers"]


def test_an_unknown_run_is_no(robot):
    out = robot.attest("not-a-run", "0" * 40)
    assert out["attested"] is False and "no armed attestation" in out["why"]


def test_a_merge_commit_is_attestable_too(robot, repo, tmp_path, committed_gate, monkeypatch):
    import subprocess
    subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=repo, check=True)
    (repo / "s.txt").write_bytes(b"s")
    subprocess.run(["git", "add", "s.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "side"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "illustrated"], cwd=repo, check=True)
    seen = _spy_commit(robot, monkeypatch, lambda rid, tree: robot.attest(rid, tree))
    out = robot.merge("side", reason="attest a merge")
    assert out["merged"] is True
    assert seen["env"]["GITROBOT_OP"] == "merge"
    assert seen["answers"]["attested"] is True, seen["answers"]
