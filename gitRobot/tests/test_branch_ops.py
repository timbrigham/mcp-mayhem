"""The two Tier 2 rows that were specified but unbuilt, plus the fetch/pull gap.

  * `checkout` / `switch` / `merge` / `rebase` — "refuses if the tree is dirty"
  * `branch -d/-D` / `tag` / `rm` — "mediated and audited"

Two deliberate divergences from the spec, both asserted here so they are decisions
on the record rather than omissions:

  1. **No acknowledgement parameter.** §3 says these refuse "unless explicitly
     acknowledged". An acknowledgement flag is shaped exactly like the `force` /
     `allow_dirty` parameters §6 requires to stay ABSENT, and that absence is the
     property the whole design rests on. The escape is an action — commit, or take
     a worktree — both of which leave the work somewhere a person can find it.
  2. **No force-delete and no tag deletion.** `branch -D` strands commits in the
     reflog, which expires; a pushed tag is a public marker that here mints a
     permanent DOI. Neither is an agent decision, so neither verb exists.
"""

import subprocess

import pytest

from core.errors import RefusalError, UsageError


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _branch(repo, name, *, commit=True):
    """A second branch, optionally carrying a commit of its own."""
    _git(repo, "branch", name)
    if commit:
        _git(repo, "switch", name)
        (repo / f"{name}.txt").write_text(name, encoding="utf-8")
        _git(repo, "add", f"{name}.txt")
        _git(repo, "commit", "-q", "-m", f"work on {name}")
        _git(repo, "switch", "illustrated")
    return name


# -- dirty-tree refusal, and its named escape ---------------------------------

@pytest.mark.parametrize("call", ["switch", "merge", "rebase"])
def test_branch_movement_refused_while_dirty(robot, repo, dirty, call):
    _branch(repo, "feature")
    kwargs = {"reason": "r"} if call in ("merge", "rebase") else {}
    target = "feature" if call != "rebase" else "feature"
    with pytest.raises(RefusalError, match="tree is dirty") as exc:
        getattr(robot, call)(target, **kwargs)
    # the escape is an action, not a flag
    assert "worktree" in exc.value.alternative and "commit" in exc.value.alternative
    assert "no acknowledgement flag" in exc.value.alternative
    # and the uncommitted work is untouched
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT\n"
    assert (repo / "untracked.txt").exists()


def test_switch_works_on_a_clean_tree(robot, repo):
    _branch(repo, "feature")
    assert robot.switch("feature")["decision"] == "allowed"
    assert robot.git.branch() == "feature"


def test_switch_can_create(robot, repo):
    assert robot.switch("brand-new", create=True)["decision"] == "allowed"
    assert robot.git.branch() == "brand-new"


def test_merge_works_on_a_clean_tree_and_is_audited(robot, repo):
    _branch(repo, "feature")
    result = robot.merge("feature", reason="folding the feature in")
    assert result["decision"] == "allowed" and result["ok"]
    record = robot.audit.read()[-1]
    assert record["op"] == "merge" and record["reason"] == "folding the feature in"


def test_merge_requires_a_reason(robot, repo):
    _branch(repo, "feature")
    with pytest.raises(UsageError, match="reason"):
        robot.merge("feature", reason="  ")


@pytest.mark.parametrize("call,args", [
    ("switch", ("--orphan",)), ("merge", ("-X",)), ("rebase", ("--onto",))])
def test_branch_names_that_are_flags_are_rejected(robot, call, args):
    kwargs = {"reason": "r"} if call in ("merge", "rebase") else {}
    with pytest.raises(UsageError):
        getattr(robot, call)(args[0], **kwargs)


# -- rebase: the published-history guard --------------------------------------

def test_rebase_refuses_to_rewrite_pushed_commits(robot, repo):
    """The guard that matters: rewriting history other checkouts already have
    breaks them, and the damage only surfaces when someone else pulls."""
    _git(repo, "switch", "-c", "base")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "base work")
    _git(repo, "switch", "illustrated")
    # a commit that IS already on the remote
    (repo / "published.txt").write_text("p", encoding="utf-8")
    _git(repo, "add", "published.txt")
    _git(repo, "commit", "-q", "-m", "published")
    _git(repo, "push", "-q", "origin", "illustrated")

    with pytest.raises(RefusalError, match="already on the remote") as exc:
        robot.rebase("base", reason="tidying")
    assert "merge" in exc.value.alternative


def test_rebase_allows_rewriting_only_unpushed_commits(robot, repo):
    _git(repo, "switch", "-c", "base")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "base work")
    _git(repo, "switch", "illustrated")
    (repo / "local.txt").write_text("l", encoding="utf-8")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "-q", "-m", "local only")

    assert robot.rebase("base", reason="tidying local work")["decision"] == "allowed"


# -- branch deletion: safe only -----------------------------------------------

