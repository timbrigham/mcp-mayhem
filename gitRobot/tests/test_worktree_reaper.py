"""The worktree reaper — the leak D1 turns from incidental into routine.

⚠ Every horizon here is written RELATIVE to now. A fixture pinned to a literal date is a
test with an expiry, which this project has already paid for once today.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from core.engine import GitRobot

CONFIG = Path(__file__).resolve().parents[1] / "config" / "worktree_reaper.v1.json"


def _run(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "main"
    r.mkdir()
    _run(r, "init", "-q")
    _run(r, "config", "user.email", "t@e.com")
    _run(r, "config", "user.name", "t")
    (r / "f.txt").write_text("a", encoding="utf-8")
    (r / "gate_round.json").write_text('{"round": 0}', encoding="utf-8")
    _run(r, "add", "-A")
    _run(r, "commit", "-qm", "base")
    return r


@pytest.fixture
def policy():
    """Swap the harness policy for the duration of one test, then put it back.

    ⛔⛔ BYTES, NOT `write_text`. On Windows `Path.write_text` translates LF to CRLF, so a
    fixture that reads a tracked config and writes it back does not RESTORE it — it rewrites
    every line ending. Measured 2026-09-08: this fixture put 10 CRLF into
    `worktree_reaper.v1.json` and verdictLedger's cross-server hygiene control caught it in a
    suite this file is not even part of. A teardown that corrupts what it was protecting is
    worse than no teardown, because the damage looks like someone else's commit.
    """
    original = CONFIG.read_bytes()

    def apply(doc):
        body = json.dumps(doc) if isinstance(doc, dict) else doc
        CONFIG.write_bytes(body.encode("utf-8"))
    yield apply
    CONFIG.write_bytes(original)


def _bot(repo, tmp_path):
    # ⚠ SCRATCH IS PER-TEST. conftest asserts nothing leaks into the SHARED scratch, and this
    # file deliberately leaves worktrees behind — the dirty-inside-horizon cases are KEPT by
    # design, which is the whole point of them. Without an isolated scratch those passes would
    # be indistinguishable from the leak the reaper exists to remove.
    return GitRobot(str(repo), data_path=str(tmp_path / "ops.jsonl"), actor="test",
                    scratch=str(tmp_path / "scratch"))


def _path_of(receipt):
    # ⚠ `_receipt` FLATTENS `extra` INTO THE TOP LEVEL. There is no "extra" key on the way
    # out, which is worth pinning here because the first draft of this file assumed there was.
    return receipt["path"]


def _age(path, hours):
    """Backdate a worktree so the reaper sees it as abandoned."""
    old = time.time() - hours * 3600
    for target in (Path(path), Path(path) / ".git"):
        if target.exists():
            os.utime(target, (old, old))


def _names(rows):
    return {Path(r["path"]).name for r in rows}


def test_a_clean_worktree_past_48h_is_reaped(repo, tmp_path, policy):
    policy({"clean_after_hours": 48, "dirty_after_hours": 168, "session_state": []})
    bot = _bot(repo, tmp_path)
    path = _path_of(bot.worktree("add", ref="HEAD", name="stale"))
    _age(path, 60)
    out = bot.worktree("reap")
    assert Path(path).name in _names(out["removed"]), (
        "a clean worktree untouched for 60h holds nothing to lose — its commits live in the "
        "shared object store — and must be reaped")


def test_a_DIRTY_worktree_inside_7_days_is_KEPT(repo, tmp_path, policy):
    """⛔ THE WHOLE REASON THERE ARE TWO HORIZONS. Destroying uncommitted work while
    reporting success is this project's archetypal failure — the reason reset --hard, clean
    and stash are refused outright. A reaper removing a dirty tree on a timer does exactly
    what those refused verbs do, on a schedule, with nobody watching."""
    policy({"clean_after_hours": 48, "dirty_after_hours": 168, "session_state": []})
    bot = _bot(repo, tmp_path)
    path = _path_of(bot.worktree("add", ref="HEAD", name="working"))
    (Path(path) / "f.txt").write_text("uncommitted edit", encoding="utf-8")
    _age(path, 60)
    out = bot.worktree("reap")
    assert Path(path).name not in _names(out["removed"])
    kept = {Path(r["path"]).name: r for r in out["kept"]}
    assert kept[Path(path).name]["dirty"] is True


def test_a_dirty_worktree_past_7_days_IS_reaped(repo, tmp_path, policy):
    """⚠ The other edge. (b) — skip dirty forever — was rejected: it is the leak wearing a
    warning label. Seven days is a grace period, not an exemption."""
    policy({"clean_after_hours": 48, "dirty_after_hours": 168, "session_state": []})
    bot = _bot(repo, tmp_path)
    path = _path_of(bot.worktree("add", ref="HEAD", name="abandoned"))
    (Path(path) / "f.txt").write_text("long abandoned edit", encoding="utf-8")
    _age(path, 200)
    out = bot.worktree("reap")
    assert Path(path).name in _names(out["removed"])


def test_session_state_alone_does_NOT_count_as_dirty(repo, tmp_path, policy):
    """⭐⭐ THE FIELD THAT MAKES THE 48h HORIZON REACHABLE AT ALL.

    Tim, 2026-09-08: gate_round.json is "a session State tracking variable" — tracked at
    {round: 0} and rewritten at runtime, so it is dirty essentially always. Counting it would
    mark EVERY worktree dirty and nothing would ever take the 48h path.

    ⚠ It is not a tolerance for a file we allow to be dirty. The reaper asks "does this tree
    hold work someone would lose", and session state is not work.
    """
    policy({"clean_after_hours": 48, "dirty_after_hours": 168,
            "session_state": ["gate_round.json"]})
    bot = _bot(repo, tmp_path)
    path = _path_of(bot.worktree("add", ref="HEAD", name="sessiondirty"))
    (Path(path) / "gate_round.json").write_text('{"round": 5}', encoding="utf-8")
    _age(path, 60)
    out = bot.worktree("reap")
    assert Path(path).name in _names(out["removed"]), (
        "only session state changed, so the tree holds no work and the 48h horizon applies. "
        "If this fails, nothing will ever be reaped at 48h.")


def test_the_main_checkout_is_never_reaped(repo, tmp_path, policy):
    policy({"clean_after_hours": 0.0001, "dirty_after_hours": 0.0001, "session_state": []})
    bot = _bot(repo, tmp_path)
    _age(repo, 10000)
    out = bot.worktree("reap")
    removed = {Path(r["path"]).resolve() for r in out["removed"]}
    assert Path(repo).resolve() not in removed, (
        "the main checkout must be excluded structurally, not by luck of its horizon")


def test_no_policy_means_no_reaping(repo, tmp_path, policy):
    """⛔ ABSENT CONFIG DISABLES IT, never defaults a horizon. A built-in default would be a
    second copy of the policy, and the direction it would be wrong in is DELETION."""
    policy("{ not json")
    bot = _bot(repo, tmp_path)
    path = _path_of(bot.worktree("add", ref="HEAD", name="orphan"))
    _age(path, 10000)
    out = bot.worktree("reap")
    assert out["configured"] is False
    assert out["removed"] == []


def test_a_kept_dirty_worktree_NAMES_what_made_it_dirty(repo, tmp_path, policy):
    """⭐ SO THE `session_state` LIST CANNOT DECAY IN SILENCE.

    ZeroParadox, 2026-09-08: "session_state is now a list someone maintains. The next
    runtime-rewritten tracked file that is not on it re-creates the defect for that one file,
    quietly." Right — and the answer is not a smarter list. It is that a chronically-dirty
    unlisted file appears in the same kept row on every hourly sweep, forever, which a reader
    eventually notices. A list that decays in silence is a defect; a list that decays in the
    output is a to-do.
    """
    policy({"clean_after_hours": 48, "dirty_after_hours": 168,
            "session_state": ["gate_round.json"]})
    bot = _bot(repo, tmp_path)
    path = _path_of(bot.worktree("add", ref="HEAD", name="undeclared"))
    # one declared session-state file and one that nobody put on the list
    (Path(path) / "gate_round.json").write_text('{"round": 9}', encoding="utf-8")
    (Path(path) / "f.txt").write_text("an unlisted chronically-dirty file", encoding="utf-8")
    _age(path, 60)
    out = bot.worktree("reap")
    kept = {Path(r["path"]).name: r for r in out["kept"]}
    row = kept[Path(path).name]
    assert row["dirty"] is True
    assert "f.txt" in row["dirty_paths"], "the reason it was kept must be NAMED, not counted"
    assert "gate_round.json" not in row["dirty_paths"], (
        "a declared session-state path must not appear — it carries no information about "
        "whether this tree holds work")


def test_every_tree_aware_mutation_RECORDS_which_tree(repo, tmp_path):
    """⭐⭐ THE AUDIT LOG MUST SAY WHERE A MUTATION HAPPENED, NOT JUST THAT IT DID.

    Found 2026-09-08, the day D1 landed. `gitRobot` audits mutations and its receipts carried
    `repo` — which is `repo_mode`, and is NOT the worktree. So a commit made in an isolated
    reviewer worktree and a commit made in the shared checkout produced IDENTICAL receipts.

    ⛔ AND IT COST A WRONG CONCLUSION BEFORE IT COST ANYTHING ELSE. Reading `repo: "main"` off
    the log, I was about to report that D1's first live round had NOT authored in a worktree.
    It had — the git parentage proves it, two lines from one parent joined by a merge that a
    branch commit would never have needed. The instrument did not measure the thing, and the
    field's absence read as evidence of absence.

    ⚠ D1 makes this routine: reviewers now commit in worktrees as the normal path. An audit
    trail that cannot distinguish isolated from shared authorship cannot answer the question
    the workflow exists to make answerable.

    This is a RATCHET: it walks the engine for every method taking a `worktree` parameter and
    fails if one does not put it in its receipt. The next tree-aware mutation cannot ship
    without it.
    """
    import inspect
    from core.engine import GitRobot as Engine

    tree_aware = []
    for name, fn in inspect.getmembers(Engine, inspect.isfunction):
        if name.startswith("_"):
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        if "worktree" in sig.parameters:
            tree_aware.append(name)
    assert tree_aware, "the scrape found no worktree-aware methods — the check broke, not the code"

    src = inspect.getsource(Engine)
    missing = []
    for name in tree_aware:
        body = inspect.getsource(getattr(Engine, name))
        if "read" == name:
            continue                       # read is not a mutation and writes no receipt
        if '"worktree": worktree' not in body:
            missing.append(name)
    assert not missing, (
        "these mutations accept a worktree but do not record it, so their receipts cannot say "
        "WHICH TREE the change landed in: %s" % missing)


def test_every_call_signature_in_instructions_is_actually_callable():
    """A CONFIDENTLY WRONG INSTRUCTION IS WORSE THAN NO INSTRUCTION.

    Added `instructions` on 2026-09-08 after an outside cold-read audit found no server here
    used more than one of the three channels that teach a caller. Then wrote the call
    signatures from MEMORY rather than from the schemas, and the same auditor caught it:

        sjv            view() REQUIRES kind.  validate(collection=...) takes NO parameters.
        verdictLedger  inventory(ref=...) REQUIRES action.

    Their judgement is the one to keep: "As written this is a DOWNGRADE from having no START
    HERE, because it directs confidently to a dead end." A cold agent burns two failed calls
    and still lacks the answer it was promised.

    IT IS LOAD-BEARING FOR THIS AUDIENCE. Under deferred tool loading an agent receives
    `instructions` but NOT the schemas, so a signature written in prose is the only signature
    it has until it spends a schema load.

    This control is the auditor's own suggestion and closes the CLASS rather than the two
    instances. Run against the live surface it found FIVE problems, two of which the manual
    audit missed - a bare merge() and find(count_only=True) - which is the argument for a
    parser over a proofread.
    """
    import asyncio
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from mcpcommon.instructioncheck import unsupported_calls

    from gitrobot_server import server as _srv

    tools = [{"name": t.name, "inputSchema": t.inputSchema}
             for t in asyncio.run(_srv.mcp.list_tools())]
    problems = unsupported_calls(_srv.mcp.instructions or "", tools)
    assert not problems, "uncallable signatures in instructions: %s" % problems


# -- one declaration of what counts as session state --------------------------

def test_the_arc_handshake_is_a_member_of_the_session_state_set():
    """⛔⛔ THERE WERE THREE DECLARATIONS OF THIS ONE FACT AND NOTHING COMPARED THEM.

    `_ARC_STATE`, `_EXPECTED_LOCAL` (forty lines apart in engine.py) and a `session_state` list
    in the reaper config. Found 2026-09-13 while diagnosing a `D1` carrier merge that had hung
    TWICE on the same defect — and the middle one was added six days earlier, in a commit that
    argued for one source and no second copies.

    ⭐ `_ARC_STATE` keeps its own name because the commit guard reads its `round` FIELD, which
    no pattern list carries. This asserts it is a MEMBER of the set rather than a rival
    declaration of it, so the two cannot drift.
    """
    from fnmatch import fnmatch
    from core.engine import GitRobot

    assert any(fnmatch(GitRobot._ARC_STATE, pat) for pat in GitRobot._SESSION_STATE), (
        "_ARC_STATE %r matches no pattern in _SESSION_STATE %r — the guard and the reaper "
        "would disagree about whether the arc counter is work"
        % (GitRobot._ARC_STATE, GitRobot._SESSION_STATE))


def test_the_reaper_config_carries_no_second_session_state_list():
    """⚠ A CONFIG VALUE THE CODE IGNORES IS A COPY THAT READS AS AUTHORITY. The key was removed
    when the declaration consolidated; a tombstone explains why. If someone re-adds it, the
    reaper will silently keep using the constant and the file will lie."""
    import json
    from pathlib import Path

    cfg = json.loads((Path(__file__).resolve().parents[1] / "config"
                      / "worktree_reaper.v1.json").read_text(encoding="utf-8"))
    assert "session_state" not in cfg, (
        "the reaper reads GitRobot._SESSION_STATE; a `session_state` key here is a second "
        "declaration nothing consults")
    assert "_session_state_moved" in cfg, "the tombstone must survive, or the absence reads as an omission"
