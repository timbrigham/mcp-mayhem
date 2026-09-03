"""A FAIL condemns the bytes it INDICTS, never every byte it happened to examine.

⛔⛔ MEASURED 2026-09-02, AND IT HAD CONDEMNED AN ENTIRE PUSH — sixteen commits, parked.
ZeroParadox healed nine short intermediates by checking each out in a worktree and re-running
the six tip-only mechanical steps. Two of those commits genuinely carried a defect
(`check_codebox.py` existed as an orphan no checker invoked), so `check_checkers` honestly
recorded FAIL at each. **The count went from 8 short to 15 short — every commit in the range,
including the tip, and including a commit that predated `check_codebox.py` existing at all.**

The records, from the live stream:

    FAIL @140bf315  subjects=24  reason="2 failing subject(s): .../(roster), .../check_codebox.py"
    PASS @8cd8cc32  subjects=24  <- the tip, genuinely clean, codebox fixed ddba1f95 -> e64f7d16

**23 of those 24 subjects carry byte-identical blobs in both records.** The step examined the
whole roster and failed on one member, but emitted a single FAIL naming all 24 as subjects — so
its indictment and its coverage were the same list. The FAIL was written later, `_index` keeps
the highest revision and ties go to the last writer, and worst-verdict-wins then read FAIL for
every commit sharing those 23 innocent blobs.

⚠⚠ THE REMEDY WAS UNREACHABLE, which is what makes this worse than a wrong answer. Re-running
cannot clear it: the checker is honest and the bytes it indicted really did move on. ZeroParadox
recorded a fresh PASS at the tip and the refusal did not change, then correctly stopped rather
than infer a fourth model and act on it — every experiment writes to an append-only permanent
record.

⭐ THIS IS THE CONTENT-KEYED RULE IN THE DIRECTION IT WAS MISSING. Coverage already demanded
proof that THESE EXACT BYTES were examined — Tim, 2026-09-01: *"I don't think anything should be
gated unless we have proof the exact bytes of a file were tested in a previous blob."*
Condemnation is that same claim with the sign flipped, and it was travelling freely to bytes
nobody had judged.

⚠ `record.emit`'s docstring already specified the correct shape — "a step that examined forty
files and failed on one emits a PASS over the thirty-nine and a FAIL over the one" — so a single
wide FAIL was always malformed. The stream is APPEND-ONLY and those records cannot be withdrawn,
so the ledger reads `failing` when a record carries it and falls back to the old all-subjects
reading when it does not.
"""

import pytest

from core import inventory as inventory_mod


STEP = "check_prose"


def _rec(sha, verdict, subjects, rid=None, revision=0, failing=None):
    """A record whose subject set and indicted set can differ."""
    rec = {"id": rid or f"{STEP}@{sha}#{revision}", "step": STEP, "verdict": verdict,
           "revision": revision,
           "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
           "subjects": [{"path": p, "git_blob_id": b} for p, b in subjects.items()],
           "basis": {"kind": "tree", "value": sha}}
    if failing is not None:
        rec["failing"] = failing
    return rec


def _build(ledger, records, files):
    return inventory_mod.build(config=ledger.config, records=records, action="push",
                               files=files, ref="deadbeef")


def _row(inv):
    return next(r for r in inv["rows"] if r["step"] == STEP)


# ⭐⭐ the headline: the exact shape that parked the push ----------------------

def test_a_wide_fail_does_not_condemn_the_innocent_bytes_beside_it(ledger):
    """⭐⭐ THE REGRESSION, IN MINIATURE. Two files examined together; only `bad.md` failed.
    `good.md` never changed. Asking about a tree where `bad.md` has been FIXED must not
    return FAIL — the FAIL is about bytes that are no longer here."""
    broken = {"good.md": "aaa", "bad.md": "old"}
    fixed = {"good.md": "aaa", "bad.md": "new"}

    # ⚠⚠ THE FAIL IS WRITTEN LAST, exactly as in the live stream (lines 1588 vs 1642/1649).
    # `_index` resolves ties on `>=`, so the later record owns every shared content key —
    # which is how the FAIL came to own 23 blobs the clean tip PASS had already covered.
    # Ordering the PASS last makes this test pass without the fix; it was, and it was wrong.
    records = [
        _rec("s2", "PASS", fixed, rid=f"{STEP}@s2#0"),
        _rec("s1", "FAIL", broken, failing=["bad.md"]),
    ]
    row = _row(_build(ledger, records, fixed))

    assert row["status"] == "SATISFIED", (
        f"a FAIL indicting only bad.md condemned the tree that fixed it — status {row['status']}")


