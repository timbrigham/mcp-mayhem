"""A verdict recorded against DIFFERENT BYTES does not describe these bytes.

⚠⚠ THIS FILE EXISTS BECAUSE OF A MEASURED FAILURE (2026-08-23). One probe `build`
FAIL — recorded against a throwaway tree, on a README sha of literal "bbbb…" —
reported ALL EIGHT audited commits as NOT_APPROVED, "landed over a non-passing
verdict". None of those commits had ever been examined by anything.

Two defects, one root, and they compounded:

  * `inventory` checked the FAIL verdict BEFORE the staleness check, so a PASS
    against moved content was correctly demoted to STALE while a FAIL was not.
    A single stale FAIL condemned every commit forever, clearable only by a PASS
    on the exact sha.
  * `crossref` counted STALE as "examined", so a commit nothing had ever looked at
    reported `examined_by=3` and escaped the NOT_RUN finding — the single finding
    the audit exists to produce.

The compound effect is worse than either: the audit cried wolf on every commit
(training a reader to ignore it) while simultaneously being unable to report the
one thing it is for. Both directions of wrong, at once.
"""

import pytest

from core import crossref as crossref_mod
from core import inventory as inventory_mod


# ⚠ These use `check_prose`, not `build`. `build` is narrowed to actions:["tag"]
# in the registry (stub-first commits sorry-stubbed files on purpose), so at `push`
# every build row resolves NOT_APPLICABLE -- a test written against it would be
# exercising the narrowing while claiming to exercise staleness.
def _rec(step, sha, verdict, rid=None):
    return {"id": rid or f"{step}@{sha}#0", "step": step, "verdict": verdict,
            "revision": 0, "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "README.md", "sha256": sha}],
            "basis": {"kind": "tree", "value": sha}}


def _build(ledger, records, files, admission=None):
    return inventory_mod.build(config=ledger.config, records=records, action="push",
                               files=files, ref="deadbeef", admission=admission)


# -- ⭐ a FAIL against other bytes is STALE, not FAIL --------------------------

def test_a_fail_against_different_bytes_demotes_to_stale(ledger):
    """⭐ THE HEADLINE REGRESSION. `check_prose` failed on sha 'old'; we are asking about
    sha 'new'. The honest status is "never run on this", not "this failed"."""
    inv = _build(ledger, [_rec("check_prose", "old", "FAIL")], {"README.md": "new"})
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["status"] == "STALE"
    assert row["status"] != "FAIL"


def test_the_demoted_row_still_names_the_failure_it_saw(ledger):
    """⚠ Demoting must not DISCARD the signal. "there was a recent FAIL, against
    other content" is worth knowing; it is just not a verdict on these bytes."""
    inv = _build(ledger, [_rec("check_prose", "old", "FAIL")], {"README.md": "new"})
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert "against different bytes" in row["why"]
    assert "check_prose@old#0" in row["why"]


def test_a_fail_against_these_bytes_is_still_a_fail(ledger):
    """⚠ THE CONTROL THAT KEEPS THE FIX FROM BEING A HOLE. The demotion applies only
    when the record examined something else."""
    inv = _build(ledger, [_rec("check_prose", "same", "FAIL")], {"README.md": "same"})
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["status"] == "FAIL"


def test_an_undecided_against_other_bytes_also_demotes(ledger):
    inv = _build(ledger, [_rec("check_prose", "old", "UNDECIDED")], {"README.md": "new"})
    assert next(r for r in inv["rows"] if r["step"] == "check_prose")["status"] == "STALE"


def test_demoting_weakens_no_gate(ledger):
    """⭐ THE LOAD-BEARING PROPERTY. `complete` requires stale == 0 as well as
    failed == 0, so the action is refused either way. This fix changes only what the
    reader is TOLD — never whether the push is allowed."""
    inv = _build(ledger, [_rec("check_prose", "old", "FAIL")],
                 {"README.md": "new"}, admission=["check_prose"])
    assert inv["complete"] is False


def test_a_covering_record_wins_over_a_stale_one(ledger):
    """⚠ A SECOND, SUBTLER DEFECT: one `record` served both covered and stale hits,
    so whichever path was iterated first supplied the verdict. A stale FAIL could
    speak for a step that had also been properly examined."""
    files = {"README.md": "new", "GUIDE.md": "new2"}
    records = [
        {"id": "check_prose@old#0", "step": "check_prose", "verdict": "FAIL", "revision": 0,
         "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
         "subjects": [{"path": "README.md", "sha256": "old"}],
         "basis": {"kind": "tree", "value": "old"}},
        {"id": "check_prose@new2#0", "step": "check_prose", "verdict": "PASS", "revision": 0,
         "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
         "subjects": [{"path": "GUIDE.md", "sha256": "new2"}],
         "basis": {"kind": "tree", "value": "new2"}},
    ]
    row = next(r for r in _build(ledger, records, files)["rows"] if r["step"] == "check_prose")
    assert row["status"] == "STALE"          # partly examined, not FAILED
    assert row["record_id"] == "check_prose@new2#0"   # the COVERING record speaks


# -- ⭐ STALE is not "examined" ------------------------------------------------

def test_stale_does_not_count_as_examined(ledger):
    """⭐ The bypass detector must not report coverage it does not have. A commit
    whose every row is STALE was examined by NOTHING, and NOT_RUN is the finding."""
    inv = _build(ledger, [_rec("check_prose", "old", "PASS")], {"README.md": "new"})
    examined = [r for r in inv["rows"]
                if r["status"] in ("SATISFIED", "FAIL", "UNDECIDED")]
    assert examined == []


def test_the_crossref_examined_filter_excludes_stale():
    """Pins the filter itself: the constant lives in crossref and a well-meaning
    edit re-adding STALE would silently restore the defect."""
    import inspect
    src = inspect.getsource(crossref_mod.check)
    assert '("SATISFIED", "FAIL", "UNDECIDED")' in src
    assert '("SATISFIED", "STALE", "FAIL", "UNDECIDED")' not in src
