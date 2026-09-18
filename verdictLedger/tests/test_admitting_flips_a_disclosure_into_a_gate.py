"""ADMITTING A STEP DOES NOT TOUCH ITS ROW. It changes what the same row DOES.

⛔⛔ THE PROCESS THIS PINS, and it is the one Tim asked to be tested before it is run. Widening
`prior_art`'s scope on 2026-09-17 revealed a STALE row — `LEAN_CUSTOM_REGISTRY.md`, examined by a
2026-09-15 round at blob 97b7e7e5, moved since to d0cd4047. While `prior_art` is NOT in the
admission set that row is a DISCLOSURE: it prints and nothing refuses. Mirror the registry into
admission with the row in that state and the SAME row refuses the push.

⚠ Nothing about the verdict, the subjects or the bytes changes at that moment. The gating flag
does, and the flag is what decides whether a true sentence is advice or a refusal — `R-ZERONULL`
at the admission layer. So the order is: name the stale path, clear it, THEN mirror. Mirroring
first converts a disclosure nobody was acting on into a refusal nobody predicted.

⭐ AND THE WIDENING DID NOT CREATE THE OBLIGATION — it revealed one the narrow glob had hidden.
The 2026-09-15 round examined 105 subjects, most of them outside the step's declared scope at the
time. The practice was wider than the glob; the glob catching up is what made the row visible.
"""

import subprocess

from core import canpush as canpush_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_prose"          # stands in for any admitted review step
OTHER = "check_encoding"      # the step under test: admitted or not, per case
PATH = "doc.md"


def _stale_world(ledger, tmp_path):
    """Two commits. OTHER examined PATH at the OLD bytes only, so its row is STALE at the tip."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    b_old, b_tip = _blob(tmp_path, old, PATH), _blob(tmp_path, tip, PATH)
    records = [_rec(STEP, PATH, b_tip, tip),          # the admitted step is clean at the tip
               _rec(OTHER, PATH, b_old, old)]         # the candidate step is one blob behind
    # ⚠ The range is old..tip, ONE commit. A wider range would also carry the intermediate,
    # which is short on the stand-in step and would refuse for a reason this file is not about.
    return old, tip, records, b_old, b_tip


def _check(ledger, tmp_path, base, tip, records, admission):
    return canpush_mod.check(records=list(records), config=ledger.config, repo=str(tmp_path),
                             rev_range=f"{base}..{tip}", admission=list(admission),
                             commit_admission=list(admission))


def test_unadmitted_the_stale_row_is_only_a_disclosure(ledger, tmp_path):
    """⭐ BEFORE THE MIRROR. The row is stale and the push is ALLOWED, because a step nobody
    admitted gates nothing. This is the state a reader sees as 'fine'."""
    base, tip, records, _, _ = _stale_world(ledger, tmp_path)

    result = _check(ledger, tmp_path, base, tip, records, [STEP])

    assert result["allowed"] is True
    assert OTHER not in result["stale"], "an unadmitted step must not appear as blocking work"
    assert OTHER in (result["not_gating"] or []), "and it must still be VISIBLE as registered"


def test_admitting_the_same_step_refuses_the_same_push(ledger, tmp_path):
    """⛔⛔ THE HEADLINE. Identical records, identical bytes, identical range — only the admission
    list differs, and the push flips from allowed to refused."""
    base, tip, records, _, _ = _stale_world(ledger, tmp_path)

    before = _check(ledger, tmp_path, base, tip, records, [STEP])
    after = _check(ledger, tmp_path, base, tip, records, [STEP, OTHER])

    assert before["allowed"] is True and after["allowed"] is False
    assert OTHER in after["stale"], "the newly admitted step must name itself as the blocker"
    tip_row = [c for c in after["commits"] if c["is_tip"]][0]
    assert OTHER in tip_row["stale"]


def test_clearing_first_then_admitting_does_not_refuse(ledger, tmp_path):
    """⭐ THE SANCTIONED ORDER. Record the step at the CURRENT bytes first; then admitting it
    changes nothing about whether the push may proceed. This is what 'clear, then mirror' buys."""
    base, tip, records, _, b_tip = _stale_world(ledger, tmp_path)
    cleared = records + [_rec(OTHER, PATH, b_tip, tip)]

    result = _check(ledger, tmp_path, base, tip, cleared, [STEP, OTHER])

    assert result["allowed"] is True, "clearing first must make the mirror a no-op for the gate"
    assert not result["stale"]


def test_a_never_examined_path_reads_MISSING_not_STALE_when_admitted(ledger, tmp_path):
    """⚠ THE DISTINCTION THAT NAMED THE REAL PATH. 'Examined before, bytes moved' (STALE) and
    'never examined' (MISSING) are different states with different remedies, and the widening
    produced one of each — 1 stale, 221 never examined. A process that cannot tell them apart
    would send a review round at the wrong file."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]   # OTHER has never run at all

    result = _check(ledger, tmp_path, old, tip, records, [STEP, OTHER])

    assert result["allowed"] is False
    assert OTHER in result["missing"] and OTHER not in result["stale"]