def test_the_fail_still_condemns_the_bytes_it_named(ledger):
    """⛔ THE OTHER HALF, AND THE ONE THAT MATTERS FOR SAFETY. Narrowing the indictment must
    not make a real FAIL vanish. While `bad.md` still carries the indicted blob, the step FAILS."""
    broken = {"good.md": "aaa", "bad.md": "old"}
    records = [_rec("s1", "FAIL", broken, failing=["bad.md"])]
    row = _row(_build(ledger, records, broken))

    assert row["status"] == "FAIL", "the indicted bytes are still present and must still fail"


def test_a_fail_cannot_reach_backwards_into_history_it_never_judged(ledger):
    """⚠⚠ THE PART THAT MADE IT SPREAD. A commit that predates the bad file entirely still read
    FAIL, because it shared the innocent blobs. Nothing here was ever indicted, so nothing here
    may fail."""
    broken = {"good.md": "aaa", "bad.md": "old"}
    earlier = {"good.md": "aaa"}                       # bad.md does not exist yet

    records = [_rec("s0", "PASS", earlier, rid=f"{STEP}@s0#0"),
               _rec("s1", "FAIL", broken, failing=["bad.md"])]      # FAIL last, as measured
    row = _row(_build(ledger, records, earlier))

    assert row["status"] == "SATISFIED", (
        f"a FAIL about a file that does not exist here condemned this tree — {row['status']}")


# ⚠ back-compatibility: silence must not be read as innocence -----------------

def test_a_fail_without_failing_still_indicts_every_subject(ledger):
    """⚠⚠ NO HISTORICAL FAIL IS WEAKENED BY THIS LANDING. Records written before `failing`
    existed carry no indictment list, and absent MUST mean all-subjects — the pre-existing
    reading exactly. Treating silence as "nothing indicted" would turn every legacy FAIL in an
    append-only stream into a PASS, which is the one change that could never be undone."""
    broken = {"good.md": "aaa", "bad.md": "old"}
    fixed = {"good.md": "aaa", "bad.md": "new"}

    records = [_rec("s2", "PASS", fixed, rid=f"{STEP}@s2#0"),
               _rec("s1", "FAIL", broken)]            # no `failing` key at all, written last
    row = _row(_build(ledger, records, fixed))

    assert row["status"] != "SATISFIED", (
        "a legacy wide FAIL was silently narrowed — every pre-2026-09-02 FAIL just became a PASS")


def test_the_sanctioned_remedy_is_a_higher_revision(ledger):
    """⭐ HOW A WIDE FAIL IS CORRECTED WITHOUT EDITING THE PAST. The stream is append-only, so
    the record is re-emitted at a HIGHER REVISION naming its real indicted subset. `_index`
    resolves each content key to the highest revision, so the correction supersedes per-content
    and the original stays readable. This is the answer to "tell me the sanctioned way and I
    will do it rather than invent one"."""
    broken = {"good.md": "aaa", "bad.md": "old"}
    fixed = {"good.md": "aaa", "bad.md": "new"}

    records = [
        _rec("s2", "PASS", fixed, rid=f"{STEP}@s2#0"),
        _rec("s1", "FAIL", broken),                                        # legacy: condemns all
        _rec("s1", "FAIL", broken, revision=1, failing=["bad.md"]),        # correction
    ]
    row = _row(_build(ledger, records, fixed))

    assert row["status"] == "SATISFIED", (
        f"the revision-1 correction did not supersede the wide FAIL — {row['status']}")


def test_narrowing_changes_the_rendered_verdict_not_just_the_count(ledger):
    """⚠ A ROW MAY NOT SAY FAIL WHILE COUNTING AS COMPLETE. If the narrowing moved `complete`
    but left the status reading FAIL, that is precisely the collapse-of-distinct-statuses this
    module forbids — and it would be read as "the gate is broken" rather than "the gate is
    satisfied"."""
    fixed = {"good.md": "aaa", "bad.md": "new"}
    records = [_rec("s2", "PASS", fixed, rid=f"{STEP}@s2#0"),
               _rec("s1", "FAIL", {"good.md": "aaa", "bad.md": "old"}, failing=["bad.md"])]
    row = _row(_build(ledger, records, fixed))

    assert row["status"] == "SATISFIED"
    assert row["status"] != "FAIL", "status and completeness disagree about the same record"


# -- ⛔ the interrogation tool that answered a typo with a confident empty set ---

