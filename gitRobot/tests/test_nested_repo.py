"""`.claude-local` is a SEPARATE repository with its own remote and its own history.

The same verbs apply to it — stage, commit, push — they simply must not overlap
with the production repo. Two rules follow, and both are asserted here:

  * it has **no gate pipeline of its own** and no verdicts in the ledger, so `push`
    there requires no inventory. Demanding a verdict from a pipeline that does not
    exist would make the operation permanently unreachable rather than safe.
  * its contents must **never enter the production repo**. Prod ignores the
    directory, but a refusal that says *why* beats a git error that says
    "ignored".
"""

import subprocess

import pytest

from core.errors import RefusalError


LOCAL = ".claude-local"


# -- the full flow works there ------------------------------------------------

def test_stage_commit_push_all_work_on_the_nested_repo(robot, nested_local, tmp_path):
    (nested_local / "notes.md").write_text("private notes\nplus more\n", encoding="utf-8")
    assert robot.stage(["-A"], repo_mode=LOCAL)["decision"] == "allowed"

    msg = tmp_path / "m.txt"
    msg.write_text("update notes\n", encoding="utf-8")
    result = robot.commit(str(msg), reason="sync notes", repo_mode=LOCAL)
    assert result["decision"] == "allowed" and result["ok"]

    pushed = robot.push("master", reason="back up private notes", repo_mode=LOCAL)
    assert pushed["decision"] == "allowed" and pushed["ok"]


def test_push_there_needs_no_verdict(robot, nested_local, tmp_path, ledger_refuses):
    """The main repo refuses without a satisfied admission set; this repo has no
    pipeline, no verdicts and nothing to record them against. Demanding an inventory
    here would make the operation permanently unreachable rather than safe."""
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="main needs a verdict")
    assert robot.push("master", reason="local does not",
                      repo_mode=LOCAL)["decision"] == "allowed"


def test_commit_there_runs_no_gate(robot, nested_local, tmp_path):
    """No pipeline exists there, so a missing one must not be reported as a failure."""
    (nested_local / "notes.md").write_text("changed\n", encoding="utf-8")
    robot.stage(["-A"], repo_mode=LOCAL)
    msg = tmp_path / "m.txt"
    msg.write_text("no gate here\n", encoding="utf-8")
    result = robot.commit(str(msg), repo_mode=LOCAL)
    assert result["decision"] == "allowed"
    assert not result.get("gates")


def test_reads_target_the_nested_repo(robot, nested_local):
    out = robot.read("log", ["-1", "--pretty=%s"], repo_mode=LOCAL)["output"]
    assert "initial" in out
    assert robot.read("rev-parse", ["--abbrev-ref", "HEAD"],
                      repo_mode=LOCAL)["output"] == "master"


# -- the audit must name the tree that was touched ----------------------------

def test_the_audit_records_the_nested_repo_not_the_main_one(robot, nested_local, tmp_path):
    """A log that recorded the main repo's HEAD for a nested write would be a log
    that lies about what happened."""
    (nested_local / "notes.md").write_text("x\n", encoding="utf-8")
    robot.stage(["-A"], repo_mode=LOCAL)
    record = robot.audit.read()[-1]
    assert record["args"]["repo"] == LOCAL
    assert record["branch"] == "master"                  # the nested branch
    assert record["head"] != robot.git.head()            # not the main repo's HEAD


# -- the overlap rule ---------------------------------------------------------

@pytest.mark.parametrize("path", [".claude-local/notes.md", ".claude-local",
                                  "./.claude-local/sub/x.md", ".claude-local\\notes.md"])
def test_staging_a_nested_path_into_prod_is_refused(robot, nested_local, path):
    """The two histories are deliberately disjoint. Prod ignores the directory, but a
    refusal that says WHY beats a git error that says "ignored"."""
    with pytest.raises(RefusalError, match="SEPARATE repository") as exc:
        robot.stage([path])
    assert f"repo_mode='{LOCAL}'" in exc.value.alternative


def test_the_nested_repo_is_still_reachable_by_its_own_mode(robot, nested_local):
    """The overlap guard must not break the legitimate path it points at."""
    (nested_local / "notes.md").write_text("y\n", encoding="utf-8")
    assert robot.stage(["notes.md"], repo_mode=LOCAL)["decision"] == "allowed"


def test_an_unknown_repo_mode_is_still_refused(robot, nested_local):
    from core.errors import UsageError
    with pytest.raises(UsageError, match="does not accept repository paths"):
        robot.push("master", reason="r", repo_mode="C:/Workspace/SomethingElse")
