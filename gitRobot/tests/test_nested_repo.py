"""`.claude-local` is a SEPARATE repository with its own remote and its own history.

The same verbs apply to it — stage, commit, push — they simply must not overlap
with the production repo. Two rules follow, and both are asserted here:

  * it has **no gate pipeline of its own**, so `push` there requires no preflight.
    Demanding a verdict from a pipeline that does not exist would make the
    operation permanently unreachable rather than safe.
  * its contents must **never enter the production repo**. Prod ignores the
    directory, but a refusal that says *why* beats a git error that says
    "ignored".
"""

import subprocess

import pytest

from core.errors import RefusalError


def _init(path):
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=str(path), check=True, capture_output=True)


@pytest.fixture
def nested(repo, tmp_path):
    """`.claude-local` inside the main checkout, with its own remote — the real shape."""
    local = repo / ".claude-local"
    local.mkdir()
    _init(local)
    (local / "notes.md").write_text("private notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(local), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(local),
                   check=True, capture_output=True)

    bare = tmp_path / "ZeroParadoxLocal.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=str(local),
                   check=True, capture_output=True)

    # prod ignores it, exactly as the real repo does
    (repo / ".gitignore").write_text(".claude-local/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=str(repo), check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "ignore local"], cwd=str(repo),
                   check=True, capture_output=True)
    return local


LOCAL = ".claude-local"


# -- the full flow works there ------------------------------------------------

def test_stage_commit_push_all_work_on_the_nested_repo(robot, nested, tmp_path):
    (nested / "notes.md").write_text("private notes\nplus more\n", encoding="utf-8")
    assert robot.stage(["-A"], repo_mode=LOCAL)["decision"] == "allowed"

    msg = tmp_path / "m.txt"
    msg.write_text("update notes\n", encoding="utf-8")
    result = robot.commit(str(msg), reason="sync notes", repo_mode=LOCAL)
    assert result["decision"] == "allowed" and result["ok"]

    pushed = robot.push("master", reason="back up private notes", repo_mode=LOCAL)
    assert pushed["decision"] == "allowed" and pushed["ok"]


def test_push_there_needs_no_preflight(robot, nested, tmp_path):
    """The main repo refuses without one; this repo has no pipeline to run."""
    with pytest.raises(RefusalError, match="no passing pre-push preflight"):
        robot.push("illustrated", reason="main needs a verdict")
    assert robot.push("master", reason="local does not",
                      repo_mode=LOCAL)["decision"] == "allowed"


def test_commit_there_runs_no_gate(robot, nested, tmp_path):
    """No pipeline exists there, so a missing one must not be reported as a failure."""
    (nested / "notes.md").write_text("changed\n", encoding="utf-8")
    robot.stage(["-A"], repo_mode=LOCAL)
    msg = tmp_path / "m.txt"
    msg.write_text("no gate here\n", encoding="utf-8")
    result = robot.commit(str(msg), repo_mode=LOCAL)
    assert result["decision"] == "allowed"
    assert not result.get("gates")


def test_reads_target_the_nested_repo(robot, nested):
    out = robot.read("log", ["-1", "--pretty=%s"], repo_mode=LOCAL)["output"]
    assert "initial" in out
    assert robot.read("rev-parse", ["--abbrev-ref", "HEAD"],
                      repo_mode=LOCAL)["output"] == "master"


# -- the audit must name the tree that was touched ----------------------------

def test_the_audit_records_the_nested_repo_not_the_main_one(robot, nested, tmp_path):
    """A log that recorded the main repo's HEAD for a nested write would be a log
    that lies about what happened."""
    (nested / "notes.md").write_text("x\n", encoding="utf-8")
    robot.stage(["-A"], repo_mode=LOCAL)
    record = robot.audit.read()[-1]
    assert record["args"]["repo"] == LOCAL
    assert record["branch"] == "master"                  # the nested branch
    assert record["head"] != robot.git.head()            # not the main repo's HEAD


# -- the overlap rule ---------------------------------------------------------

@pytest.mark.parametrize("path", [".claude-local/notes.md", ".claude-local",
                                  "./.claude-local/sub/x.md", ".claude-local\\notes.md"])
def test_staging_a_nested_path_into_prod_is_refused(robot, nested, path):
    """The two histories are deliberately disjoint. Prod ignores the directory, but a
    refusal that says WHY beats a git error that says "ignored"."""
    with pytest.raises(RefusalError, match="SEPARATE repository") as exc:
        robot.stage([path])
    assert f"repo_mode='{LOCAL}'" in exc.value.alternative


def test_the_nested_repo_is_still_reachable_by_its_own_mode(robot, nested):
    """The overlap guard must not break the legitimate path it points at."""
    (nested / "notes.md").write_text("y\n", encoding="utf-8")
    assert robot.stage(["notes.md"], repo_mode=LOCAL)["decision"] == "allowed"


def test_an_unknown_repo_mode_is_still_refused(robot, nested):
    from core.errors import UsageError
    with pytest.raises(UsageError, match="does not accept repository paths"):
        robot.push("master", reason="r", repo_mode="C:/Workspace/SomethingElse")
