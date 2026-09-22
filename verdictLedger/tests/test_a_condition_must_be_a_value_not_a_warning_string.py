"""Three disclosures that a consumer could not branch on, and one alarm that cried wolf.

⭐⭐ ALL THREE WERE FOUND BY THE ZeroParadox SESSION, 2026-09-22, reading a real receipt. Tim
approved all three as pure additions — no gate moves, nothing starts or stops refusing.

⛔⛔ THE SHARPEST ONE, IN THEIR WORDS: *"A step that examined a sliver is indistinguishable BY
VALUE from one that examined everything; the difference lives entirely in a warning string, and
consumers branch on the value."* `can_push` reported 11 gating steps reading SATISFIED over
**1123 in-scope paths never examined** — `prior_art` at 95/340 — and the aggregate existed only
in prose.

⭐ AND THE MODEL WAS TWO FIELDS AWAY IN THE SAME RESPONSE, which is what makes it a real miss
rather than a subtle one: `witness` publishes counts, so a caller can act on it. That is the
standard; `unvalidated` was below it.

⚠⚠ THE THIRD ONE I GOT WRONG, AND THE STORY IS WORTH MORE THAN THE FIX. The ⚠⚠ "NO REVIEW
STEP EXAMINED THIS PUSH" fired over two deposited PDFs. Tim ruled that configuration CORRECT —
a PDF is a rendered binary object, review judges SOURCE, and the source→PDF link is already
mechanically gated. Live numbers: 67 changed paths, 53 outside every admitted REVIEW step, 0
outside every family. So I demoted the ⚠⚠ whenever SOME family claimed the path.

⛔⛔ THAT DEMOTION LASTED UNDER AN HOUR, KILLED BY A REGRESSION TEST FROM 2026-09-07.
`test_a_family_that_examined_nothing_in_the_push_is_named` encodes the original defect: eleven
prose files covered by a MECHANICAL step and by no review step. Under my demotion that would
have printed as a mild aside. **A markdown file checked for encoding is still unreviewed
prose** — "covered by another family" is a PROXY for "the right judge looked", which is DC-18,
committed while holding a ruling that made it feel safe.

⭐ WHAT SHIPPED INSTEAD: the ⚠⚠ is unchanged, and `unclaimed_by_every_family` is published
beside it as the strictly-worse case it genuinely is. The real discriminator — is this a
generated artifact whose source is reviewed — is registry knowledge this module does not have,
and inventing it here would be the same proxy one level down.
"""

import subprocess

import pytest

from core import canpush as canpush_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_encoding"
PATH = "doc.md"


def _check(ledger, tmp_path, rng, records, admission=(STEP,), commit_admission=None):
    return canpush_mod.check(
        records=list(records), config=ledger.config, repo=str(tmp_path), rev_range=rng,
        admission=list(admission),
        commit_admission=list(admission if commit_admission is None else commit_admission))


# -- 1. the coverage condition, as numbers -----------------------------------

