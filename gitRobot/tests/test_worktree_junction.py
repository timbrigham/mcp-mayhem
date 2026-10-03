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
    # the project's OWN build output — copied per worktree since 2026-10-02, never shared
    build = repo / ".lake" / "build" / "lib" / "ZeroParadox"
    build.mkdir(parents=True)
    (build / "Core.olean").write_bytes(b"MAIN-OLEAN")
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

    assert out["linked"] == [".lake/packages"], out
    assert ".lake/build" in out["copied"], out
    assert out["not_provisioned"] == [], out
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

    robot._unlink_shared_deps(wt)                # drop our junction(s)
    shutil.rmtree(wt / ".lake")                  # and the per-worktree copy
    real = wt / ".lake"
    real.mkdir()
    (real / "handmade.txt").write_text("not ours", encoding="utf-8")
    (real / "packages").mkdir()                  # a REAL dir at the nested link's name, too
    (real / "packages" / "handmade.txt").write_text("not ours either", encoding="utf-8")

    removed = robot._unlink_shared_deps(wt)
    assert removed == [], "a real directory was treated as our junction"
    assert (real / "handmade.txt").exists()
    assert (real / "packages" / "handmade.txt").exists()


# -- ⭐⭐ 2026-10-02: share `packages`, COPY `build` ---------------------------------

def _robot(tmp_path):
    from core.engine import GitRobot
    repo = _shared_dep_repo(tmp_path)
    robot = GitRobot(repo=str(repo), data_path=str(tmp_path / "ops.jsonl"), actor="t",
                     scratch=tmp_path / "scratch")
    return repo, robot


