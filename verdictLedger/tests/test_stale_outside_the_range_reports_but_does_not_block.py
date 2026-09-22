"""Subject-staleness over paths a range does not touch is REPORTED, never blocking.

⛔⛔ THE MEASURED CASE, 2026-09-18. Six ZeroParadox commits touching only `tools/verify/` were
blocked because `editorial` read STALE over ONE prose file they never touched —
`ZeroParadox/Computability/Kleene.md` — which had entered editorial's scope that same morning,
in the ride-along strike.

⚠⚠ THE ASYMMETRY IS THE ARGUMENT, and it was measured at that moment:

    prior_art   247 paths NEVER examined at these bytes   -> blocked nothing
    adversary    24 paths NEVER examined at these bytes   -> blocked nothing
    editorial     1 path examined once, at older bytes    -> blocked six unrelated commits

**Both states say the same thing about the bytes being published: nobody has judged them.** The
only difference is whether the step happened to look at an OLDER version — which has no bearing
on what ships. The gate blocked on the strictly less alarming of the two.

⭐ THE REAL RISK IS COVERED BY THE RATCHET, which refuses any path the range CHANGES that lacks
a verdict at its new bytes. Post-ratchet, staleness over an untouched path is a BACKLOG artifact,
and the backlog is accepted and ratcheted forward. Tim's ruling.
"""

import subprocess

import pytest

from conftest import good
from core import canpush as canpush_mod
from core import inventory as inventory_mod
# ⚠ ALIASED: this module defines its own `_rec` with a different signature, and an
# unaliased import would be shadowed by it — silently, since both are callable.
from test_can_push import _blob as _blob_at, _rec as _range_rec

STEP = "check_invariants"


def _build(ledger, files, records, changed):
    return inventory_mod.build(config=ledger.config, records=records, action="commit",
                               files=files, ref="a" * 40, admission=[STEP],
                               changed=changed)


def _rec(path, blob):
    return good(subjects=[{"git_blob_id": blob, "path": path}])


def test_stale_over_an_untouched_path_does_not_block(ledger):
    """⭐⭐ THE HEADLINE: the range touches `touched.md`; the stale file is a different one."""
    files = {"touched.md": "c" * 40, "elsewhere.md": "d" * 40}
    records = [_rec("touched.md", "c" * 40), _rec("elsewhere.md", "b" * 40)]   # elsewhere moved

    inv = _build(ledger, files, records, changed={"touched.md"})
    row = [r for r in inv["rows"] if r["step"] == STEP][0]

    assert row["status"] == "STALE", "it is still stale — the backlog must stay visible"
    assert row["stale_out_of_range"] is True
    assert inv["complete"] is True, "a path this range never touched refused the push"


def test_stale_over_a_path_the_range_touches_still_blocks(ledger):
    """⛔ THE GUARD, UNCHANGED. If the range CHANGES the stale path, this push publishes bytes
    the step has not judged, and it must refuse."""
    files = {"touched.md": "c" * 40}
    records = [_rec("touched.md", "b" * 40)]        # examined at OTHER bytes

    inv = _build(ledger, files, records, changed={"touched.md"})
    row = [r for r in inv["rows"] if r["step"] == STEP][0]

    assert row["status"] == "STALE"
    assert row["stale_out_of_range"] is False
    assert inv["complete"] is False


def test_a_ref_query_keeps_blocking_because_the_question_has_no_answer(ledger):
    """⛔⛔ `changed is None` MEANS THE CALLER ASKED ABOUT A REF, NOT A RANGE — so "did this push
    touch it" has no answer at all. It keeps blocking.

    ⚠ This is the `absence is never success` rule applied to the new field: an exemption that
    silently applies when its precondition is UNKNOWN is a fail-open wearing a ruling.
    """
    files = {"whatever.md": "c" * 40}
    records = [_rec("whatever.md", "b" * 40)]

    inv = _build(ledger, files, records, changed=None)
    row = [r for r in inv["rows"] if r["step"] == STEP][0]

    assert row["status"] == "STALE"
    assert row["stale_out_of_range"] is False, "an unknown range must not grant the exemption"
    assert inv["complete"] is False


def test_the_row_still_names_the_stale_paths_so_the_backlog_stays_visible(ledger):
    """⚠ GRANDFATHERED IS NOT HIDDEN. A row that dropped out of the stale list would conceal the
    backlog rather than defer it — and the whole model depends on the backlog being countable."""
    files = {"touched.md": "c" * 40, "elsewhere.md": "d" * 40}
    records = [_rec("touched.md", "c" * 40), _rec("elsewhere.md", "b" * 40)]

    inv = _build(ledger, files, records, changed={"touched.md"})
    row = [r for r in inv["rows"] if r["step"] == STEP][0]

    assert row["stale_paths"] == ["elsewhere.md"]
    assert "NOT BLOCKING" in row["why"] and "elsewhere.md" in row["why"]


# =============================================================================
# ⛔⛔ AND THE SAME FORGIVENESS, APPLIED AT THE TIP, WAS A FAIL-OPEN
# =============================================================================

def _commit_files(tmp_path, files, msg):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", msg], cwd=tmp_path, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()


def _init_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True,
                   capture_output=True)
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


def _three_commits(tmp_path):
    """base, then a commit touching ONLY other.md, then a tip touching ONLY doc.md.

    ⚠ THE SHAPE IS THE POINT: `other.md` is changed BY THE RANGE and is absent from the TIP
    COMMIT'S OWN DIFF. That is the gap between "what this push publishes" and "what the last
    commit touched", and it is where the forgiveness above was being applied to the wrong set.
    A merge tip is the worst case in the wild, since its first-parent diff can be tiny.
    """
    _init_repo(tmp_path)
    base = _commit_files(tmp_path, {"doc.md": "d0", "other.md": "o0"}, "base")
    mid = _commit_files(tmp_path, {"other.md": "o1"}, "touch other.md ONLY")
    tip = _commit_files(tmp_path, {"doc.md": "d1"}, "touch doc.md ONLY")
    return base, mid, tip


