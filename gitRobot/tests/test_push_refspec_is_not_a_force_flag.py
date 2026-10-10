"""`push(branch=...)` is a refspec to git, and refspec syntax must not reach it.

⛔ Measured 2026-10-09 by examples/restriction-verification: with the ledger allowing,
push(branch='+illustrated') FORCE-PUSHED and a colleague's commit on the remote was lost, while
push('illustrated') correctly failed as non-fast-forward. The README's "no force" held as a
parameter list and failed as a string. These tests reproduce the harm on a diverged remote, so
they fail on the damage, not on a message.
"""

import subprocess

import pytest

from core import ledger as ledger_client
from core.errors import RefusalError


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def allow(monkeypatch, robot):
    monkeypatch.setattr(ledger_client, "can_push", lambda *a, **k: {
        "ok": True, "allowed": True, "range": "origin/illustrated..illustrated",
        "commits_in_range": 1, "blocking_count": 0, "tip": robot.git.head(),
        "admitted": [], "admission_state": "SET", "not_gating": [], "config_sha": "p",
        "commits": [], "line": "ALLOWED"})


@pytest.fixture
def diverged(repo, tmp_path):
    """The remote holds a colleague's commit the local branch does not have."""
    colleague = tmp_path / "colleague"
    _git(tmp_path, "clone", "-q", "-b", "illustrated", str(tmp_path / "remote.git"), str(colleague))
    (colleague / "theirs.txt").write_text("their work\n", encoding="utf-8")
    _git(colleague, "add", "theirs.txt")
    _git(colleague, "-c", "user.email=c@e.invalid", "-c", "user.name=c", "commit", "-q", "-m", "theirs")
    _git(colleague, "push", "-q", "origin", "illustrated")
    (repo / "mine.txt").write_text("mine\n", encoding="utf-8")
    _git(repo, "add", "mine.txt")
    _git(repo, "commit", "-q", "-m", "mine")
    return _git(tmp_path / "remote.git", "rev-parse", "illustrated")


def _theirs_survives(tmp_path, theirs):
    remote = tmp_path / "remote.git"
    tip = _git(remote, "rev-parse", "illustrated")
    return subprocess.run(["git", "merge-base", "--is-ancestor", theirs, tip], cwd=remote).returncode == 0


@pytest.mark.parametrize("branch", ["+illustrated", "+refs/heads/illustrated",
                                    "illustrated:illustrated", "+illustrated:illustrated",
                                    "HEAD:illustrated", "no-such-branch"])
def test_refspec_syntax_is_refused_and_the_remote_commit_survives(robot, allow, diverged,
                                                                   tmp_path, branch):
    with pytest.raises(RefusalError, match="not the name of a local branch"):
        robot.push(branch, reason="r", wait=True)
    assert _theirs_survives(tmp_path, diverged)


def test_the_control_a_plain_fast_forward_push_still_works(robot, allow, repo, tmp_path):
    (repo / "next.txt").write_text("next\n", encoding="utf-8")
    _git(repo, "add", "next.txt")
    _git(repo, "commit", "-q", "-m", "next")
    out = robot.push("illustrated", reason="r", wait=True)
    assert out["decision"] == "allowed", out
    assert _git(tmp_path / "remote.git", "rev-parse", "illustrated") == _git(repo, "rev-parse", "HEAD")
