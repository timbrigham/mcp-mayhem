"""Regression tests for the two defects found by the 2026-08-22 verification run.

**Defect 1 — a long gate run destroyed itself.** `preflight` blocked for ~155s on the
real repository. FastMCP calls a synchronous tool function directly on the event loop, so
the whole server stalled; the process supervisor's 30s health poll saw it Down, restarted
it, and killed the run mid-flight. The reported symptom was "the call window is too short",
but a longer window would have changed nothing — the supervisor kills first. Worse, the
attempt left NO audit row at all, so "failed" and "never ran" were indistinguishable: the
audit log's own founding lesson, recurring one door over.

**Defect 2 — `explain` lost its long form across a restart.** It degraded to "the durable
copy is the audit record", which was true and useless: the alternative is the half a caller
needs, and the spec never said it could be lost.
"""

import inspect
import json
import os

import pytest

from core.errors import RefusalError


# -- Defect 1: the run must outlive the call, and leave a trace either way -----

def test_preflight_returns_immediately_and_records_a_start_row(robot, repo, fake_gate):
    """It must not hold the caller (or the event loop) open for the pipeline."""
    fake_gate(0)
    result = robot.preflight(reason="checking")
    assert result["state"] == "running" and result["run_id"]

    started = [r for r in robot.audit.read() if r["decision"] == "started"]
    assert len(started) == 1
    assert started[0]["op"] == "preflight"
    assert started[0]["run_id"] == result["run_id"]
    assert started[0]["pid"] == os.getpid()


def test_the_verdict_lands_afterwards_and_authorises_a_push(robot, repo, tmp_path,
                                                            fake_gate, ledger_ok):
    fake_gate(0)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    robot.stage(["a.txt"])
    msg = tmp_path / "m.txt"
    msg.write_text("m\n", encoding="utf-8")
    robot.commit(str(msg))

    robot.preflight(wait=True)
    assert robot.preflight_status()["state"] == "passed"
    # ⚠ the push is authorised by the LEDGER (ledger_ok), not by the preflight
    # above — which is now only a way to RUN the checks, never to certify them.
    assert robot.push("illustrated", reason="shipping")["decision"] == "allowed"


def test_a_running_preflight_is_not_a_verdict(robot, repo, fake_gate, ledger_refuses):
    """An in-flight run must not authorise a push — and now it CANNOT, because a
    preflight no longer authorises anything at all. Kept as a control rather than
    deleted: the property is what matters, and a future refactor could reintroduce
    the shortcut it names."""
    fake_gate(0)
    robot.preflight()
    with pytest.raises(RefusalError, match="admission set is not satisfied"):
        robot.push("illustrated", reason="too early")


def test_a_second_preflight_is_refused_while_one_runs(robot, fake_gate):
    fake_gate(0)
    robot.preflight()
    with pytest.raises(RefusalError, match="already running"):
        robot.preflight()


def test_an_interrupted_run_reports_died_not_silence(robot, repo, fake_gate):
    from core import ledger as ledger_client
    """THE defect. A run killed mid-flight left no trace at all, so it was
    indistinguishable from never having been attempted. It must now be nameable."""
    fake_gate(0)
    head = robot.git.head()
    # A start row from a process that is gone, with no outcome row after it —
    # exactly what a supervisor kill leaves behind.
    robot.audit.append(actor="test", op="preflight", args={}, decision="started",
                       head=head, branch=robot.git.branch(), tree=robot.git.tree_state(),
                       detail="pre-push preflight started", run_id="deadrun")
    records = robot.audit.read()
    records[-1]["pid"] = 999999                      # a pid that is not this process
    robot.audit.path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8")

    state = robot.preflight_status()
    assert state["state"] == "died"
    assert state["run_id"] == "deadrun"
    assert "interrupted" in state["note"]
    # and it still does not authorise a push
    with pytest.raises(ledger_client.LedgerUnreachable):
        robot.push("illustrated", reason="shipping on a corpse")


def test_status_reports_no_preflight_before_any_run(robot):
    assert robot.preflight_status()["state"] == "none"


# -- the structural control that keeps the root cause from returning ----------