def test_find_matches_a_verdict_regardless_of_case(ledger):
    """⛔⛔ REPORTED BY ZeroParadox 2026-09-02. `find(verdict='fail')` returned **count 0**
    while four FAIL records for that step sat in the stream, because the comparison was exact
    against a stored `"FAIL"`. An empty result is precisely what "no such records" looks like,
    so the tool answered a typo with a calm, confident, wrong answer — and they nearly acted on
    it: *"I would have concluded no FAIL records existed if I had not queried again unfiltered."*
    """
    from conftest import good
    ledger.append(good(verdict="FAIL", reason="one bad file"))
    assert ledger.find(verdict="fail")["count"] == 1, "lowercase filter found nothing"
    assert ledger.find(verdict="FAIL")["count"] == 1
    assert ledger.find(verdict="  Fail ")["count"] == 1


def test_find_refuses_a_value_that_is_not_a_verdict(ledger):
    """⚠⚠ CASE WAS ONLY HALF OF IT. Folding case makes `'fail'` work and leaves `'failed'`
    silently empty — the same fail-open one letter further out. An unrecognised filter value is
    a caller error and must SAY so, because the empty set is already spoken for: it means
    "none match"."""
    from core.errors import UsageError

    with pytest.raises(UsageError) as exc:
        ledger.find(verdict="failed")
    msg = str(exc.value)
    assert "not a verdict" in msg
    assert "FAIL" in msg, "the refusal must name the valid values, not just reject"


# -- ⚠ the field must be storable, and must not be storable in a misleading place ---

def test_a_record_carrying_failing_is_accepted(ledger):
    """⛔ THE ONE THAT WOULD HAVE BITTEN THE PEER. V7 rejects unknown top-level keys, so
    before `failing` was added to `schema.TOP_LEVEL` a record carrying it was REFUSED outright
    — and I had already told ZeroParadox to write two such records. Caught by asking whether
    the write path accepted what the read path had learned to understand."""
    from conftest import good
    rec = good(verdict="FAIL", reason="one bad file", failing=["docs/x.md"])
    out = ledger.append(rec)                       # must not raise ValidationFailure
    assert out.get("id"), f"append returned no record id: {out}"
    stored = ledger.find(verdict="FAIL")
    assert stored["count"] == 1
    assert stored["records"][0]["failing"] == ["docs/x.md"], (
        "the field round-tripped through the store unchanged")


def test_failing_on_a_non_fail_is_rejected_not_ignored(ledger):
    """⚠⚠ THE WORST SHAPE AVAILABLE, IF IT WERE ALLOWED. The resolver consults `failing` only
    on a FAIL, so a `failing` list on a PASS would be accepted, stored, and silently ignored —
    a record that LOOKS like it narrows an indictment and narrows nothing. Same reasoning as
    V7: an unreadable claim is rejected, never quietly dropped."""
    from conftest import good
    from core.errors import ValidationFailure

    with pytest.raises(ValidationFailure) as exc:
        ledger.append(good(verdict="PASS", failing=["docs/x.md"]))
    assert "only meaningful on a FAIL" in str(exc.value)


def test_an_empty_failing_is_rejected(ledger):
    """⚠ AN EMPTY INDICTMENT IS A FAIL THAT CANNOT FAIL. `failing: []` would resolve to PASS at
    every path — exoneration wearing the costume of a FAIL, and reachable by a caller who meant
    to omit the field. Absent means all-subjects; empty must not be a quiet synonym for none."""
    from conftest import good
    from core.errors import ValidationFailure

    with pytest.raises(ValidationFailure) as exc:
        ledger.append(good(verdict="FAIL", reason="x", failing=[]))
    assert "must not be empty" in str(exc.value)


# -- ⭐⭐ narrow(): the sanctioned correction, without retyping a single blob id ---

def _wide_fail_in_store(ledger):
    from conftest import good
    rec = good(verdict="FAIL", reason="one bad file among many",
               subjects=[{"path": "docs/x.md", "git_blob_id": "b" * 40},
                         {"path": "docs/ok.md", "git_blob_id": "d" * 40}])
    return ledger.append(rec)["id"]


def test_narrow_supersedes_at_a_higher_revision_without_retyping_subjects(ledger):
    """⭐⭐ THE FOURTH ROUTE. Asked to correct two wide FAILs, ZeroParadox found three ways and
    rejected all three — hand-authoring 24 blob ids into an append-only stream (*"transcription
    risk on an append-only record is exactly the wrong risk to take"*), recomputing under a
    worktree carrying the OLD checker module, or adding a `revision` passthrough that its own
    docstring forbids. **All three refusals were correct.** This route copies `subjects`,
    `evidence` and `basis` verbatim from the stored record and takes the revision from the store,
    so nothing is retyped and nothing is recomputed."""
    rid = _wide_fail_in_store(ledger)
    out = ledger.narrow(record_id=rid, failing=["docs/x.md"])

    assert out["appended"] is True
    corrected = ledger.get(out["id"])
    assert corrected["revision"] == 1, "the correction must supersede, not branch"
    assert corrected["failing"] == ["docs/x.md"]
    # ⚠ VERBATIM: the subject set is unchanged. `narrow` alters the INDICTMENT, never coverage.
    original = ledger.get(rid)
    assert corrected["subjects"] == original["subjects"]
    assert corrected["verdict"] == "FAIL", "narrow is not a route from FAIL to PASS"


