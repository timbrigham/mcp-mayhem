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
    """Swap the harness policy for the duration of one test, then put it back."""
    original = CONFIG.read_text(encoding="utf-8")

    def apply(doc):
        CONFIG.write_text(json.dumps(doc) if isinstance(doc, dict) else doc, encoding="utf-8")
    yield apply
    CONFIG.write_text(original, encoding="utf-8")


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
