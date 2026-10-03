"""`owed_between(base, tip)`: what a MERGE imported that nobody judged — and only that.

⭐ Asked for by ZeroParadox 2026-10-03, policy ratified by Tim: unchanged bytes imported by a merge
owe nothing (a verdict travels with its blob); unjudged imported bytes are owed by the importing
session, and the bill must show AT MERGE TIME. Measured 2026-09-24: a session-start merge turned a
two-file defect fix into a fourteen-signature bill nobody saw until push.

⛔ THE OBJECT IS THE WHOLE POINT. `can_push`'s ratchet takes its base from the parent of the
OLDEST commit in the range — for a merge, the branch's FORK POINT — so over `pre..merge` it also
bills THIS side's own unjudged changes as if the merge had brought them. The headline test pins
both answers side by side so the difference cannot be argued away.
"""

import subprocess

from core import canpush as canpush_mod
from test_can_push import _blob, _rec

STEP = "check_encoding"       # scope ["*"] in the sample registry


def _git(tmp_path, *args):
    return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(tmp_path, name, body):
    (tmp_path / name).write_bytes(body.encode())
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", name)
    return _git(tmp_path, "rev-parse", "HEAD")


def _merge_fixture(tmp_path):
    """main and side fork; main changes ours.md, side changes theirs.md; side merges into main.

    Returns (pre-merge main HEAD, merge commit)."""
    _git(tmp_path, "init", "-q", "-b", "main", str(tmp_path))
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):
        _git(tmp_path, *args)
    _commit(tmp_path, "ours.md", "ours base")
    _commit(tmp_path, "theirs.md", "theirs base")
    _git(tmp_path, "checkout", "-q", "-b", "side")
    _commit(tmp_path, "theirs.md", "theirs CHANGED on side")
    _git(tmp_path, "checkout", "-q", "main")
    pre = _commit(tmp_path, "ours.md", "ours CHANGED on main")
    _git(tmp_path, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    return pre, _git(tmp_path, "rev-parse", "HEAD")


def _owed(ledger, tmp_path, base, tip, records=(), admission=(STEP,)):
    return canpush_mod.owed_between(records=list(records), config=ledger.config,
                                    repo=str(tmp_path), base=base, tip=tip,
                                    admission=None if admission is None else list(admission))


def test_a_merge_owes_what_it_imported_and_not_what_this_side_changed(ledger, tmp_path):
    """⭐⭐ THE HEADLINE. Neither changed file is judged. The merge imported `theirs.md`; `ours.md`
    was this side's own change. owed_between names ONLY theirs.md — and can_push over the same
    range names BOTH, which is why owed_between exists."""
    pre, merge = _merge_fixture(tmp_path)

    out = _owed(ledger, tmp_path, pre, merge)

    assert out["checked"] is True
    assert out["owed_paths"] == ["theirs.md"], out
    assert out["owed_count"] == 1
    assert out["owed_by_step"] == {STEP: 1}
    assert out["owed"][0]["git_blob_id"] == _blob(tmp_path, merge, "theirs.md")

    # ⚠ THE CONTRAST, measured rather than asserted in prose: the push ratchet over the same
    # range bills this side's own change as well, because its base is the fork point.
    cp = canpush_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                           rev_range=f"{pre}..{merge}", admission=[STEP],
                           commit_admission=[STEP])
    cp_paths = sorted({o["path"] for o in cp["ratchet"]["owed"]})
    assert cp_paths == ["ours.md", "theirs.md"], cp_paths


def test_imported_bytes_already_judged_owe_nothing(ledger, tmp_path):
    """⭐ Policy (a): a verdict binds (step, path, blob), so it travels with the bytes."""
    pre, merge = _merge_fixture(tmp_path)
    side_blob = _blob(tmp_path, merge, "theirs.md")
    records = [_rec(STEP, "theirs.md", side_blob, "side-tip")]

    out = _owed(ledger, tmp_path, pre, merge, records)

    assert out["owed_count"] == 0, out
    assert out["owed_paths"] == []


def test_no_admission_is_unknown_never_zero(ledger, tmp_path):
    """⛔ ABSENCE IS NEVER SUCCESS. Nobody said what judges, so nothing can be priced."""
    pre, merge = _merge_fixture(tmp_path)

    out = _owed(ledger, tmp_path, pre, merge, admission=None)

    assert out["checked"] is False
    assert out["owed_count"] is None


def test_an_unresolvable_base_is_unknown_never_zero(ledger, tmp_path):
    _pre, merge = _merge_fixture(tmp_path)

    out = _owed(ledger, tmp_path, "no-such-ref", merge)

    assert out["checked"] is False
    assert out["owed_count"] is None
    assert "resolve" in out["why"]