def test_every_mcp_tool_is_async(robot):
    """The root cause, asserted directly.

    FastMCP runs a sync tool function ON the event loop — a blocking call in one
    stalls the whole server, including the health endpoint the supervisor polls.
    Every tool must therefore be a coroutine that offloads its work. If someone
    adds a plain `def` tool later, this fails rather than the server dying in
    production at the first slow call.
    """
    pytest.importorskip("mcp")
    from gitrobot_server import server

    # The registry, not the module namespace: @mcp.tool() returns the plain
    # function, so scanning attributes would silently find nothing and pass.
    tools = server.mcp._tool_manager._tools
    assert len(tools) >= 9, "tool registry looks empty — the introspection broke"
    for name, tool in sorted(tools.items()):
        assert inspect.iscoroutinefunction(tool.fn), (
            f"MCP tool {name!r} is a plain def. FastMCP will run it on the event loop, "
            f"so any blocking work stalls the server and the supervisor will kill it "
            f"mid-call. Make it `async def` and await _guard(...)."
        )


# -- Defect 2: explain must survive a restart ---------------------------------

def test_explain_survives_a_restart(robot, tmp_path, dirty):
    """A fresh process has an empty in-process cache; the alternative has to come
    back from the log, because the alternative is the useful half."""
    with pytest.raises(RefusalError) as exc:
        robot.guard_tier1("reset", ["--hard"])
    rid = exc.value.refusal_id

    from core.engine import GitRobot
    restarted = GitRobot(robot.repo, data_path=robot.audit.path, actor="test",
                         scratch=tmp_path / "scratch")
    assert restarted._refusals == {}                 # nothing cached in the new process
    explained = restarted.explain(rid)
    assert "worktree" in explained["alternative"]
    assert "durable copy" not in explained["alternative"]


def test_the_alternative_is_persisted_on_every_refusal(robot, dirty):
    for sub, args in [("reset", ["--hard"]), ("clean", ["-fd"]), ("stash", [])]:
        with pytest.raises(RefusalError):
            robot.guard_tier1(sub, args)
    for record in robot.audit.read():
        assert record["decision"] == "refused"
        assert record["alternative"], f"{record['op']} refusal persisted no alternative"


# -- worktree cleanup (a stranded foreign worktree was found in the wild) -----

def test_a_worktree_outside_the_scratch_area_can_be_removed(robot, tmp_path):
    """Removability keys on git's OWN list, not on gitRobot's scratch directory, so
    a leftover from another session is cleanable instead of stranded."""
    foreign = tmp_path / "someone-elses-scratchpad" / "wt3"
    foreign.parent.mkdir(parents=True)
    assert robot.git.run(["worktree", "add", "--detach", str(foreign), "HEAD"]).ok

    assert robot.worktree("remove", name=str(foreign))["decision"] == "allowed"
    assert not foreign.exists()


def test_worktree_prune_clears_records_for_vanished_directories(robot, tmp_path):
    foreign = tmp_path / "gone" / "wt"
    foreign.parent.mkdir(parents=True)
    robot.git.run(["worktree", "add", "--detach", str(foreign), "HEAD"])
    import shutil
    shutil.rmtree(foreign)                            # directory gone, record remains

    assert robot.worktree("prune")["decision"] == "allowed"
    assert str(foreign) not in robot.worktree("list")["output"]


# -- ⭐⭐ the aborted provision, measured by ZeroParadox 2026-08-25 -------------
#
# `worktree(action='add', ref='HEAD')` failed partway and left a directory holding
# only `.git` and `tracked.txt` -- a partial checkout git had never registered. From
# then on:
#
#   add    -> fatal: '…/gitrobot-worktrees/HEAD-7c335d652168' already exists
#   remove -> REFUSED, "is not a worktree of this repository"
#   prune  -> the OPPOSITE case; it clears records whose directories are GONE
#
# Every sanctioned route closed, while the refusal confidently named two of them.
# It was cleared with a raw `Remove-Item` -- a session working AROUND this server,
# which §2 says is what a refusal without a workable alternative invents.
#
# Two independent defects, and each gets its own control below: the path was a pure
# function of the ref, so provisions collided by construction; and `remove` keyed
# only on git's list, so an unregistered directory was unreachable.

