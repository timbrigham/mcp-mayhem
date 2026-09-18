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

import pytest

from conftest import good
from core import inventory as inventory_mod

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