def test_narrow_refuses_to_exonerate(ledger):
    """⚠⚠ THE GUARD THAT MATTERS, AND IT IS THE EMPTY-`failing` HOLE IN DISGUISE. Entries that
    are not subjects are INERT for resolution — nothing resolves `tools/verify/(roster)` to
    content. So a `failing` naming ONLY non-subjects indicts nothing and the FAIL reads as a PASS
    everywhere it covers. ⚠ Pseudo-paths riding ALONGSIDE a real subject stay legal, because a
    roster-level finding is a true indictment that happens not to be a file."""
    from core.errors import UsageError

    rid = _wide_fail_in_store(ledger)
    with pytest.raises(UsageError) as exc:
        ledger.narrow(record_id=rid, failing=["tools/verify/(roster)"])
    assert "inert" in str(exc.value) or "exonerate" in str(exc.value)

    # the same pseudo-path is fine WITH a real subject beside it
    out = ledger.narrow(record_id=rid,
                        failing=["docs/x.md", "tools/verify/(roster)"])
    assert ledger.get(out["id"])["failing"] == ["docs/x.md", "tools/verify/(roster)"]


def test_narrow_refuses_a_non_fail_and_an_empty_list(ledger):
    """⚠ The two ways to reach an exoneration by accident, both closed at the operation."""
    from conftest import good
    from core.errors import UsageError

    rid = _wide_fail_in_store(ledger)
    with pytest.raises(UsageError, match="non-empty"):
        ledger.narrow(record_id=rid, failing=[])

    # ⚠ A DIFFERENT BASIS. Reusing the FAIL's basis collides on V11 (same step+basis+revision,
    # different payload) — correctly, and it is not what this test is about.
    ok = ledger.append(good(verdict="PASS",
                            basis={"kind": "tree", "value": "e" * 40,
                                   "resolved_from": "explicit"}))["id"]
    with pytest.raises(UsageError) as exc:
        ledger.narrow(record_id=ok, failing=["docs/x.md"])
    assert "is a FAIL" in str(exc.value) or "applies to a FAIL" in str(exc.value)


def test_narrow_refuses_an_unknown_record(ledger):
    """⚠ A correction to a record that does not exist is a typo, not a narrowing."""
    from core.errors import UsageError
    with pytest.raises(UsageError, match="no record"):
        ledger.narrow(record_id="check_prose@nope#0", failing=["docs/x.md"])


def test_narrow_refuses_to_resurrect_a_superseded_fail(ledger):
    """⛔⛔ THE FOOTGUN IN THE FIX, FOUND BY SIMULATING BEFORE SHIPPING.

    Narrowing re-emits at a HIGHER revision, and revision decides which record owns a content
    key — so narrowing a FAIL that a later PASS has already overtaken lifts it back ABOVE that
    PASS and condemns content which has since been fixed.

    ⚠ MEASURED 2026-09-02 against the live stream, read-only: narrowing ALL SIX `check_checkers`
    FAILs put `check_codebox.py@e64f7d16` — the TIP's own bytes, repaired at `972f8c2a` and
    passed twice after — back under a FAIL, condemning the tip. Narrowing only the TWO records
    that were genuinely current cleared every FAIL in the range and left the tip `failed=[]`.

    ⭐ ZeroParadox predicted the shape from the record alone (*"tip-green has a hole, and it is
    the same shape again"*) and asked me not to build the leg until it was settled. They were
    right that it bites — through REVISION, not through blob-presence — and this is where it is
    stopped, at the write path rather than in the gate."""
    from conftest import good
    from core.errors import UsageError

    blob = "b" * 40
    ledger.append(good(verdict="FAIL", reason="orphan at the time",
                       subjects=[{"path": "docs/x.md", "git_blob_id": blob}]))
    rid = f"check_invariants@{'a' * 40}#0"

    # a later PASS over the SAME bytes — the defect was relational and got fixed elsewhere
    ledger.append(good(verdict="PASS",
                       basis={"kind": "tree", "value": "c" * 40, "resolved_from": "explicit"},
                       subjects=[{"path": "docs/x.md", "git_blob_id": blob}]))

    with pytest.raises(UsageError) as exc:
        ledger.narrow(record_id=rid, failing=["docs/x.md"])
    msg = str(exc.value)
    assert "SUPERSEDED" in msg
    assert "docs/x.md" in msg, "the refusal must name which bytes are already held elsewhere"