def _listed(robot):
    """git prints worktree paths with FORWARD slashes even on Windows. Comparing raw
    strings makes an `in` assertion pass for the wrong reason -- it can never match,
    so a "not in" check would go green against a worktree that is still registered."""
    return robot.worktree("list")["output"].replace("\\", "/")


def _fwd(path):
    return str(path).replace("\\", "/")


def _orphan(robot, name="HEAD-deadbeef"):
    """A partial provision: the shape an aborted `add` leaves behind."""
    d = robot.scratch / name
    d.mkdir(parents=True)
    (d / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
    (d / "tracked.txt").write_text("half a checkout\n", encoding="utf-8")
    return d


def test_two_adds_at_one_ref_do_not_collide(robot):
    """⭐⭐ THE ROOT CAUSE. The directory name used to be `<ref>-<hash of that same
    path>` -- a pure function of the ref, so a second provision at one ref could only
    ever land on the first one's directory. Concurrent rounds at a single tree is
    exactly what the review-snapshot design would make routine."""
    first = robot.worktree("add", ref="HEAD")
    second = robot.worktree("add", ref="HEAD")
    assert first["ok"] and second["ok"], (first, second)
    assert first["path"] != second["path"]
    listed = _listed(robot)
    assert _fwd(first["path"]) in listed and _fwd(second["path"]) in listed


def test_an_aborted_provision_does_not_block_the_next_add(robot):
    """⚠ THE SYMPTOM AS REPORTED, end to end: a leftover directory in the scratch
    root must not poison every future `add` at that ref."""
    _orphan(robot)
    assert robot.worktree("add", ref="HEAD")["ok"] is True


def test_an_orphaned_directory_can_be_removed(robot):
    """⭐⭐ THE REFUSAL THAT NAMED TWO IMPOSSIBLE REMEDIES. git cannot list what it
    never registered, and prune is for the opposite case. Under gitRobot's own scratch
    root -- which it created and which holds nothing else -- removing it IS the
    workable alternative the refusal owed."""
    d = _orphan(robot)
    out = robot.worktree("remove", name=str(d))
    assert out["decision"] == "allowed"
    assert out["orphan"] is True
    assert not d.exists()


def test_the_orphan_cleanup_is_audited_as_its_own_operation(robot):
    """⚠ An orphan cleanup and a real worktree removal are different facts. Logging
    both as `worktree.remove` would make "gitRobot deleted a directory git knew
    nothing about" indistinguishable from an ordinary teardown, afterwards."""
    d = _orphan(robot)
    robot.worktree("remove", name=str(d))
    assert robot.audit.read()[-1]["op"] == "worktree.remove_orphan"


def test_an_unknown_path_outside_the_scratch_root_is_still_refused(robot, tmp_path):
    """⚠⚠ THE CONTROL THAT KEEPS THE FIX FROM BEING A HOLE, and it is the whole
    reason the orphan branch is bounded to one directory. Outside that root, a path
    git does not know about is somebody's actual work, and deleting it is not this
    server's call."""
    real = tmp_path / "someones-work"
    real.mkdir()
    (real / "notes.md").write_text("not a worktree\n", encoding="utf-8")
    with pytest.raises(RefusalError):
        robot.worktree("remove", name=str(real))
    assert (real / "notes.md").exists()


def test_the_scratch_root_itself_is_not_removable(robot):
    """⚠ The bound must exclude its own edge, or one call empties every live
    worktree gitRobot has provisioned."""
    robot.scratch.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RefusalError):
        robot.worktree("remove", name=str(robot.scratch))
    assert robot.scratch.exists()


def test_a_registered_worktree_is_still_removed_by_git_not_by_rmtree(robot):
    """⚠ The orphan branch must not swallow the ordinary case: a REGISTERED worktree
    under the scratch root still goes through `git worktree remove`, so git's record
    is cleared rather than left behind as the exact orphan this fixes."""
    added = robot.worktree("add", ref="HEAD")
    out = robot.worktree("remove", name=added["path"])
    assert out["decision"] == "allowed"
    assert out.get("orphan") is None
    assert _fwd(added["path"]) not in _listed(robot)
