"""`coverage_gap` decides "passing" with the inventory's record and the inventory's rule.

⛔⛔ REPORTED BY THE CONSUMER 2026-11-22 (their ticket `tooling-union-fail-hides-passes`).
`coverage_gap(step='adversary')` read 165 of 424 missing. 145 of those were subjects of ONE union
FAIL: 258 subjects, `failing` = 40, run `gate-adversary-sweep-2026-11-13-union`. None of the 145
was in `failing`, none had moved, and no other record covered them. LED-10's remedy says a FAIL
"is ordinary passing coverage for its other subjects", and `build` has honoured that since
2026-09-02. This reader collected `verdict == "PASS"` records only, so it never did.

Measured here at the consumer's HEAD the same day: adversary 20 missing against the inventory
row's 422/424, copy_editor 71 against 147/149. Both gaps fell to exactly 2.

⚠ The fix also makes the reader take the DECIDING record at each content key, the same one `build`
takes. A PASS superseded by a later FAIL at the same bytes used to count as done here while the
gate read FAIL. That tightened nothing at that HEAD over 22 admitted steps. It is pinned anyway,
because it is the fail-open direction.
"""

from core import inventory as inventory_mod

STEP = "check_prose"


def _rec(sha, verdict, subjects, revision=0, failing=None):
    rec = {"id": f"{STEP}@{sha}#{revision}", "step": STEP, "verdict": verdict,
           "revision": revision, "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
           "subjects": [{"path": p, "git_blob_id": b} for p, b in subjects.items()],
           "basis": {"kind": "tree", "value": sha}}
    if failing is not None:
        rec["failing"] = failing
    return rec


def _gap(ledger, records, files):
    out = inventory_mod.coverage_gap(config=ledger.config, records=records, action="push",
                                     files=files, admission=[STEP], limit=1000)
    return next(s for s in out["steps"] if s["step"] == STEP)


def _row(ledger, records, files):
    inv = inventory_mod.build(config=ledger.config, records=records, action="push",
                              files=files, ref="deadbeef")
    return next(r for r in inv["rows"] if r["step"] == STEP)


FILES = {"docs/good.md": "aaa", "docs/bad.md": "bbb"}


def test_a_narrowed_fail_covers_the_subjects_it_does_not_name(ledger):
    """⭐⭐ THE REPORT, IN MINIATURE. One FAIL examined both files and indicts only `bad.md`."""
    gap = _gap(ledger, [_rec("s1", "FAIL", FILES, failing=["docs/bad.md"])], FILES)
    assert gap["applies_to"] == 2, "fixture must put both paths in scope"
    assert gap["paths"] == ["docs/bad.md"], (
        f"an un-indicted subject of a narrowed FAIL was reported as owed: {gap['paths']}")


def test_an_absent_failing_still_indicts_every_subject(ledger):
    """⛔ THE SAFETY HALF. No `failing` means the pre-LED-10 reading, all subjects indicted."""
    gap = _gap(ledger, [_rec("s1", "FAIL", FILES)], FILES)
    assert sorted(gap["paths"]) == ["docs/bad.md", "docs/good.md"]


def test_a_narrowed_undecided_covers_the_rest_too(ledger):
    """`build` narrows both blocking verdicts, so this reader must narrow both."""
    gap = _gap(ledger, [_rec("s1", "UNDECIDED", FILES, failing=["docs/bad.md"])], FILES)
    assert gap["paths"] == ["docs/bad.md"]


def test_a_pass_superseded_at_the_same_bytes_is_owed_again(ledger):
    """⚠ THE OTHER DIRECTION. A later revision FAIL over the same bytes is the deciding record;
    the earlier PASS must not keep the path off the work order while the gate reads FAIL."""
    recs = [_rec("s1", "PASS", FILES, revision=0), _rec("s1", "FAIL", FILES, revision=1)]
    gap = _gap(ledger, recs, FILES)
    assert sorted(gap["paths"]) == ["docs/bad.md", "docs/good.md"]
    assert _row(ledger, recs, FILES)["status"] == "FAIL", "the inventory must agree"


def test_gap_and_inventory_row_count_the_same_paths(ledger):
    """⭐ THE PARITY THAT WAS MISSING. Over a mixed stream, `have` here equals the row's covered
    count wherever the row covers by a passing reading."""
    recs = [_rec("s0", "PASS", {"docs/c.md": "ccc"}),
            _rec("s1", "FAIL", FILES, failing=["docs/bad.md"])]
    files = dict(FILES, **{"docs/c.md": "ccc", "docs/d.md": "ddd"})
    gap = _gap(ledger, recs, files)
    assert sorted(gap["paths"]) == ["docs/bad.md", "docs/d.md"]
    assert gap["have"] == 2


def test_a_narrowed_fail_is_no_reason_to_say_fix_the_findings(ledger):
    """`_gap_remedy` said "fix the findings, re-running changes nothing" on ANY FAIL subject at a
    current blob, including one the FAIL did not indict. Here `bad.md` moved since it was
    indicted, and `good.md`'s deciding record is an UNDECIDED, so re-running IS the remedy."""
    recs = [_rec("s1", "FAIL", {"docs/good.md": "aaa", "docs/bad.md": "old"},
                 failing=["docs/bad.md"]),
            _rec("s1", "UNDECIDED", {"docs/good.md": "aaa"}, revision=1)]
    gap = _gap(ledger, recs, FILES)
    assert gap["missing"] == gap["applies_to"] == 2
    assert gap["remedy"] == "run the step over the listed paths and record", gap["remedy"]


def test_a_live_indicting_fail_still_says_fix_the_findings(ledger):
    """⛔ The remedy's real case survives: the FAIL indicts bytes that are still here."""
    gap = _gap(ledger, [_rec("s1", "FAIL", FILES)], FILES)
    assert gap["remedy"].startswith("fix the findings")
