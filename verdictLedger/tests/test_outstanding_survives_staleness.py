"""`outstanding` must not evaporate when a row stops being SATISFIED — LED-7.

⭐⭐ RAISED BY ZeroParadox 2026-08-30 and rated above its own checker work, correctly. V18 lets a
PASS carry `outstanding` findings: reviewed, ordinary findings left, loop cap reached, proceed.
`inventory` computed them as `... if status == "SATISFIED" else []`, so the moment a later commit
moved ONE subject the row went STALE and seven recorded findings rendered as `outstanding: 0`.

⚠⚠ IT MATTERS MORE NOW THAN WHEN V18 SHIPPED. Under R-LOOPCAP's ordinary cap the review gates
record PASS-with-`outstanding` rather than FAIL, so `outstanding` is the PRIMARY carrier of every
finding not being fixed before a push. Zeroing it on staleness converts "reviewed, not certified
clean" into "reviewed, findings lost" — and silently, because a zeroed count and a real zero are
the same bytes. That is this project's recurring defect: an absence rendering as a clean result.
"""

import pytest

from conftest import good
from core import inventory as inventory_mod


def _rows(ledger, records, files, admission, action="commit"):
    inv = inventory_mod.build(config=ledger.config, records=records, action=action,
                              files=files, admission=admission)
    return {r["step"]: r for r in inv["rows"]}, inv


def test_a_satisfied_row_reports_its_findings(ledger):
    """⚠ The baseline V18 case: a PASS carrying findings says so."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "a real finding"}]))
    rows, _ = _rows(ledger, ledger.store.records(), {"x.lean": "b" * 40}, ["check_invariants"])
    row = rows["check_invariants"]
    assert row["status"] == "SATISFIED"
    assert row["outstanding"] == 1
    assert row["outstanding_stale"] is False
    assert row["outstanding_notes"] == ["a real finding"]


def test_findings_survive_the_row_going_stale(ledger):
    """⭐⭐ THE HEADLINE. One subject moves, the row goes STALE — and the findings recorded
    against it are still facts about the corpus. Before this they returned 0."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "a real finding"},
                                    {"severity": "ordinary", "note": "another"}]))
    rows, _ = _rows(ledger, ledger.store.records(), {"x.lean": "c" * 40}, ["check_invariants"])
    row = rows["check_invariants"]
    assert row["status"] == "STALE"
    assert row["outstanding"] == 2, "findings evaporated when the row went stale — LED-7"
    assert row["outstanding_notes"] == ["a real finding", "another"]


def test_stale_findings_are_marked_as_stale(ledger):
    """⚠⚠ A COUNT WITHOUT ITS CURRENCY IS THE DEFECT ONE LAYER OUT. Findings carried by a
    stale record are about bytes that have moved. Reporting them without saying so would let a
    reader act on findings that may already be fixed — so the count travels with the flag."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "a real finding"}]))
    rows, _ = _rows(ledger, ledger.store.records(), {"x.lean": "c" * 40}, ["check_invariants"])
    assert rows["check_invariants"]["outstanding_stale"] is True


def test_a_row_with_no_findings_still_reports_zero(ledger):
    """⚠ The complement, so the fix cannot invent findings. A genuine zero stays zero and is
    NOT marked stale — otherwise every stale row would look like it were hiding something."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    rows, _ = _rows(ledger, ledger.store.records(), {"x.lean": "c" * 40}, ["check_invariants"])
    row = rows["check_invariants"]
    assert row["status"] == "STALE"
    assert row["outstanding"] == 0
    assert row["outstanding_stale"] is False


def test_the_inventory_total_counts_them_too(ledger):
    """⚠ The per-row fix is useless if the aggregate everyone reads still says zero — the
    surface `progress()` and the render line take their number from."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "n1"},
                                    {"severity": "ordinary", "note": "n2"}]))
    _, inv = _rows(ledger, ledger.store.records(), {"x.lean": "c" * 40}, ["check_invariants"])
    assert inv["outstanding"] == 2


# -- ⚠⚠ several records can cover one step at once ----------------------------

def test_findings_are_the_union_across_every_covering_record(ledger):
    """⭐⭐ MEASURED 2026-08-30. A step can have SEVERAL records covering it. `outstanding`
    read from `min(covered_recs, key=severity)` — and `covered_recs` holds one entry PER
    COVERED PATH, so with every candidate PASS the key ties and `min` returns whichever record
    covers the alphabetically first path.

    Live result: adversary resolved to an older record carrying 11 findings while the round the
    caller was actually pushing, carrying 7, contributed nothing. The COUNT was right and the
    FINDINGS were the wrong ones — worse than a zero, because it looks answered."""
    ledger.append(good(step="check_invariants",
                       basis={"kind": "tree", "value": "1" * 40, "resolved_from": "explicit"},
                       subjects=[{"git_blob_id": "a" * 40, "path": "a.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "from the older run"}]))
    ledger.append(good(step="check_invariants",
                       basis={"kind": "tree", "value": "2" * 40, "resolved_from": "explicit"},
                       subjects=[{"git_blob_id": "d" * 40, "path": "d.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "from the newer run"}]))
    rows, _ = _rows(ledger, ledger.store.records(),
                    {"a.lean": "a" * 40, "d.lean": "d" * 40}, ["check_invariants"])
    notes = rows["check_invariants"]["outstanding_notes"]

    assert "from the older run" in notes
    assert "from the newer run" in notes, \
        "only one covering record contributed — selection by path order, the 2026-08-30 bug"
    assert rows["check_invariants"]["outstanding"] == 2


def test_the_contributing_records_are_named(ledger):
    """⚠ A count without provenance cannot be told from a partial one: a reader seeing 11 has
    no way to know it is not 11 of 27. Same argument that put `outstanding_stale` beside it."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "a" * 40, "path": "a.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "n1"}]))
    rows, _ = _rows(ledger, ledger.store.records(), {"a.lean": "a" * 40}, ["check_invariants"])
    row = rows["check_invariants"]
    assert row["outstanding_from"], "no provenance for the count"
    assert row["outstanding_from"] == [row["record_id"]] or len(row["outstanding_from"]) >= 1


def test_a_finding_restated_in_a_later_round_counts_once(ledger):
    """⚠ Deduped by note. The same finding carried forward by a second record is ONE finding —
    an inflated count misleads exactly as much as a truncated one, in the other direction."""
    ledger.append(good(step="check_invariants",
                       basis={"kind": "tree", "value": "3" * 40, "resolved_from": "explicit"},
                       subjects=[{"git_blob_id": "a" * 40, "path": "a.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "the same finding"}]))
    ledger.append(good(step="check_invariants",
                       basis={"kind": "tree", "value": "4" * 40, "resolved_from": "explicit"},
                       subjects=[{"git_blob_id": "d" * 40, "path": "d.lean"}],
                       outstanding=[{"severity": "ordinary", "note": "the same finding"}]))
    rows, _ = _rows(ledger, ledger.store.records(),
                    {"a.lean": "a" * 40, "d.lean": "d" * 40}, ["check_invariants"])
    assert rows["check_invariants"]["outstanding"] == 1
