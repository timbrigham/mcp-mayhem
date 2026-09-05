"""UNDECIDED indicts a SUBSET, exactly as FAIL does — and refusing that was my own hole.

⭐⭐ TIM, 2026-09-05, designing the copy-editor phase: *"so at one point in time we actually
have multiple adversaries running concurrently, and needing to come to a consensus… the copy
editor phase here might be a perfect place to run three and need two of the three or more to
agree"* — and then, on what a 2–1 split records: *"the undecided is a perfect use case here
when the three copy editors disagreeing"*.

⛔⛔ THE VOCABULARY EXISTED AND THE GUARD FORBADE USING IT. `UNDECIDED` has been fully wired
since the schema was written and appears in ZERO of 2,085 records. The moment there was finally
a real producer for it, my own `failing` guard — added days earlier to stop wide FAILs
condemning innocent bytes — refused `failing` on any verdict but FAIL. So a panel that split
2–1 over forty files could only record an UNDECIDED that blocked **all forty**, when it was
undecided about one line and perfectly decided about the other thirty-nine.

⚠⚠ THAT IS THE 2026-09-02 `check_checkers` DEFECT ARRIVING THROUGH THE DOOR BUILT TO STOP IT.
One dispute condemning every file examined beside it — the identical shape, reached by the
identical route (indictment and coverage forced to be the same list). The difference is that
the wide FAIL was MALFORMED and this would have been the only *representable* record, which is
strictly worse: nothing downstream could have flagged it, because it would have been correct.

⭐ THE ASYMMETRY IS THE SAFETY AND IT IS DELIBERATE. FAIL and UNDECIDED both BLOCK, so narrowing
either moves paths from blocked to clear and a reader can see which. PASS blocks nothing, so
`failing` there could only mean something the resolver does not implement — it stays refused,
and `outstanding` (graded by V18) remains the way a PASS carries findings.
"""

import pytest

from core import inventory as inventory_mod
from core import validate as validate_mod


STEP = "check_prose"


def _rec(sha, verdict, subjects, rid=None, revision=0, failing=None):
    rec = {"id": rid or f"{STEP}@{sha}#{revision}", "step": STEP, "verdict": verdict,
           "revision": revision, "reason": "two of three editors agreed; one dissented",
           "decided": {"how": "delegated", "who": "copy-editor-panel", "passes": 3,
                       "agreed": 2},
           "subjects": [{"path": p, "git_blob_id": b} for p, b in subjects.items()],
           "basis": {"kind": "tree", "value": sha}}
    if failing is not None:
        rec["failing"] = failing
    return rec


def _row(ledger, records, files):
    inv = inventory_mod.build(config=ledger.config, records=records, action="push",
                              files=files, ref="deadbeef")
    return next(r for r in inv["rows"] if r["step"] == STEP)


# -- the validator half ---------------------------------------------------------

def _structural_errors(record):
    return [e for e in validate_mod.structural(record) if "failing" in e]


def test_failing_is_accepted_on_undecided():
    """⭐ THE ENABLING CHANGE. A split panel must be able to say WHICH line it split over."""
    rec = _rec("abc", "UNDECIDED", {"good.md": "aaa", "disputed.md": "bbb"},
               failing=["disputed.md"])
    assert _structural_errors(rec) == [], (
        "a 2-1 panel cannot record a narrow dispute — the only legal record blocks every "
        "file it read")


def test_failing_is_still_refused_on_pass():
    """⛔ THE ASYMMETRY HOLDS. A PASS blocks nothing, so a `failing` list on one would be
    stored and silently ignored — the exact shape the guard was written to prevent. Widening
    to UNDECIDED must not widen to everything."""
    rec = _rec("abc", "PASS", {"good.md": "aaa"}, failing=["good.md"])
    errs = _structural_errors(rec)
    assert errs, "a `failing` list on a PASS would be inert, and inert is worse than refused"
    assert "outstanding" in errs[0], (
        "the refusal must name what a PASS uses INSTEAD — a refusal that does not name the "
        "alternative is how a workaround gets invented (§3)")


def test_an_empty_failing_is_refused_on_undecided_too():
    """⚠ THE VACUOUS-BLOCK HOLE, which widens with the field. An empty indictment resolves to
    a PASS at every path — an UNDECIDED that blocks nothing while claiming to block."""
    rec = _rec("abc", "UNDECIDED", {"good.md": "aaa"}, failing=[])
    assert _structural_errors(rec), "an empty `failing` must not be a quiet spelling of PASS"


