"""`unstage` — the missing inverse of a `stage` that was never only about intent.

Raised by ZeroParadox 2026-08-29, and it is not a corner case. `batch.py precommit`
records verdicts against the STAGED content: three checkers exited 2 with "differs
from HEAD in the worktree or index" until the files were staged, and the identical run
then passed. **On this pipeline staging is a VERIFICATION step, not a statement of
commit intent** — and there was no way back out of it. A session that verified more
than it was ready to commit had an index it could not narrow: a gate-exempt tooling
change and a gated document could only be committed together or not at all.

⚠⚠ THE OTHER CANDIDATE WAS A `paths` PARAMETER ON `commit`, AND IT IS WRONG FOR THIS
SYSTEM. Measured before choosing:

    index tree (what the gate verified)        b6293d90
    commit tree (what a pathspec commit lands) 2a1c180d

`git commit -- <paths>` builds a TEMPORARY tree — staged content for the named paths,
HEAD's for everything else — so the commit does not carry the index tree while
verdictLedger records against `write-tree`. The record would name a tree that never
became a commit: §12-0-alpha's defect through a new door.
"""

import subprocess

import pytest

from core.errors import RefusalError, UsageError


def _git(repo, *args):
    p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr
    return p.stdout


def _staged(repo):
    return sorted(l.split("\t", 1)[1].strip()
                  for l in _git(repo, "diff", "--cached", "--name-only",
                                "--format=").splitlines() if l.strip()) \
        if False else sorted(x for x in _git(repo, "diff", "--cached",
                                             "--name-only").split() if x)


# -- ⭐⭐ the thing that could not be done ------------------------------------

def test_a_verified_file_can_be_taken_back_out_of_the_index(robot, repo):
    """⭐⭐ THE HEADLINE. Two files staged so the checkers could see them; only one is
    ready to commit. Before this, they went together or not at all."""
    (repo / "ready.md").write_text("tooling change\n", encoding="utf-8")
    (repo / "blocked.md").write_text("awaiting review\n", encoding="utf-8")
    robot.stage(["ready.md", "blocked.md"])
    assert _staged(repo) == ["blocked.md", "ready.md"]

    out = robot.unstage(["blocked.md"], reason="held pending editorial review")
    assert out["decision"] == "allowed"
    assert _staged(repo) == ["ready.md"]


def test_the_working_tree_is_untouched(robot, repo):
    """⚠⚠ THE PROPERTY THAT PUTS THIS OUTSIDE TIER 1. `reset --hard`, `checkout -- .`,
    `clean` and `stash` are refused because they destroy uncommitted WORKING-TREE state
    that exists nowhere else. This cannot: the file on disk is exactly as it was."""
    (repo / "f.txt").write_text("v1-STAGED\n", encoding="utf-8")
    robot.stage(["f.txt"])
    (repo / "f.txt").write_text("v2-WORKTREE\n", encoding="utf-8")

    robot.unstage(["f.txt"], reason="probe")
    assert (repo / "f.txt").read_text(encoding="utf-8") == "v2-WORKTREE\n"


def test_it_is_audited_like_every_other_tier_2_call(robot, repo):
    """⚠ §7: every mutating call leaves a record, including the clean path. An index
    change nobody can account for afterwards is the gap the audit exists to close."""
    (repo / "a.md").write_text("x\n", encoding="utf-8")
    robot.stage(["a.md"])
    robot.unstage(["a.md"], reason="not ready")
    last = robot.audit.read()[-1]
    assert last["op"] == "unstage"
    assert last["decision"] == "allowed"
    assert last["reason"] == "not ready"


# -- ⚠ the guards, mirroring `stage` -----------------------------------------

@pytest.mark.parametrize("token", ["-A", ".", "--all", ":/", "*"])
def test_bulk_forms_are_refused(robot, repo, token):
    """⚠ Same reason `stage` refuses them: background agents write to this checkout
    concurrently, so 'unstage everything' would clear entries this session never made.
    The refusal names what to do instead, or it just produces a workaround."""
    with pytest.raises(RefusalError) as exc:
        robot.unstage([token], reason="probe")
    assert "unstage(paths=" in exc.value.alternative


def test_an_empty_path_list_is_refused_with_the_reason(robot, repo):
    with pytest.raises(UsageError, match="no bulk form"):
        robot.unstage([], reason="probe")


def test_a_path_that_looks_like_a_flag_is_never_passed_as_one(robot, repo):
    """⚠ gitRobot passes paths, never options. The engine also terminates options with
    `--` so a file legitimately named like a flag still works as a path."""
    with pytest.raises(UsageError, match="looks like a flag"):
        robot.unstage(["--staged"], reason="probe")


def test_the_working_tree_restore_form_is_unreachable(robot, repo):
    """⚠⚠ `--staged` IS THE WHOLE DIFFERENCE AND IT IS NOT A CALLER PARAMETER. Without
    it this would be `git restore`, which overwrites the working tree from the index —
    a Tier 1 destroy wearing the same verb. Pinned by reading the call the engine
    actually builds, because the distinction is one word."""
    import inspect
    from core import engine
    src = inspect.getsource(engine.GitRobot.unstage)
    assert '"restore", "--staged", "--", *paths' in src
    assert "--worktree" not in src
