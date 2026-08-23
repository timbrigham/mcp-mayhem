"""GRB-3 and GRB-4 — two defects measured in the shipped server on 2026-08-23.

Both are the same species: a tool that ANSWERS, but whose answer cannot be trusted or
cannot be read. Neither crashes, and that is why both survived to be measured in
production rather than caught in a test.
"""

import json
import subprocess

import pytest


# =============================================================================
# GRB-3 — status() counted UNTRACKED files as STAGED
# =============================================================================

def _short(repo):
    return subprocess.run(["git", "status", "--short"], cwd=str(repo),
                          capture_output=True, text=True).stdout.splitlines()


def test_untracked_files_are_not_counted_as_staged(robot, repo):
    """⭐⭐ GRB-3 EXACTLY. Measured twice: `staged: 3, untracked: 3` for the same three
    files, while `--short` showed three `??` and `diff --cached` was empty.

    A caller that trusts that count commits nothing and believes it committed three
    files — the tool did not fail, it lied, which is why it reached production.
    """
    for name in ("a.txt", "b.txt", "c.txt"):
        (repo / name).write_text(name, encoding="utf-8")

    state = robot.git.tree_state()
    assert state["untracked"] == 3
    assert state["staged"] == 0, "untracked files were counted as staged (GRB-3)"


def test_the_counts_agree_with_status_short(robot, repo):
    """⚠ THE DETECTOR 12i ASKS FOR: "status()'s counts must agree with --short."
    Pinning the invariant rather than the one arrangement that exposed it."""
    (repo / "untracked.txt").write_text("new", encoding="utf-8")
    (repo / "tracked.txt").write_text("modified", encoding="utf-8")
    (repo / "staged.txt").write_text("staged", encoding="utf-8")
    robot.stage(["staged.txt"])

    lines = _short(repo)
    state = robot.git.tree_state()

    assert state["untracked"] == sum(1 for ln in lines if ln.startswith("??"))
    assert state["staged"] == sum(1 for ln in lines
                                  if ln[:1] not in (" ", "?", "!") and ln[:2] != "??")
    assert state["unstaged"] == sum(1 for ln in lines
                                    if ln[1:2] not in (" ", "?") and ln[:2] != "??")


def test_a_staged_then_modified_file_counts_in_both(robot, repo):
    """⚠ Both halves are real and must not collapse: the index has one version and
    the work tree another. Committing now records the FIRST."""
    (repo / "tracked.txt").write_text("staged version", encoding="utf-8")
    robot.stage(["tracked.txt"])
    (repo / "tracked.txt").write_text("further edit", encoding="utf-8")

    state = robot.git.tree_state()
    assert state["staged"] == 1 and state["unstaged"] == 1


def test_a_clean_tree_reports_nothing_anywhere(robot, repo):
    state = robot.git.tree_state()
    assert state == {"dirty": False, "staged": 0, "unstaged": 0, "untracked": 0,
                     "ignored": 0, "unmerged": 0}


def test_status_would_block_push_still_works_with_untracked_present(robot, repo):
    """⚠ GRB-3 reproduced only when untracked files were present, so the control has
    to keep them present."""
    (repo / "junk.txt").write_text("x", encoding="utf-8")
    assert robot.status()["tree"]["staged"] == 0


# =============================================================================
# GRB-4 — history() was unusable at its own default
# =============================================================================

def _fill(robot, n=40):
    for i in range(n):
        robot.audit.append(actor="test", op="push" if i % 2 else "commit",
                           args={"branch": "illustrated", "noise": "x" * 400},
                           decision="refused" if i % 3 else "allowed",
                           head="a" * 40, branch="illustrated",
                           tree={"dirty": False}, detail="y" * 800,
                           reason=f"reason {i}")


def test_history_is_a_summary_by_default(robot):
    """⭐⭐ GRB-4 EXACTLY. `limit=30` returned 194,296 characters across 818 lines —
    it had to be dumped to a file and grepped. §7 gives this tool one job, answering
    "did this guard ever fire?" after an incident, and it could not be read at the
    moment it was needed. A tool that must be post-processed has the wrong default.
    """
    _fill(robot)
    out = robot.history(limit=30)
    assert len(json.dumps(out)) < 8000, "still unreadable at its own default (GRB-4)"
    assert set(out["records"][0]) <= set(robot.SUMMARY_FIELDS)
    assert "detail" not in out["records"][0]


def test_the_full_record_is_one_flag_away(robot):
    """⚠ Truncation that cannot be undone trades an unreadable log for a lossy one."""
    _fill(robot, n=5)
    full = robot.history(limit=5, full=True)
    assert "detail" in full["records"][0] and "args" in full["records"][0]


def test_history_names_what_it_left_out(robot):
    """⭐ A window that renders like the whole log is the exact shape this project
    keeps fixing. Silence about 780 skipped rows would be that shape again."""
    _fill(robot, n=40)
    out = robot.history(limit=10)
    assert out["count"] == 10 and out["total"] >= 40
    assert out["omitted"] >= 30
    assert "most recent 10 of" in out["note"]


def test_a_complete_window_carries_no_note(robot):
    """⚠ …and it must not cry wolf when nothing WAS omitted."""
    _fill(robot, n=3)
    out = robot.history(limit=100)
    assert out["omitted"] == 0 and out["note"] is None


def test_history_shows_the_MOST_RECENT_entries(robot):
    """⚠ An incident is always at the end of the log. A window taken from the front
    is the one window guaranteed not to contain it."""
    _fill(robot, n=30)
    out = robot.history(limit=3)
    assert [r["reason"] for r in out["records"]] == ["reason 27", "reason 28",
                                                     "reason 29"]


@pytest.mark.parametrize("kwargs,check", [
    ({"decision": "refused"}, lambda r: r["decision"] == "refused"),
    ({"op": "push"}, lambda r: r["op"] == "push"),
])
def test_history_can_answer_the_incident_question_directly(robot, kwargs, check):
    """⚠ "Did this guard ever fire?" should be one call, not a grep over a dump."""
    _fill(robot, n=30)
    out = robot.history(limit=50, **kwargs)
    assert out["records"] and all(check(r) for r in out["records"])
