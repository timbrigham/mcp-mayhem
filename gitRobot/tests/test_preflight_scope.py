"""preflight must judge the scope the PUSH will send, not an empty one.

⛔⛔ MEASURED 2026-09-15 ON A REAL PUSH. gitRobot ran ZeroParadox's pre-push hook with NO STDIN.
git feeds that hook the refs being pushed, and their `hooks.py pre_push` derives its whole scope
from them, so the pipeline judged:

    scope   0 ref(s) being pushed
    scope   0 reviewable file(s) in the PUSHED RANGE(S) (none)
    ledger  step `adversary` - no reviewable change in scope - review not required

and exited 0. preflight recorded `passed` at cb27e4e; the push of that same HEAD failed in the
hook eighteen minutes later, over 76 files. Every leg of that pipeline is universally quantified
over the reviewed scope, so all of them held vacuously over the empty set.
"""

import pytest

from core.errors import RefusalError


def _hook_recording_stdin(repo, exit_code=0):
    """A stand-in hook that writes what it received on stdin where a test can read it."""
    entry = repo / "tools" / "verify" / "hooks.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "import sys, pathlib\n"
        "data = sys.stdin.read()\n"
        "pathlib.Path('stdin_seen.txt').write_text(data, encoding='utf-8')\n"
        "print('refs seen: ' + repr(data))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8")
    return repo / "stdin_seen.txt"


def test_preflight_feeds_the_hook_the_refs_git_would(robot, repo, tmp_path):
    """⭐ THE HEADLINE. The hook receives `<local ref> <local sha> <remote ref> <remote sha>`,
    exactly git's pre-push format, naming the branch and the HEAD being judged."""
    seen = _hook_recording_stdin(repo)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    robot.stage(["a.txt"])
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    robot.commit(str(msg))
    head = robot.git.head()

    out = robot.preflight(wait=True)

    assert out["passed"] is True
    line = seen.read_text(encoding="utf-8").strip().split()
    assert len(line) == 4, f"not git's pre-push ref format: {line!r}"
    local_ref, local_sha, remote_ref, remote_sha = line
    assert local_ref == remote_ref == "refs/heads/illustrated"
    assert local_sha == head, "the hook must judge the HEAD being preflighted"
    assert remote_sha in (robot.git.run(["rev-parse", "origin/illustrated"]).output.strip(),
                          "0" * 40)


def test_the_started_receipt_names_the_scope_being_judged(robot, repo, tmp_path):
    """⚠ A preflight that judged NOTHING must not read like one that judged the push. The refs
    and the range are on the receipt and on the audit row, before the run lands."""
    _hook_recording_stdin(repo)
    started = robot.preflight(wait=False)
    assert started["push_refs"].startswith("refs/heads/illustrated ")
    assert ".." in started["range"] or "new on the remote" in started["range"]
    row = [r for r in robot.audit.read() if r["op"] == "preflight"][-1]
    assert "refs fed to the hook" in (row.get("detail") or "")


def test_a_detached_head_refuses_rather_than_judging_nothing(robot, repo, tmp_path):
    """⛔ ABSENCE IS NEVER SUCCESS. With no branch there are no refs to feed, and a pipeline with
    no refs reports every check green over an empty scope — the exact defect. Refuse instead."""
    _hook_recording_stdin(repo)
    robot.git.run(["checkout", "-q", "--detach"])

    with pytest.raises(RefusalError) as exc:
        robot.preflight(wait=True)
    assert "detached" in str(exc.value)
    assert "empty scope" in exc.value.alternative


def test_push_status_carries_the_failure_reason(robot, repo, tmp_path, fake_gate, monkeypatch):
    """⛔ `extra` IS NOT ON THE AUDIT ROW — `_receipt` merges it into the returned receipt only,
    so push_status's `extra.output` read was null on EVERY push. Measured 2026-09-15: a failed
    push whose 8,120-character transcript sat on the row under `detail`, while the caller got
    `output: null` and re-ran the pipeline by hand to learn why."""
    fake_gate(0)
    (repo / "b.txt").write_text("b", encoding="utf-8")
    robot.stage(["b.txt"])
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    robot.commit(str(msg))

    from core import ledger as ledger_client
    monkeypatch.setattr(ledger_client, "can_push", lambda *a, **k: {
        "ok": True, "allowed": True, "range": "r", "commits_in_range": 1, "blocking_count": 0,
        "tip": robot.git.head(), "admitted": ["build"], "admission_state": "SET",
        "not_gating": [], "config_sha": "p", "commits": [], "line": "ALLOWED"})
    # a remote that refuses, so the push fails with a real transcript
    robot.git.run(["remote", "set-url", "origin", str(tmp_path / "does-not-exist")])
    robot.push("illustrated", reason="prove the failure reason survives", wait=True)

    status = robot.push_status()
    assert status["state"] == "failed"
    assert status["output"], "a failed push must carry its reason; the caller cannot re-run git"