def test_branch_delete_removes_a_merged_branch(robot, repo):
    _branch(repo, "feature")
    robot.merge("feature", reason="merged")
    assert robot.branch_delete("feature", reason="merged, no longer needed"
                               )["decision"] == "allowed"
    assert "feature" not in robot.read("branch", ["--list"])["output"]


def test_branch_delete_refuses_an_unmerged_branch(robot, repo):
    """`-D` would strand the commits in the reflog, which expires. gitRobot has no
    force-delete, so the refusal names what keeps the work reachable instead."""
    _branch(repo, "orphan")
    with pytest.raises(RefusalError, match="not merged anywhere") as exc:
        robot.branch_delete("orphan", reason="cleaning up")
    assert "tag" in exc.value.alternative
    assert "orphan" in robot.read("branch", ["--list"])["output"]


def test_branch_delete_refuses_the_current_branch(robot, repo):
    with pytest.raises(RefusalError, match="currently checked out"):
        robot.branch_delete("illustrated", reason="oops")


def test_branch_delete_requires_a_reason(robot, repo):
    _branch(repo, "feature", commit=False)
    with pytest.raises(UsageError, match="reason"):
        robot.branch_delete("feature", reason="")


# -- tags: create only ---------------------------------------------------------

def test_tag_create_makes_an_annotated_tag(robot, repo):
    assert robot.tag_create("v0.1", reason="first cut")["decision"] == "allowed"
    assert "v0.1" in robot.read("tag", ["--list"])["output"]


def test_there_is_no_tag_deletion_verb(robot):
    """A pushed tag is a public marker — here, releases mint permanent DOIs."""
    assert not hasattr(robot, "tag_delete")
    with pytest.raises(RefusalError):
        robot.read("tag", ["-d", "v0.1"])


# -- git rm --------------------------------------------------------------------

def test_remove_files_deletes_named_tracked_paths(robot, repo):
    (repo / "doomed.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "doomed.txt")
    _git(repo, "commit", "-q", "-m", "add doomed")   # committed: nothing to lose

    result = robot.remove_files(["doomed.txt"], reason="superseded")
    assert result["decision"] == "allowed"
    assert not (repo / "doomed.txt").exists()


def test_remove_files_refuses_a_path_with_staged_but_uncommitted_content(robot, repo):
    """Staged-not-committed is work that exists nowhere else either."""
    (repo / "fresh.txt").write_text("x\n", encoding="utf-8")
    robot.stage(["fresh.txt"])
    result = robot.remove_files(["fresh.txt"], reason="never mind")
    assert result["decision"] == "failed"          # git declines; gitRobot has no -f
    assert (repo / "fresh.txt").exists()


def test_remove_files_cached_untracks_but_keeps_the_file(robot, repo):
    result = robot.remove_files(["tracked.txt"], reason="should not be tracked",
                                cached=True)
    assert result["decision"] == "allowed"
    assert (repo / "tracked.txt").exists()          # still on disk


def test_remove_files_refuses_a_bulk_token(robot):
    with pytest.raises(RefusalError, match="delete everything"):
        robot.remove_files(["."], reason="tidy")


def test_remove_files_refuses_a_file_with_uncommitted_work(robot, repo, dirty):
    """git would need -f to discard the modification, and -f is not available here."""
    with pytest.raises(RefusalError, match="uncommitted modifications") as exc:
        robot.remove_files(["tracked.txt"], reason="removing")
    assert "cached=True" in exc.value.alternative
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT\n"


def test_remove_files_requires_a_reason_and_named_paths(robot):
    with pytest.raises(UsageError, match="at least one path"):
        robot.remove_files([], reason="r")
    with pytest.raises(UsageError, match="reason"):
        robot.remove_files(["tracked.txt"], reason=" ")


# -- fetch, and the pull pointer ----------------------------------------------

def test_fetch_updates_remote_refs_and_is_audited(robot):
    result = robot.fetch()
    assert result["decision"] == "allowed"
    assert robot.audit.read()[-1]["op"] == "fetch"


def test_refused_reads_name_the_tool_that_does_the_job(robot):
    """A caller told only "not allow-listed" goes looking for a way around the wall.
    Naming the door beside it is the difference."""
    cases = {"pull": "fetch", "commit": "commit(message_file", "add": "stage(paths",
             "push": "preflight()", "rm": "remove_files", "merge": "merge(branch"}
    for op, expected in cases.items():
        with pytest.raises(RefusalError) as exc:
            robot.read(op, [])
        assert expected in exc.value.alternative, f"read({op!r}) did not point anywhere useful"


def test_pull_specifically_explains_why_it_is_split(robot):
    with pytest.raises(RefusalError) as exc:
        robot.read("pull", [])
    assert "fetch+merge" in exc.value.alternative or "fetch" in exc.value.alternative
    assert "merge" in exc.value.alternative