def _is_reparse(p):
    import stat
    try:
        return bool(getattr(p.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def test_a_worktree_build_never_writes_into_the_main_build(tmp_path):
    """⛔⛔ THE PROPERTY THIS CHANGE EXISTS FOR. Measured by ZeroParadox 2026-10-02: with `.lake`
    junctioned whole, `<wt>\\.lake\\build` WAS the main checkout's build — 18 worktrees, one
    output directory, concurrent builds forced into single file. A write in a worktree's build
    must land in THAT worktree only."""
    repo, robot = _robot(tmp_path)
    wt = Path(robot.worktree("add", ref="HEAD")["path"])

    assert not _is_reparse(wt / ".lake"), ".lake is still a junction — the build is shared"
    assert _is_reparse(wt / ".lake" / "packages"), "packages must stay SHARED (7.76 GB)"
    assert not _is_reparse(wt / ".lake" / "build"), "build must be a per-worktree copy"
    wt_olean = wt / ".lake" / "build" / "lib" / "ZeroParadox" / "Core.olean"
    assert wt_olean.read_bytes() == b"MAIN-OLEAN", "the copy must not be empty: ZeroParadox.* " \
                                                   "would not import"

    wt_olean.write_bytes(b"WORKTREE-OLEAN")
    (wt / ".lake" / "build" / "lib" / "ZeroParadox" / "OnlyHere.olean").write_bytes(b"x")

    main = repo / ".lake" / "build" / "lib" / "ZeroParadox"
    assert (main / "Core.olean").read_bytes() == b"MAIN-OLEAN", \
        "a worktree build overwrote the MAIN checkout's olean"
    assert not (main / "OnlyHere.olean").exists(), \
        "a worktree-only module's olean landed in the MAIN checkout's build"


def test_teardown_of_the_new_layout_keeps_mathlib_and_the_main_build(tmp_path):
    repo, robot = _robot(tmp_path)
    wt = Path(robot.worktree("add", ref="HEAD")["path"])

    out = robot.worktree("remove", name=str(wt))

    assert out["decision"] == "allowed", out
    assert out["unlinked"] == [".lake/packages"], out
    assert not wt.exists()
    assert (repo / ".lake" / "packages" / "mathlib" / "Mathlib.lean").exists(), \
        "teardown reached through the nested junction and destroyed the pinned dependency"
    assert (repo / ".lake" / "build" / "lib" / "ZeroParadox" / "Core.olean").exists()


def test_teardown_of_a_pre_change_worktree_still_unlinks_the_whole_lake(tmp_path):
    """⚠⚠ 18 LIVE WORKTREES ON 2026-10-02 HOLD THE OLD LAYOUT. Teardown and the reaper meet them
    for weeks; the outer junction must still be recognised and removed as a link."""
    repo, robot = _robot(tmp_path)
    wt = Path(robot.worktree("add", ref="HEAD")["path"])
    robot._unlink_shared_deps(wt)
    shutil.rmtree(wt / ".lake")
    _junction(wt / ".lake", repo / ".lake")      # rebuild the OLD shape by hand

    out = robot.worktree("remove", name=str(wt))

    assert out["decision"] == "allowed", out
    assert out["unlinked"] == [".lake"], out
    assert (repo / ".lake" / "packages" / "mathlib" / "Mathlib.lean").exists()
    assert (repo / ".lake" / "build" / "lib" / "ZeroParadox" / "Core.olean").exists()


def test_a_foreign_link_inside_lake_is_refused_not_followed(tmp_path):
    """The nested layout opens a new place for a hand-made link. It is not ours, so remove must
    refuse and NAME it rather than hand it to git, which would delete its target."""
    from core.errors import RefusalError
    repo, robot = _robot(tmp_path)
    precious = tmp_path / "PRECIOUS"
    precious.mkdir()
    (precious / "keep.txt").write_bytes(b"keep")
    wt = Path(robot.worktree("add", ref="HEAD")["path"])
    _junction(wt / ".lake" / "vendor", precious)

    with pytest.raises(RefusalError) as exc:
        robot.worktree("remove", name=str(wt))
    assert "vendor" in str(exc.value)
    assert (precious / "keep.txt").exists()
    assert (repo / ".lake" / "packages" / "mathlib" / "Mathlib.lean").exists()


def test_a_link_in_the_main_lake_is_reported_never_copied_through(tmp_path):
    """⚠ An unplanned reparse point in the MAIN `.lake` must not be followed by copytree."""
    repo, robot = _robot(tmp_path)
    elsewhere = tmp_path / "ELSEWHERE"
    elsewhere.mkdir()
    (elsewhere / "big.bin").write_bytes(b"would be copied if followed")
    _junction(repo / ".lake" / "cache", elsewhere)

    out = robot.worktree("add", ref="HEAD")
    wt = Path(out["path"])

    assert any(s.startswith(".lake/cache:") for s in out["not_provisioned"]), out
    assert not (wt / ".lake" / "cache").exists()


def test_an_unknown_lake_entry_is_copied_not_shared(tmp_path):
    """⭐ DENYLIST OF SHARING. A `.lake` entry added later must be ISOLATED by default; sharing
    is opt-in by name in `_LAKE_SHARED`."""
    repo, robot = _robot(tmp_path)
    (repo / ".lake" / "config").mkdir()
    (repo / ".lake" / "config" / "x.json").write_bytes(b"{}")

    out = robot.worktree("add", ref="HEAD")
    wt = Path(out["path"])

    assert ".lake/config" in out["copied"], out
    assert not _is_reparse(wt / ".lake" / "config")


def test_the_reaper_over_the_new_layout_keeps_mathlib(tmp_path, monkeypatch):
    """The reaper removes through `worktree(remove)` and inherits its guards — pinned, because a
    reaper meeting a layout it does not expect is the risk the consumer named."""
    repo, robot = _robot(tmp_path)
    wt = Path(robot.worktree("add", ref="HEAD")["path"])
    monkeypatch.setattr(robot, "_reaper_policy",
                        lambda: {"clean_after_hours": 1, "dirty_after_hours": 1})
    monkeypatch.setattr(robot, "_worktree_age_hours", lambda p: 1000.0)

    out = robot._reap_worktrees()

    assert [r["path"] for r in out["removed"]] == [str(wt)], out
    assert not wt.exists()
    assert (repo / ".lake" / "packages" / "mathlib" / "Mathlib.lean").exists()
    assert (repo / ".lake" / "build" / "lib" / "ZeroParadox" / "Core.olean").exists()


def test_worktree_add_says_where_to_run_the_checkers(tmp_path):
    """⚠⚠ THE NON-OBVIOUS STEP, RETURNED AT THE MOMENT THE WORKTREE IS CREATED.

    ZeroParadox 2026-09-05, healing eleven commits by worktree: running the worktree's own
    checker with cwd still at the MAIN repo produced a V16 refusal whose evidence path read
    `../../../../../../../Workspace/ZeroParadox/tools/verify/check_claude_md.py`. Setting
    `ZPLEDGER_CONFIG` did NOT fix it; setting cwd to the worktree did.

    ⭐ Same silent-root defect that would have broken `where.py` on its move — a tool resolving
    ROOT from its INVOCATION context rather than its TARGET, failing in a way that looks like a
    different problem. **A traversal path in an evidence field is the tell**, and V16 is a good
    place for it to surface because it refuses rather than recording a wrong-tree verdict.

    ⚠ `worktree add` handed back a path and said nothing about where to stand. This is a fact
    returned with the path, not a rule anyone has to remember."""
    from core.engine import GitRobot

    repo = _shared_dep_repo(tmp_path)
    robot = GitRobot(repo=str(repo), data_path=str(tmp_path / "ops.jsonl"), actor="t",
                     scratch=tmp_path / "scratch")
    out = robot.worktree("add", ref="HEAD")

    assert out["run_tools_from"] == out["path"], (
        "the receipt must name the directory to stand in, not leave it inferred")
    # ⛔⛔ THE NOTE MUST NAME A PER-COMMAND PROPERTY, NEVER A ONE-TIME `cd`. `CWD-1`,
    # ZeroParadox 2026-09-20: this field used to read "cd into this directory before running any
    # checker". An agent briefed with that sentence DID cd, and its NEXT tool call built in the
    # MAIN checkout, because a shell's working directory does not survive a tool-call boundary in
    # that harness. Four PDFs went dirty in the shared tree and it re-blocked a pending
    # fast-forward. **The advice was not wrong, it was unsurvivable** — `cd` is state, and state
    # set in one call is a bet on an execution model the caller may not have.
    assert "per command" in out["note"], (
        "a one-time `cd` is a race: it reads as obeyed right up until a tool-call boundary "
        "discards it. The instruction must be a property of EVERY command.")
    assert "Set-Location" in out["note"] and "cd <path> &&" in out["note"], (
        "name the inline form for both shells — an agent that cannot see HOW to comply "
        "per-command will fall back to the bare `cd` this exists to replace")
    assert "MAIN checkout" in out["note"], (
        "say where the work LANDS when it goes wrong; 'it will not work' is not actionable")
    assert "V16" in out["note"], (
        "the note must name where the mistake SURFACES — it presents as a config problem")
