"""Committing FROM a worktree — the thing that made worktree-per-change impossible.

⭐⭐ MEASURED 2026-09-02: `_target()` accepted only `main` and `.claude-local`, so `stage`,
`commit` and `unstage` could not reach a worktree at all. A worktree was somewhere you could
READ and run checkers; it was not somewhere you could AUTHOR. With raw git hook-blocked on the
consuming side, there was no fallback — so the intended worktree-per-change flow lapsed into 26
commits in three days on one branch, every other branch months stale.

⚠⚠ THE SAFETY ARGUMENT IS "GIT VOUCHES FOR IT", NOT "PATHS ARE FINE". `sub_repo` refuses a path
argument because it "would reopen the general-proxy hole this class exists to close" — right, and
the objection is to paths the CALLER INVENTS. A worktree is validated against `git worktree list`,
a set only `worktree(action='add')` can add to. That is a STRONGER check than `sub_repo`'s two
hand-written tests, because it asks git rather than reasoning about the filesystem.
"""

import subprocess

import pytest

from core.errors import RefusalError, UsageError


def _git(repo, *args):
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr
    return p.stdout


# -- ⭐⭐ the thing that could not be done -------------------------------------

def test_a_commit_can_be_authored_in_a_worktree(robot, repo, fake_gate):
    """⭐⭐ THE HEADLINE. Stage and commit inside a worktree, and the MAIN checkout does not
    move — which is the whole point of concurrent editing: two sessions, two indexes, no
    contention for the state they would otherwise share."""
    # ⚠ THE GATE MUST BE IN THE WORKTREE, WHICH MEANS COMMITTED BEFORE IT IS CREATED. The
    # fixture writes `tools/verify/hooks.py` into the working tree only; a worktree made from
    # HEAD would not contain it, and the gate would correctly refuse "cannot vouch for this
    # tree". That refusal IS the fix working — before it, the gate ran in the main checkout
    # and would have passed while committing entirely different content.
    _git(repo, "add", "tools/verify/hooks.py")
    _git(repo, "commit", "-q", "-m", "install the gate")

    wt = robot.worktree("add", ref="HEAD")["path"]
    main_head_before = _git(repo, "rev-parse", "HEAD").strip()

    (__import__("pathlib").Path(wt) / "feature.txt").write_text("A's work\n", encoding="utf-8")
    robot.stage(["feature.txt"], worktree=wt)
    msg = repo.parent / "msg.txt"
    msg.write_text("work authored in a worktree\n", encoding="utf-8")
    out = robot.commit(str(msg), reason="concurrent edit", worktree=wt)

    assert out["decision"] == "allowed"
    assert _git(wt, "log", "-1", "--format=%s").strip() == "work authored in a worktree"
    assert _git(repo, "rev-parse", "HEAD").strip() == main_head_before, \
        "the main checkout moved — the worktree was not isolated"


def test_two_worktrees_hold_independent_indexes(robot, repo):
    """⚠ THE PROPERTY CONCURRENCY RESTS ON. Staging in one worktree must not appear in the
    other. If indexes were shared, two agents editing the same files would corrupt each other's
    verdicts — records key on the INDEX, so a shared one would mean a verdict about the wrong
    bytes."""
    import pathlib
    a = robot.worktree("add", ref="HEAD")["path"]
    b = robot.worktree("add", ref="HEAD")["path"]

    (pathlib.Path(a) / "a.txt").write_text("from A\n", encoding="utf-8")
    robot.stage(["a.txt"], worktree=a)

    assert _git(a, "diff", "--cached", "--name-only").split() == ["a.txt"]
    assert _git(b, "diff", "--cached", "--name-only").split() == [], \
        "a stage in one worktree appeared in another — indexes are shared"


# -- ⚠⚠ the validated set, which is the safety argument -----------------------

def test_a_path_git_does_not_list_is_refused(robot, repo, tmp_path):
    """⭐⭐ THE GUARD. Only what `git worktree list` vouches for. An invented path, a directory
    outside the repo, another repository — none appear in that set, so all are refused."""
    outside = tmp_path / "not-a-worktree"
    outside.mkdir()
    with pytest.raises(RefusalError) as exc:
        robot.stage(["x.txt"], worktree=str(outside))
    assert "does not list" in str(exc.value)


def test_a_removed_worktree_stops_being_targetable(robot, repo):
    """⚠ THE SET IS LIVE, NOT REMEMBERED. Once removed, git stops listing it, so it stops being
    targetable — no stale handle survives teardown."""
    wt = robot.worktree("add", ref="HEAD")["path"]
    robot.worktree("remove", name=wt)

    with pytest.raises(RefusalError):
        robot.stage(["x.txt"], worktree=wt)


def test_the_main_checkout_is_not_reachable_as_a_worktree(robot, repo):
    """⚠ git lists the main checkout among the worktrees, so it WOULD pass the set test. It is
    refused separately and told to omit the parameter — two ways to say the same thing is how a
    guard gets bypassed by whichever spelling is checked less."""
    with pytest.raises(UsageError, match="main checkout"):
        robot.stage(["x.txt"], worktree=str(repo))


def test_worktree_and_a_nested_repo_are_mutually_exclusive(robot, repo):
    """⚠ `.claude-local` is a separate repository; it has no worktrees of its own. Accepting
    both would silently pick one, which is the ambiguity these modes exist to remove."""
    wt = robot.worktree("add", ref="HEAD")["path"]
    with pytest.raises(UsageError, match="mutually exclusive"):
        robot.stage(["x.txt"], repo_mode=".claude-local", worktree=wt)


def test_the_gate_runs_in_the_tree_being_committed(robot, repo, fake_gate):
    """⛔⛔ THE BUG I ALMOST SHIPPED, PINNED. `self.gates` is bound to the MAIN checkout. Once
    `worktree` became targetable, a worktree commit would have run the pipeline against the main
    tree while committing the worktree's content — **the check and the act about different
    objects**, which is the defect class this project spent three days removing, reintroduced by
    the fix for something else.

    ⚠ Asserted by DIVERGENCE, not by reading the call: the gate is made to FAIL in the worktree
    while still passing in the main checkout. If the gate followed the main tree the commit would
    succeed; it must be refused."""
    import pathlib
    _git(repo, "add", "tools/verify/hooks.py")
    _git(repo, "commit", "-q", "-m", "install the gate")
    wt = robot.worktree("add", ref="HEAD")["path"]

    # main checkout keeps a PASSING gate; the worktree's copy fails
    (pathlib.Path(wt) / "tools" / "verify" / "hooks.py").write_text(
        "import sys\nprint('worktree gate')\nsys.exit(1)\n", encoding="utf-8")
    (pathlib.Path(wt) / "x.txt").write_text("work\n", encoding="utf-8")
    robot.stage(["x.txt"], worktree=wt)
    msg = repo.parent / "m.txt"
    msg.write_text("should be refused\n", encoding="utf-8")

    with pytest.raises(RefusalError, match="pre-commit gate did not pass"):
        robot.commit(str(msg), reason="probe", worktree=wt)

    assert _git(wt, "log", "-1", "--format=%s").strip() != "should be refused", \
        "the gate ran against the main tree and let a worktree commit through"