def test_the_tip_prices_staleness_against_the_push_not_against_one_commit(ledger, tmp_path):
    """⛔⛔ REPRODUCED BEFORE IT WAS FIXED, WHICH IS THE ONLY REASON IT COUNTS AS A CONTROL.

    Three mechanisms each behaved correctly on its own and composed into a push that published
    unjudged bytes:

      1. INTERMEDIATES did not gate the step — it is admitted at `push` and not at `commit`.
      2. THE TIP forgave it — the stale path was outside the TIP COMMIT'S diff, so the
         out-of-range rule above fired, even though the PUSH publishes those bytes.
      3. THE RATCHET skipped it — `_judging_steps` consults only steps that declare a scope,
         deliberately, because silence is not a claim to everything.

    The probe returned `allowed: True` over a tip row reading `stale: ['check_prose']`,
    `required 2, satisfied 1, complete True`. ⚠ It was not live on the consumer's registry —
    all four push-only steps declare scopes — but the push-only SET was created that same day
    by narrowing `check_hashes` to the tip, and the other three scopes were under active edit
    that afternoon. The safety rested on a coincidence between two files, one of them in a repo
    this one does not own and cannot enforce.

    ⭐ THE FIX IS A SPLIT, NOT A TIGHTENING: `changed` still prices `min_coverage` per commit
    (Tim, 2026-09-07, and still right), while `published` prices staleness — the range at the
    tip, the commit's own diff beneath it.
    """
    base, mid, tip = _three_commits(tmp_path)
    scoped, scopeless = "check_encoding", "check_prose"    # scope ['*']  vs  no scope at all

    records = [
        # the scoped step is judged at every byte the range changes, so IT never blocks
        _range_rec(scoped, "doc.md", _blob_at(tmp_path, mid, "doc.md"), mid),
        _range_rec(scoped, "other.md", _blob_at(tmp_path, mid, "other.md"), mid),
        _range_rec(scoped, "doc.md", _blob_at(tmp_path, tip, "doc.md"), tip),
        _range_rec(scoped, "other.md", _blob_at(tmp_path, tip, "other.md"), tip),
        # the scopeless step judged other.md at the BASE bytes only -> STALE from `mid` onward
        _range_rec(scopeless, "other.md", _blob_at(tmp_path, base, "other.md"), base),
    ]
    result = canpush_mod.check(
        records=records, config=ledger.config, repo=str(tmp_path),
        rev_range=f"{base}..{tip}",
        admission=[scoped, scopeless],      # the tip bar
        commit_admission=[scoped])          # intermediates do NOT gate the scopeless step

    tip_row = [c for c in result["commits"] if c["is_tip"]][0]
    mid_row = [c for c in result["commits"] if not c["is_tip"]][0]

    # the fixture must really be the composed case, or this proves something easier
    assert scopeless not in (result["ratchet"].get("steps_consulted") or []), (
        "fixture: the ratchet must NOT consult this step, or it is the thing doing the blocking")
    assert result["ratchet"].get("owed") == [], (
        "fixture: the ratchet must owe nothing, or the tip row is not what refuses")
    assert scopeless in tip_row["stale"], "fixture: the step must be STALE at the tip"
    assert mid_row["complete"] is True, (
        "intermediates are judged by the bar that applied when they were made, and that has "
        "not changed — a per-commit staleness scope is correct beneath the tip")

    # ⛔ THE CLAIM: bytes this push publishes are unjudged, so the push is refused.
    assert tip_row["complete"] is False, (
        "the tip forgave a STALE step over a path the PUSH PUBLISHES, because it priced the "
        "stale set against the tip commit's own diff instead of the range")
    assert result["allowed"] is False


def test_the_split_does_not_re_block_a_genuinely_untouched_path(ledger, tmp_path):
    """⚠ THE OTHER DIRECTION, AND WITHOUT IT THE FIX ABOVE IS INDISTINGUISHABLE FROM DELETING
    THE FORGIVENESS. Tim's 2026-09-18 ruling stands: a STALE row over a path the RANGE never
    touches is backlog, is reported, and does not block. Widening the tip's set from the commit
    to the range must not widen it to everything.
    """
    base, mid, tip = _three_commits(tmp_path)
    scoped, scopeless = "check_encoding", "check_prose"
    # a third file, present since `base` and touched by NOTHING in the range
    (tmp_path / "untouched.md").write_text("old", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add untouched"], cwd=tmp_path, check=True,
                   capture_output=True)
    newbase = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                             text=True).stdout.strip()
    later = _commit_files(tmp_path, {"doc.md": "d2"}, "touch doc.md only")

    records = [
        _range_rec(scoped, "doc.md", _blob_at(tmp_path, later, "doc.md"), later),
        # STALE on a path this range does not touch at all: judged at bytes that are not current
        _range_rec(scopeless, "untouched.md", "0" * 40, newbase),
    ]
    result = canpush_mod.check(
        records=records, config=ledger.config, repo=str(tmp_path),
        rev_range=f"{newbase}..{later}",
        admission=[scoped, scopeless], commit_admission=[scoped])

    tip_row = [c for c in result["commits"] if c["is_tip"]][0]
    assert scopeless in tip_row["stale"], "it is still STALE and still reported"
    assert tip_row["complete"] is True, (
        "a stale path the range never touches was re-blocked — the fix widened forgiveness's "
        "scope from the commit to the RANGE, not from the commit to EVERYTHING")
