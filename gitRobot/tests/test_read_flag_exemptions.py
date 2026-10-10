"""Per-op exemptions from the forbidden-token check, and `grep` as a read.

Measured 2026-10-09 in gitRobot's audit log: all 8 refusals by the redirect/flag check were
benign reads - `log -n N`, `grep -n`, `rev-parse --git-dir` - refused because the check matched
the spelling wherever it appeared. The exemptions are scoped to one op each, so these tests pin
both halves: the logged forms now work, and the same tokens are still refused elsewhere.
"""

import subprocess

import pytest

import core.tiers as tiers
from core.errors import RefusalError


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def history(repo):
    (repo / "tracked.txt").write_text("alpha\nbeta needle\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "second")
    _git(repo, "tag", "-a", "v1", "-m", "first tag")
    return repo


# The shapes of the logged refusals, against the fixture's own files.
@pytest.mark.parametrize("op,args,expect", [
    ("log", ["--oneline", "-n", "1", "--", "tracked.txt"], "second"),
    ("grep", ["-n", "-i", "-e", "NEEDLE", "HEAD", "--", "tracked.txt"], "2:beta needle"),
    ("rev-parse", ["--git-dir"], ".git"),
    ("tag", ["-n"], "first tag"),
])
def test_the_logged_benign_reads_now_succeed(robot, history, op, args, expect):
    out = robot.read(op, args)
    assert out["ok"] is True, out
    assert expect in out["output"], out["output"]


@pytest.mark.parametrize("op,args", [
    ("diff", ["-n"]),                       # -n is exempt for log/grep/tag only
    ("status", ["--git-dir"]),              # --git-dir is exempt for rev-parse only
    ("log", ["--git-dir=elsewhere"]),
    ("grep", ["-C", "elsewhere", "x"]),
    ("grep", ["-Oless", "x"]),              # opens matches in another program
    ("grep", ["--open-files-in-pager", "x"]),
])
def test_the_same_tokens_are_still_refused_elsewhere(robot, history, op, args):
    with pytest.raises(RefusalError):
        robot.read(op, args)


def test_no_op_means_no_exemption():
    assert tiers.forbidden_token(["-n"]) == "-n"
    assert tiers.forbidden_token(["-n"], "log") is None
    assert tiers.forbidden_token(["--git-dir"], "log") == "--git-dir"