def test_failing_naming_no_subject_is_refused_on_undecided_too():
    """⚠ The disguised exoneration. Entries that are not subjects are INERT for resolution,
    so an UNDECIDED naming only non-subjects reads as a PASS everywhere it covers."""
    rec = _rec("abc", "UNDECIDED", {"good.md": "aaa"}, failing=["some/(pseudo-path)"])
    assert _structural_errors(rec)


# -- the resolver half, which is the half that actually had to move -------------

def test_an_undecided_does_not_block_the_files_it_did_not_dispute(ledger):
    """⭐⭐ THE HEADLINE. Two files judged together, one disputed. The undisputed file must
    resolve CLEAN — otherwise the panel's narrow disagreement parks everything it read."""
    files = {"good.md": "aaa", "disputed.md": "bbb"}
    recs = [_rec("t1", "UNDECIDED", files, failing=["disputed.md"])]
    row = _row(ledger, recs, {"good.md": "aaa"})
    assert row["status"] == "SATISFIED", (
        f"`good.md` was never in dispute; got {row['status']}")


def test_the_dispute_still_blocks_the_file_it_names(ledger):
    """⛔ THE OTHER DIRECTION, and the one that makes the test above worth anything. Narrowing
    must not become a general escape from UNDECIDED."""
    files = {"good.md": "aaa", "disputed.md": "bbb"}
    recs = [_rec("t1", "UNDECIDED", files, failing=["disputed.md"])]
    row = _row(ledger, recs, {"disputed.md": "bbb"})
    assert row["status"] == "UNDECIDED", (
        f"the disputed bytes must still block; got {row['status']}")


def test_an_undecided_without_failing_still_blocks_every_subject(ledger):
    """⚠⚠ NO HISTORICAL RECORD IS WEAKENED BY THIS LANDING. Absent `failing` means all
    subjects are indicted — the pre-existing reading, preserved exactly. The stream is
    APPEND-ONLY, so a rule that silently narrowed old records would rewrite the past."""
    files = {"good.md": "aaa", "disputed.md": "bbb"}
    recs = [_rec("t1", "UNDECIDED", files)]
    row = _row(ledger, recs, {"good.md": "aaa"})
    assert row["status"] == "UNDECIDED", (
        "an UNDECIDED that names no subset indicts all of them, exactly as before")


def test_the_row_reports_which_verdict_was_narrowed(ledger):
    """⚠ A NARROWED FAIL AND A NARROWED UNDECIDED ARE DIFFERENT CLAIMS — "condemned
    elsewhere" versus "DISPUTED elsewhere". `_narrowed_from` carries the original verdict
    rather than a boolean so the distinction Tim added UNDECIDED to make survives the
    narrowing that clears the row."""
    files = {"good.md": "aaa", "disputed.md": "bbb"}
    for verdict in ("FAIL", "UNDECIDED"):
        recs = [_rec("t1", verdict, files, failing=["disputed.md"])]
        inv = inventory_mod.build(config=ledger.config, records=recs, action="push",
                                  files={"good.md": "aaa"}, ref="deadbeef")
        row = next(r for r in inv["rows"] if r["step"] == STEP)
        assert row["status"] == "SATISFIED"
        assert row.get("narrowed_from") == verdict, (
            f"a narrowed {verdict} must say so on the ROW, where a reader can see it; "
            f"got {row.get('narrowed_from')!r}")


# -- ⭐⭐ the one that catches the half-landing --------------------------------

def test_accepting_failing_without_reading_it_is_the_defect_not_the_fix(ledger):
    """⭐⭐⭐ THE FAILURE MODE THIS CHANGE COULD HAVE SHIPPED AS, and the reason the two
    halves landed in one commit.

    Widening the VALIDATOR alone — accepting `failing` on an UNDECIDED while `_severity_at`
    still narrowed only on FAIL — produces the shape that guard's own comment calls the worst
    available: **a field accepted, stored, and silently ignored.** The panel would emit a
    correct narrow record, the ledger would take it without complaint, and every file would
    block anyway. Nothing would report a problem.

    ⚠ Refused-but-honest beats accepted-but-inert, so this asserts the pair moved together:
    a record the validator ACCEPTS must be one the resolver ACTS on. It fails loudly if a
    later edit reverts `_severity_at` while leaving the guard widened.
    """
    rec = _rec("t1", "UNDECIDED", {"good.md": "aaa", "disputed.md": "bbb"},
               failing=["disputed.md"])
    accepted = not _structural_errors(rec)
    row = _row(ledger, [rec], {"good.md": "aaa"})
    acted_on = row["status"] == "SATISFIED"
    assert accepted == acted_on, (
        f"validator accepts={accepted} but resolver narrows={acted_on} — the field is "
        f"{'inert' if accepted else 'read but unrepresentable'}. These must move together: "
        f"a `failing` list that validates and then does nothing is indistinguishable from a "
        f"working narrowing to everyone except the person debugging a parked push.")


