"""Tier 1: the operations that destroy uncommitted work and report success.

Each case asserts three things, because a refusal that only does the first is not much of a
guard:

  1. the operation is refused;
  2. the uncommitted work is STILL THERE afterwards (the property, not the proxy);
  3. the refusal names what to do instead - a refusal without an alternative is how bypasses
     get invented.

No git hook fires on any of these, which is why they are refused at the tool surface rather
than gated: there is nowhere downstream to catch them.

⛔ UNTIL 2026-10-09 EVERY CASE HERE CALLED `guard_tier1` DIRECTLY, AND NOTHING ELSE CALLED IT.
The 18 cases proved the classifier, not the tool: `_assert_work_survives` held trivially because
no git ran. Found by an outside adversarial review. Every case now goes through `read`, the one
entry point that accepts a free-form subcommand, with uncommitted work present, and the two
layers that refuse there (this classifier and the allow-list) are each shown to hold alone.
"""

import asyncio

import pytest

import core.tiers as tiers
from core.errors import RefusalError

RESET = [["--hard"], ["--hard", "HEAD"], ["--hard", "HEAD~1"], ["--merge"], ["--keep"]]
PATHS = [("checkout", ["--", "."]), ("checkout", ["--", "tracked.txt"]),
         ("switch", ["--", "."]), ("restore", ["tracked.txt"])]
CLEAN = [["-fd"], ["-f"], ["-fdx"], []]
STASH = [[], ["push"], ["-u"], ["pop"], ["drop"]]
CASES = ([("reset", a) for a in RESET] + PATHS + [("clean", a) for a in CLEAN]
         + [("stash", a) for a in STASH])


def _assert_work_survives(repo):
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "PRECIOUS EDIT\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "PRECIOUS NEW FILE\n"


def _id(case):
    sub, args = case
    return " ".join([sub, *args]) or sub


def test_there_are_eighteen_cases():
    """A floor, so an edit that empties a list cannot pass as 'all refused'."""
    assert len(CASES) == 18


@pytest.mark.parametrize("sub,args", CASES, ids=[_id(c) for c in CASES])
def test_refused_through_read_and_the_work_survives(robot, dirty, sub, args):
    with pytest.raises(RefusalError) as exc:
        robot.read(sub, args)
    assert exc.value.alternative.strip(), f"{sub} refusal names no alternative"
    assert "INSTEAD:" in str(exc.value)
    _assert_work_survives(dirty)


@pytest.mark.parametrize("sub,args", CASES, ids=[_id(c) for c in CASES])
def test_the_classifier_alone_refuses_through_read(robot, dirty, monkeypatch, sub, args):
    """Allow-list and flag check removed (`clean -f` would otherwise stop at the flag check,
    which refuses `-f` on its own): the classifier must still stop the op, and the work survive."""
    monkeypatch.setattr(tiers, "is_read", lambda op, a: True)
    monkeypatch.setattr(tiers, "forbidden_token", lambda a, op=None: None)
    with pytest.raises(RefusalError) as exc:
        robot.read(sub, args)
    assert "uncommitted" in str(exc.value).lower()
    _assert_work_survives(dirty)


@pytest.mark.parametrize("sub,args", CASES, ids=[_id(c) for c in CASES])
def test_the_allow_list_alone_refuses_through_read(robot, dirty, monkeypatch, sub, args):
    """Classifier and flag check removed: the allow-list must still stop the op, and the work
    must survive."""
    monkeypatch.setattr(tiers, "tier1_refusal", lambda op, a: None)
    monkeypatch.setattr(tiers, "forbidden_token", lambda a, op=None: None)
    with pytest.raises(RefusalError) as exc:
        robot.read(sub, args)
    assert "not an allow-listed read" in str(exc.value)
    _assert_work_survives(dirty)


def test_refused_through_the_registered_mcp_tool(repo, dirty, tmp_path, monkeypatch):
    """The function an agent's tool call actually reaches, taken from the tool registry."""
    pytest.importorskip("mcp")
    from gitrobot_server import server
    monkeypatch.setattr(server, "REPO", repo)
    monkeypatch.setattr(server, "DATA", tmp_path / "mcp_ops.jsonl")
    read_tool = server.mcp._tool_manager._tools["read"].fn
    for sub, args in CASES:
        out = asyncio.run(read_tool(op=sub, args=args))
        assert out["ok"] is False and out["error_type"] == "refusal", (sub, args, out)
        _assert_work_survives(dirty)
    # the control: a permitted read through the same function, on the same dirty tree
    ok = asyncio.run(read_tool(op="status", args=["--short"]))
    assert ok["ok"] is True and "tracked.txt" in ok["output"]


def test_refused_through_the_cli(repo, dirty, tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    base = [sys.executable, "-m", "core.cli", "--repo", str(repo),
            "--data", str(tmp_path / "cli_ops.jsonl"), "read"]
    for sub, args in [("reset", ["--hard"]), ("clean", ["-fd"]), ("checkout", ["--", "."]),
                      ("stash", [])]:
        r = subprocess.run(base + [sub, *args], cwd=root, capture_output=True, text=True)
        assert r.returncode != 0 and "INSTEAD:" in (r.stdout + r.stderr), (sub, r.stdout, r.stderr)
        _assert_work_survives(dirty)
    ok = subprocess.run(base + ["stash", "list"], cwd=root, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr


def test_restore_staged_is_not_tier1(robot, dirty):
    """CLASSIFIER ONLY, stated as such. `restore --staged` unstages but leaves the file, so the
    classifier must not call it Tier 1: over-refusal teaches callers to route around. It is not
    an allow-listed read, so through `read` it is still refused - by the allow-list."""
    assert tiers.tier1_refusal("restore", ["--staged", "tracked.txt"]) is None
    with pytest.raises(RefusalError, match="not an allow-listed read"):
        robot.read("restore", ["--staged", "tracked.txt"])
    _assert_work_survives(dirty)


def test_stash_list_is_readable_on_a_dirty_tree(robot, dirty):
    """The control for the stash cases: inspecting the stash changes nothing."""
    assert robot.read("stash", ["list"])["ok"]
    _assert_work_survives(dirty)


def test_a_refusal_is_audited_and_explainable(robot, dirty):
    """A guard that only logs when it lets something through cannot answer 'did this ever
    fire?' - the question that matters after an incident."""
    with pytest.raises(RefusalError) as exc:
        robot.read("reset", ["--hard"])
    rid = exc.value.refusal_id
    assert rid

    records = robot.audit.read()
    assert len(records) == 1
    assert records[0]["decision"] == "refused"
    assert records[0]["op"] == "read", "the audit row names the tool the caller used"
    assert rid in records[0]["detail"]

    explained = robot.explain(rid)
    assert "worktree" in explained["alternative"]


def test_reads_are_not_audited(robot):
    """Tier 3 must stay cheap; audit volume would bury the signal."""
    robot.read("status")
    robot.read("log", ["-1", "--oneline"])
    assert robot.audit.read() == []