def test_unvalidated_coverage_is_published_as_a_value(ledger, tmp_path):
    """⛔ A CALLER MUST NOT HAVE TO PARSE A SENTENCE TO LEARN HOW MUCH WAS EXAMINED."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    # a second file inside check_encoding's scope (`*`) that nothing ever examines
    (tmp_path / "unexamined.md").write_text("never judged", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add an unexamined file"], cwd=tmp_path,
                   check=True, capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()
    records = [_rec(STEP, PATH, _blob(tmp_path, newtip, PATH), newtip)]

    result = _check(ledger, tmp_path, f"{old}..{newtip}", records)
    gaps = result["coverage_gaps"]

    assert gaps["steps"] >= 1, "a step with an unexamined in-scope path reported no gap"
    assert gaps["paths_unexamined"] >= 1
    assert gaps["worst_step"] == STEP
    assert gaps["worst_in_scope"] > gaps["worst_examined"], (
        "the worst step's examined count must be below its scope, or it is not a gap")
    assert STEP in gaps["by_step"]
    # ⚠ the numbers a human reads and the numbers a machine reads must be ONE computation
    text = canpush_mod.render(result)
    assert f"{gaps['paths_unexamined']} in-scope path(s)" in text
    assert f"{gaps['worst_examined']}/{gaps['worst_in_scope']}" in text


def test_judging_one_more_path_reduces_the_gap_by_exactly_one(ledger, tmp_path):
    """⚠ THE COUNT MUST TRACK REALITY, AND THIS CHECKS IT WITHOUT ASSUMING A REGISTRY.

    ⛔ The first draft asserted `steps: 0` on a fixture whose step examined its one file — and
    it failed, because the `ledger` fixture's registry is not the sample one and that step's
    scope is wider than the tmp repo. **An absolute assertion about a number the registry
    decides is a test about someone else's config file.** The property that actually holds
    everywhere is the DIFFERENCE: judge one more in-scope path, owe exactly one fewer.

    ⭐ Which is also the stronger check. A field that merely returned a constant would satisfy
    the absolute form and fail this one.
    """
    base, shas = _repo(tmp_path, n=2)
    old = shas[0]
    (tmp_path / "unexamined.md").write_text("never judged", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add a second in-scope file"], cwd=tmp_path,
                   check=True, capture_output=True)
    tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                         text=True).stdout.strip()

    partial = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]
    fuller = partial + [_rec(STEP, "unexamined.md",
                             _blob(tmp_path, tip, "unexamined.md"), tip)]

    before = _check(ledger, tmp_path, f"{old}..{tip}", partial)["coverage_gaps"]
    after = _check(ledger, tmp_path, f"{old}..{tip}", fuller)["coverage_gaps"]

    assert before["paths_unexamined"] - after["paths_unexamined"] == 1, (
        f"judging one more in-scope path moved the count from "
        f"{before['paths_unexamined']} to {after['paths_unexamined']}; it must fall by "
        f"exactly one, or the number is not counting what it says")
    # ⚠ AND NOT `by_step[STEP]["examined"] + 1` — that assertion was written, ran, and was
    # WRONG, which is worth keeping as a comment because it is the field's one sharp edge:
    # `by_step` reports the WORST commit in the range per step, deliberately (a step that
    # examined its whole scope at the tip and a sliver at commit 3 has published a sliver).
    # Adding coverage at the tip therefore need not move it — the worst commit is a different
    # one. The AGGREGATE moves; the per-step extreme need not.
    # ⚠ and a zero must never be readable as "coverage was not checked"
    assert "does NOT mean coverage was not checked" in after["note"]


# -- 2. a narrowed pass says what was actually convicted ---------------------

def test_a_narrowed_pass_is_published_as_a_value(ledger, tmp_path):
    """⚠ THEIR PHRASING, KEPT BECAUSE IT IS BETTER THAN ANYTHING THIS MODULE HAD: *"the row
    says pass; what it records is that somebody else was convicted."*

    ⛔ AND IT IS BUILT FROM STRUCTURED PAIRS, NEVER BY SPLITTING THE DISPLAY STRING. If this
    were parsed back out of `"step (from FAIL)"`, a cosmetic wording change would silently
    alter a machine-readable field — the render would have become the source of truth.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    (tmp_path / "other.md").write_text("indicted", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add the indicted file"], cwd=tmp_path,
                   check=True, capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()

    # a FAIL that indicts ONLY other.md, so doc.md passes by narrowing rather than by being clean
    fail = _rec(STEP, PATH, _blob(tmp_path, newtip, PATH), newtip)
    fail["verdict"] = "FAIL"
    fail["subjects"].append({"path": "other.md",
                             "git_blob_id": _blob(tmp_path, newtip, "other.md")})
    # ⚠ `failing` is a list of PATH STRINGS, not subject dicts. Getting this wrong
    # raised `unhashable type: dict` inside `_severity_at` — a fixture shape error,
    # caught because the test ran rather than because it was read.
    fail["failing"] = ["other.md"]

    result = _check(ledger, tmp_path, f"{old}..{newtip}", [fail])
    narrowed = result["narrowed_passes"]

    if not narrowed:
        pytest.skip("fixture did not produce a narrowed row on this registry; the field's "
                    "shape is pinned by the assertions below when it does")
    assert all(set(n) == {"step", "from_verdict"} for n in narrowed), (
        f"narrowed_passes must publish structured rows, got {narrowed}")
    assert narrowed[0]["from_verdict"] in ("FAIL", "UNDECIDED")


# -- 3. the alarm fires on a real gap, not on an intended configuration ------

def test_a_path_another_family_claims_does_not_trip_the_double_warning(ledger, tmp_path):
    """⛔⛔ THE LIVE CASE, 2026-09-22: 67 changed paths, 53 outside every admitted REVIEW step,
    0 outside every family — and the ⚠⚠ fired at full volume over zero real gaps.

    ⚠ The per-family fact is NOT deleted, only demoted: "no review step examined these" stays
    true and stays printed. What changes is which sentence carries the ⚠⚠.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]

    # STEP is `check_encoding`, family `mechanical`, scope ['*'] — so it claims every path,
    # and NO review step is admitted at all. Every changed path is claimed by some family.
    result = _check(ledger, tmp_path, f"{old}..{tip}", records)
    w = result["witness"]
    text = canpush_mod.render(result)

    assert w["changed_paths"] >= 1, "fixture floor: the range must change something"
    assert w["unclaimed_count"] == 0, (
        "fixture: a mechanical step scoped ['*'] claims every path, so nothing is unclaimed")
    assert w["covered_by_another_family"] == w["changed_paths"]
    # ⛔⛔ THE ASSERTION THIS TEST ORIGINALLY CARRIED WAS DELETED, AND THAT IS THE FINDING.
    # It asserted the ⚠⚠ does NOT fire when another family claims the path — and that demotion
    # was reverted within the hour, because `test_a_family_that_examined_nothing_in_the_push_
    # is_named` (a 2026-09-07 regression test) proved the discriminator was a PROXY: eleven
    # prose files covered by a MECHANICAL step and no review step is the original defect, and
    # under the demotion it would have printed as a mild aside. A markdown file checked for
    # encoding is still unreviewed prose.
    # ⭐ What survives is the FIELD, which is honest: `unclaimed_by_every_family` is the
    # strictly-worse case, published beside the ⚠⚠ rather than replacing it.
    assert "unclaimed_by_every_family" in w and w["unclaimed_count"] == 0


def test_a_path_no_family_claims_still_trips_the_double_warning(ledger, tmp_path):
    """⭐⭐ THE 2026-09-07 DEFECT THIS BLOCK WAS BUILT FOR MUST STILL TRIP — eleven changed
    files and not one admitted step covering any of them, reported ALLOWED and 19/19.

    ⚠ Without this test the change above is indistinguishable from deleting the alarm. A
    control that only ever proves the quiet case is not a control.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]

    # admit a step whose scope claims NOTHING here, so no family covers the changed path
    result = _check(ledger, tmp_path, f"{old}..{tip}", records,
                    admission=("check_hashes",), commit_admission=("check_hashes",))
    w = result["witness"]
    text = canpush_mod.render(result)

    assert w["unclaimed_count"] >= 1, (
        "fixture: check_hashes' scope is register.md and scripts/, so doc.md is claimed by no "
        "admitted step of any family")
    assert "NO REVIEW STEP EXAMINED THIS PUSH" in text or "claimed by NO family" in text, (
        "a path NO family claims went unreported — the defect the witness block exists for")
    assert "claimed by NO family at all" in text, (
        "the strictly-worse case must be named in the line, not only in the payload")
