"""Removing a worktree must never reach through a JUNCTION into the thing it points at.

⭐⭐ RAISED BY ZeroParadox 2026-08-30, from a procedure it had just run for real. Healing four
pre-fix commits meant checking each one out in a detached worktree and recording the six
mechanical checkers there — and a fresh worktree has no `.lake`, so `check_paths` WITHHELD
(exit 3, "it skipped a class (Mathlib absent)"), correctly refusing to record a partial run as a
PASS. The fix is a directory junction from the worktree's `.lake` to the main checkout's.

⚠⚠ WHICH CREATES A FOOTGUN WITH A VERY LARGE BLAST RADIUS: a recursive delete of a worktree that
still contains that junction can walk INTO the real, pinned Mathlib checkout and destroy it,
while looking like tidying up a scratch directory. ZeroParadox removed each junction explicitly
with a NON-recursive `Directory.Delete(path, false)` and verified Mathlib survived all four times.

⚠ `os.path.islink()` RETURNS **False** FOR A JUNCTION — measured, Python 3.12.10. So any guard
written as "skip it if it is a link" is fooled. `shutil.rmtree` happens to handle junctions
correctly on this version (CPython stopped following them in 3.8), and that is the behaviour this
file pins: it is load-bearing, non-obvious, was not always true, and the cost of it silently
changing is a destroyed dependency rather than a failed test.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _junction(link, target):
    p = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        pytest.skip(f"cannot create a junction here: {(p.stdout + p.stderr).strip()}")


def test_rmtree_does_not_reach_through_a_junction(tmp_path):
    """⭐⭐ THE PROPERTY, PINNED AGAINST THE REAL RISK. gitRobot's orphan-worktree path calls
    `shutil.rmtree`; if that ever followed a junction it would delete the pinned Mathlib."""
    target = tmp_path / "REAL"
    target.mkdir()
    (target / "precious.txt").write_text("must survive", encoding="utf-8")

    wt = tmp_path / "worktree"
    wt.mkdir()
    _junction(wt / ".lake", target)

    shutil.rmtree(wt, ignore_errors=False)

    assert not wt.exists(), "the worktree directory should be gone"
    assert (target / "precious.txt").exists(), \
        "rmtree followed the junction and destroyed the target — a pinned dependency would be gone"


def test_islink_is_not_a_safe_guard_for_junctions(tmp_path):
    """⚠⚠ THE REASON THIS NEEDS A TEST RATHER THAN A COMMENT. The obvious defensive check —
    "it is a link, so skip it" — does not fire for a junction. Anyone hardening this code by
    hand will reach for `islink` first, and it will silently not protect them."""
    target = tmp_path / "REAL"
    target.mkdir()
    link = tmp_path / "link"
    _junction(link, target)

    assert os.path.islink(link) is False, \
        "islink now reports junctions as links — the rmtree guard may rest on different ground"


# -- ⛔⛔ the one that matters: git's deletion, not CPython's -------------------

def test_git_worktree_remove_would_follow_a_junction(tmp_path):
    """⛔⛔ THE MEASUREMENT THAT MADE THE GUARD NECESSARY, PINNED AS A FACT ABOUT GIT.

    `shutil.rmtree` does NOT follow junctions. **`git worktree remove` DOES**, and returns 0.
    So the safety argument covering gitRobot's ORPHAN path never covered its REGISTERED path,
    which shells out to git — the same class as every other defect this weekend: a control whose
    reasoning is about a different code path than the one that runs. Caught by ZeroParadox
    reading my test rather than my claim.

    ⚠ This test asserts the DANGEROUS behaviour, deliberately. If git ever stops following
    junctions the assertion fails, and that is the moment to reconsider the guard rather than
    keep a refusal nobody needs."""
    real = tmp_path / "REAL"
    real.mkdir()
    (real / "precious.txt").write_text("pinned dependency", encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@e.invalid"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True, text=True)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=repo, capture_output=True, text=True)

    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"],
                   cwd=repo, capture_output=True, text=True)
    _junction(wt / ".lake", real)

    subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                   cwd=repo, capture_output=True, text=True)

    assert not (real / "precious.txt").exists(), (
        "git no longer follows junctions — revisit the guard in engine.worktree(remove)")


def test_the_robot_refuses_to_remove_a_worktree_holding_a_junction(robot, repo, tmp_path):
    """⭐⭐ THE GUARD. gitRobot must never hand a junction-containing worktree to git, because
    git reports success while deleting the target. It refuses and NAMES the link."""
    from core.errors import RefusalError

    real = tmp_path / "REAL"
    real.mkdir()
    (real / "precious.txt").write_text("pinned dependency", encoding="utf-8")

    out = robot.worktree("add", ref="HEAD")
    wt = Path(out["path"]) if "path" in out else Path(out["name"])
    # ⚠ NOT `.lake`. That one is PROVISIONED by `worktree add` and removed by `worktree remove`
    # — ours, known, and safely unlinked. The guard exists for links the tool did NOT create,
    # because it cannot know what those point at. Using `.lake` here would test the provisioning
    # rather than the guard, and would pass for the wrong reason.
    _junction(wt / "vendor-link", real)

    with pytest.raises(RefusalError) as exc:
        robot.worktree("remove", name=str(wt))
    assert "junction" in str(exc.value).lower()
    assert (real / "precious.txt").exists(), "the target must be untouched by a refusal"


# -- ⭐⭐ the provisioning that makes the worktree flow usable at all ----------

def _shared_dep_repo(tmp_path):
    """A repo with a large gitignored `.lake`, the real shape."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@e.invalid"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True, text=True)
    (repo / ".gitignore").write_text(".lake/\n", encoding="utf-8")
    (repo / "a.txt").write_text("x", encoding="utf-8")
    lake = repo / ".lake" / "packages" / "mathlib"
    lake.mkdir(parents=True)
    (lake / "Mathlib.lean").write_text("-- pinned dependency\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=repo, capture_output=True, text=True)
    return repo


def test_a_fresh_worktree_gets_the_shared_lake(tmp_path):
    """⭐⭐ WHY THE WORKTREE FLOW LAPSED. `.lake` is gitignored, so `git worktree add` yields a
    checkout where Lean cannot build and `check_paths` WITHHOLDS on absent Mathlib. The intended
    model is a private worktree per change converging at a local merge — and a worktree straight
    out of the tool could not build the corpus, so work went serially onto one branch instead:
    26 commits in three days, all on `illustrated`, every other branch months stale.

    **A sanctioned path that does not produce a working tree is not a sanctioned path.** The rule
    could not be enforced because compliance was impossible."""
    from core.audit import AuditLog
    from core.engine import GitRobot

    repo = _shared_dep_repo(tmp_path)
    # ⚠⚠ `scratch` IS NOT OPTIONAL IN A TEST. Without it `GitRobot` falls back to
    # `DEFAULT_SCRATCH` — the SHARED production worktree area — so every run of this file left
    # a directory there holding a `.lake` junction into a pytest fixture that is deleted
    # seconds later. Measured 2026-09-03 by ZeroParadox: **24 leftover directories, 20 carrying
    # a dangling junction.** None pointed at the real `.lake` (which is why Mathlib was never
    # at risk), but a fixture whose junction DID point at the real one, plus a teardown that
    # failed, is the Mathlib hazard with a fresh door.
    robot = GitRobot(repo=str(repo), data_path=str(tmp_path / "ops.jsonl"), actor="t",
                     scratch=tmp_path / "scratch")

    out = robot.worktree("add", ref="HEAD")
    wt = Path(out["path"])

    assert ".lake" in out["linked"], "worktree add did not provision the shared dependency"
    assert (wt / ".lake" / "packages" / "mathlib" / "Mathlib.lean").exists(), \
        "the pinned dependency is not reachable from the worktree"


def test_teardown_unlinks_ours_and_never_touches_the_target(tmp_path):
    """⚠⚠ THE ORDER IS THE SAFETY ARGUMENT. `git worktree remove --force` FOLLOWS a junction and
    deletes what it points at, returning 0 — measured. So the link must go FIRST, and by a
    non-recursive `rmdir` that takes the link and never the target. This is the sequence that was
    executed by hand four times during a healing run, now done by construction."""
    from core.engine import GitRobot

    repo = _shared_dep_repo(tmp_path)
    # ⚠⚠ `scratch` IS NOT OPTIONAL IN A TEST. Without it `GitRobot` falls back to
    # `DEFAULT_SCRATCH` — the SHARED production worktree area — so every run of this file left
    # a directory there holding a `.lake` junction into a pytest fixture that is deleted
    # seconds later. Measured 2026-09-03 by ZeroParadox: **24 leftover directories, 20 carrying
    # a dangling junction.** None pointed at the real `.lake` (which is why Mathlib was never
    # at risk), but a fixture whose junction DID point at the real one, plus a teardown that
    # failed, is the Mathlib hazard with a fresh door.
    robot = GitRobot(repo=str(repo), data_path=str(tmp_path / "ops.jsonl"), actor="t",
                     scratch=tmp_path / "scratch")
    wt = Path(robot.worktree("add", ref="HEAD")["path"])

    out = robot.worktree("remove", name=str(wt))

    assert out["decision"] == "allowed"
    assert not wt.exists(), "the worktree should be gone"
    assert (repo / ".lake" / "packages" / "mathlib" / "Mathlib.lean").exists(), \
        "teardown reached through the junction and destroyed the pinned dependency"


def test_a_real_directory_named_lake_is_never_deleted(tmp_path):
    """⚠ THE COMPLEMENT, AND IT IS WHAT KEEPS THE UNLINK HONEST. Only a REPARSE POINT is removed.
    If a worktree somehow holds a genuine `.lake` directory, it is not ours and `rmdir` would be
    a destructive act on real content — so the attribute is checked, not the name."""
    from core.engine import GitRobot

    repo = _shared_dep_repo(tmp_path)
    # ⚠⚠ `scratch` IS NOT OPTIONAL IN A TEST. Without it `GitRobot` falls back to
    # `DEFAULT_SCRATCH` — the SHARED production worktree area — so every run of this file left
    # a directory there holding a `.lake` junction into a pytest fixture that is deleted
    # seconds later. Measured 2026-09-03 by ZeroParadox: **24 leftover directories, 20 carrying
    # a dangling junction.** None pointed at the real `.lake` (which is why Mathlib was never
    # at risk), but a fixture whose junction DID point at the real one, plus a teardown that
    # failed, is the Mathlib hazard with a fresh door.
    robot = GitRobot(repo=str(repo), data_path=str(tmp_path / "ops.jsonl"), actor="t",
                     scratch=tmp_path / "scratch")
    wt = Path(robot.worktree("add", ref="HEAD")["path"])

    (wt / ".lake").rmdir()                       # drop our junction
    real = wt / ".lake"
    real.mkdir()
    (real / "handmade.txt").write_text("not ours", encoding="utf-8")

    removed = robot._unlink_shared_deps(wt)
    assert removed == [], "a real directory was treated as our junction"
    assert (real / "handmade.txt").exists()
