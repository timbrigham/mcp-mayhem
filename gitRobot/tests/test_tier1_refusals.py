"""Tier 1: the operations that destroy uncommitted work and report success.

Each test asserts three things, because a refusal that only does the first is not
much of a guard:

  1. the operation is refused;
  2. the uncommitted work is STILL THERE afterwards (the property, not the proxy);
  3. the refusal names what to do instead — a refusal without an alternative is
     how bypasses get invented.

No git hook fires on any of these, which is why they are refused at the tool
surface rather than gated: there is nowhere downstream to catch them.
"""

import pytest

from core.errors import RefusalError


def _assert_work_survives(repo):
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT\n"
    assert (repo / "untracked.txt").exists()


@pytest.mark.parametrize("args", [
    ["--hard"],
    ["--hard", "HEAD"],
    ["--hard", "HEAD~1"],
    ["--merge"],
    ["--keep"],
], ids=["hard", "hard-HEAD", "hard-HEAD~1", "merge", "keep"])
def test_reset_hard_family_refused(robot, dirty, args):
    with pytest.raises(RefusalError) as exc:
        robot.guard_tier1("reset", args)
    assert "worktree" in exc.value.alternative
    _assert_work_survives(dirty)


@pytest.mark.parametrize("sub,args", [
    ("checkout", ["--", "."]),
    ("checkout", ["--", "tracked.txt"]),
    ("switch", ["--", "."]),
    ("restore", ["tracked.txt"]),
], ids=["checkout-dot", "checkout-file", "switch", "restore"])
def test_checkout_paths_refused(robot, dirty, sub, args):
    with pytest.raises(RefusalError):
        robot.guard_tier1(sub, args)
    _assert_work_survives(dirty)


@pytest.mark.parametrize("args", [["-fd"], ["-f"], ["-fdx"], []])
def test_clean_refused(robot, dirty, args):
    with pytest.raises(RefusalError):
        robot.guard_tier1("clean", args)
    _assert_work_survives(dirty)


@pytest.mark.parametrize("args", [[], ["push"], ["-u"], ["pop"], ["drop"]])
def test_stash_mutations_refused(robot, dirty, args):
    with pytest.raises(RefusalError):
        robot.guard_tier1("stash", args)
    _assert_work_survives(dirty)


def test_restore_staged_is_not_tier1(robot, dirty):
    """`restore --staged` unstages but leaves the file — it destroys nothing.

    Included so the guard is shown to be shaped like the harm, not like the word
    'restore'. Over-refusal is its own failure: it teaches callers to route around."""
    robot.guard_tier1("restore", ["--staged", "tracked.txt"])


def test_stash_list_is_readable(robot, dirty):
    """Inspecting the stash changes nothing; only stashing does."""
    robot.guard_tier1("stash", ["list"])
    assert robot.read("stash", ["list"])["ok"]


def test_every_tier1_refusal_names_an_alternative(robot, dirty):
    """The property that keeps the refusals from breeding workarounds."""
    for sub, args in [("reset", ["--hard"]), ("clean", ["-fd"]),
                      ("checkout", ["--", "."]), ("stash", [])]:
        with pytest.raises(RefusalError) as exc:
            robot.guard_tier1(sub, args)
        assert exc.value.alternative.strip(), f"{sub} refusal has no alternative"
        assert "INSTEAD:" in str(exc.value)


def test_a_refusal_is_audited_and_explainable(robot, dirty):
    """A guard that only logs when it lets something through cannot answer
    'did this ever fire?' — the question that matters after an incident."""
    with pytest.raises(RefusalError) as exc:
        robot.guard_tier1("reset", ["--hard"])
    rid = exc.value.refusal_id
    assert rid

    records = robot.audit.read()
    assert len(records) == 1
    assert records[0]["decision"] == "refused"
    assert records[0]["op"] == "reset"
    assert rid in records[0]["detail"]

    explained = robot.explain(rid)
    assert "worktree" in explained["alternative"]


def test_reads_are_not_audited(robot):
    """Tier 3 must stay cheap; audit volume would bury the signal."""
    robot.read("status")
    robot.read("log", ["-1", "--oneline"])
    assert robot.audit.read() == []