# -- the reader's half: a narrowing nobody can see is a narrowing nobody can audit

def test_a_narrowed_row_says_so_in_the_rendered_inventory(ledger):
    """⭐⭐ THE FIELD IS ONLY WORTH ADDING IF A HUMAN SEES IT. A narrowed row is SATISFIED by
    definition, so it appears ONLY on an otherwise-green inventory — the exact case where a
    reader stops reading. `render_inventory` therefore prints it BEFORE the `complete` early
    return, alongside NARROWED COVERAGE and EXAMINED BUT UNSCOPED, which sit there for the
    same reason.

    ⚠ THE DISTINCTION BEING PROTECTED: "a checker looked at this and was happy" versus "a
    checker BLOCKED at this step, and none of the paths it condemned are in this scope". Both
    render as SATISFIED. Only the second one has a live finding attached to it somewhere."""
    from core import inventory as inv_mod
    from core import render as render_mod

    files = {"good.md": "aaa", "disputed.md": "bbb"}
    inv = inv_mod.build(config=ledger.config,
                        records=[_rec("t1", "UNDECIDED", files, failing=["disputed.md"])],
                        action="push", files={"good.md": "aaa"}, ref="deadbeef",
                        admission=["check_prose"])
    assert inv["complete"] is True, "the premise: this inventory is GREEN"
    text = render_mod.render_inventory(inv)
    assert "NARROWED INDICTMENT" in text, (
        "a green inventory that is green only because of a narrowing must say so")
    assert "from UNDECIDED" in text, "and must name WHICH verdict was narrowed"


def test_a_genuinely_clean_row_raises_no_narrowing_warning(ledger):
    """⚠ …and it must not cry wolf. An alarm that fires on every green inventory trains the
    reader to skip it, which is the failure this row exists to prevent."""
    from core import inventory as inv_mod
    from core import render as render_mod

    rec = _rec("t1", "PASS", {"good.md": "aaa"})
    inv = inv_mod.build(config=ledger.config, records=[rec], action="push",
                        files={"good.md": "aaa"}, ref="deadbeef",
                        admission=["check_prose"])
    assert "NARROWED INDICTMENT" not in render_mod.render_inventory(inv)


# -- ⭐ SH-3: the same argument, at the sibling level ---------------------------

def test_the_push_path_names_a_narrowing_too():
    """⭐⭐ FOUND BY ASKING ZeroParadox's `SH-3` QUESTION OF MY OWN FIX — *a fix applied at one
    level and not its sibling*. `render_inventory` had just learned to print NARROWED
    INDICTMENT; `canpush.render`, the surface an operator actually reads before publishing,
    was still silent.

    ⚠ THE PRECEDENT WAS ALREADY SITTING TWO LINES ABOVE IT. `NARROWED COVERAGE` lives on both
    surfaces, and its comment says why: *"`inventory` names it; without this the push path —
    the one that matters — would still be silent."* The identical argument, three weeks
    earlier, about the other kind of narrowing. I wrote the new one into `inventory` only and
    would not have looked without the question.

    ⚠ Rendered from a synthetic result on purpose: what is under test is the SURFACE, and
    driving it through a real range would make the assertion depend on the resolver as well —
    the two are already covered separately above."""
    from core import canpush as canpush_mod

    text = canpush_mod.render({
        "ok": True, "allowed": True, "blocking_count": 0, "commits_in_range": 2,
        "range": "aaa..bbb",
        "commits": [
            {"complete": True, "narrowed": ["check_prose (from UNDECIDED)"]},
            {"complete": True,
             "narrowed": ["check_prose (from UNDECIDED)", "check_math (from FAIL)"]}],
    })
    assert "NARROWED INDICTMENT" in text, (
        "an ALLOWED push whose keys are green only because the covering records condemn "
        "paths outside this scope must say so — the same standard `forgiven` is held to")
    assert "check_math (from FAIL)" in text
    # ⚠ deduped across commits: the same narrowed step at ten commits is one fact, and a
    # count of ten would misreport the size of what a reader has to go look at.
    assert text.count("check_prose (from UNDECIDED)") == 1


def test_a_clean_push_raises_no_narrowing_line():
    """⚠ An alarm on every green push trains the reader to skip it — the failure this line
    exists to prevent, arriving through the line itself."""
    from core import canpush as canpush_mod

    text = canpush_mod.render({
        "ok": True, "allowed": True, "blocking_count": 0, "commits_in_range": 1,
        "range": "aaa..bbb", "commits": [{"complete": True, "narrowed": []}],
    })
    assert "NARROWED INDICTMENT" not in text
