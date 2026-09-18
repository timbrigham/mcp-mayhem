"""A non-zero `git push` does not establish that nothing was published.

⛔⛔ MEASURED 2026-09-18, ZeroParadox run 22fb604fe894. The pre-push pipeline passed, the remote
APPLIED the ref, and then the transport died before the client heard about it:

    error: RPC failed; curl 92 Send failure: Connection was aborted
    send-pack: unexpected disconnect while reading sideband packet
    fatal: the remote end hung up unexpectedly

git exited non-zero, gitRobot recorded `failed`, and the honest recovery — push again — re-ran the
whole ~12 minute pipeline and came back `cannot lock ref 'refs/heads/illustrated': is at b13e67cc
but expected 94985a41`. A red for a push whose only fault was being redundant, after a push that
had in fact succeeded.

⭐ `died` HAS CARRIED THIS CORRECTLY SINCE 2026-08-30 — "git can be killed AFTER the remote accepted
the ref; ask the remote, which is the only authority" — while `failed`, which happens far more
often, asserted straight past the same ambiguity. So the receipt now ASKS the remote instead of
inferring from the exit code, and reports three states rather than two.
"""

import pytest

from core import ledger as ledger_client


def _allow(monkeypatch, robot):
    monkeypatch.setattr(ledger_client, "can_push", lambda *a, **k: {
        "ok": True, "allowed": True, "range": "origin/illustrated..illustrated",
        "commits_in_range": 1, "blocking_count": 0, "tip": robot.git.head(),
        "admitted": ["build"], "admission_state": "SET", "not_gating": [],
        "config_sha": "p", "commits": [], "line": "ALLOWED"})


def _commit(robot, repo, tmp_path, name="a.txt"):
    (repo / name).write_text(name, encoding="utf-8")
    robot.stage([name])
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    robot.commit(str(msg))


def _push_failing(robot, monkeypatch, ls_remote_out, ls_remote_ok=True):
    """Make `git push` fail like a dropped transport, and control what the remote reports."""
    real = robot.git.run

    def fake(args, **kw):
        if args and args[0] == "push":
            class R:
                ok = False
                output = ("error: RPC failed; curl 92 Send failure: Connection was aborted\n"
                          "fatal: the remote end hung up unexpectedly")
                stdout = output
                returncode = 128
            return R()
        if args and args[0] == "ls-remote":
            class R:
                ok = ls_remote_ok
                output = ls_remote_out
                stdout = ls_remote_out
                returncode = 0 if ls_remote_ok else 128
            return R()
        return real(args, **kw)

    monkeypatch.setattr(robot.git, "run", fake)


def test_a_transport_failure_after_the_ref_moved_says_it_published(robot, repo, tmp_path,
                                                                   fake_gate, monkeypatch):
    """⛔⛔ THE HEADLINE. The remote is at the hash we sent, so the push PUBLISHED and the caller
    must be told not to retry — the retry is what costs a pipeline and produces a scary red."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    _allow(monkeypatch, robot)
    head = robot.git.head()
    _push_failing(robot, monkeypatch, f"{head}\trefs/heads/illustrated")

    out = robot.push("illustrated", reason="transport dies after the ref lands", wait=True)

    assert out["decision"] == "failed", "git failed; the audit records what happened"
    assert out["published"] is True
    assert "PUBLISHED" in out["note"] and "Do NOT push again" in out["note"]


def test_a_real_failure_says_nothing_was_published(robot, repo, tmp_path, fake_gate, monkeypatch):
    """The other side: the remote is NOT at this hash, so the push genuinely did not land and the
    remedy is to fix and retry."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    _allow(monkeypatch, robot)
    _push_failing(robot, monkeypatch, "0000000000000000000000000000000000000000\trefs/heads/illustrated")

    out = robot.push("illustrated", reason="a genuine rejection", wait=True)

    assert out["decision"] == "failed"
    assert out["published"] is False
    assert "NOT at this hash" in out["note"]


def test_an_unreadable_remote_is_UNKNOWN_not_no(robot, repo, tmp_path, fake_gate, monkeypatch):
    """⚠ THREE-VALUED ON PURPOSE. The defect being fixed is a state that asserted more than it
    knew; answering False when the remote cannot be read would rebuild it one layer down."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    _allow(monkeypatch, robot)
    _push_failing(robot, monkeypatch, "", ls_remote_ok=False)

    out = robot.push("illustrated", reason="remote unreachable", wait=True)

    assert out["decision"] == "failed"
    assert out["published"] is None
    assert "UNKNOWN" in out["note"] and "not 'no'" in out["note"]


def test_a_successful_push_asks_the_remote_nothing(robot, repo, tmp_path, fake_gate, monkeypatch):
    """⚠ The check costs a network round trip and belongs only on the ambiguous path. A push that
    exits 0 published by definition, and adding a second authority there would invent a way for a
    good push to report failure."""
    fake_gate(0)
    _commit(robot, repo, tmp_path)
    _allow(monkeypatch, robot)
    seen = []
    real = robot.git.run

    def fake(args, **kw):
        seen.append(tuple(args[:1]))
        return real(args, **kw)

    monkeypatch.setattr(robot.git, "run", fake)
    out = robot.push("illustrated", reason="ordinary success", wait=True)

    assert out["decision"] == "allowed"
    assert out.get("published") is None, "no remote lookup is recorded on the success path"
    assert ("ls-remote",) not in seen
