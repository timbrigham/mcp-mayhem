"""`heal_plan` — the witness half of self-healing.

⭐⭐ Tim, 2026-08-30: *"I absolutely love the term self-healing, anytime that that can be
implemented."* The ledger already knew what was stale, why, and what would clear it; it had no
way to say so as a PLAN. This is that, and only that — it names work, it never runs it. Keeping
it a witness is deliberate: a ledger that executes checks can no longer be trusted about them,
because it would be reporting on its own output.

⚠⚠ THE DISTINCTION IT EXISTS FOR: **STALE IS HEALABLE, FAILED IS NOT.** Stale means the answer
is unknown again, so re-running produces one. Failed means the checker looked and FOUND
something, so re-running finds it again. A self-healing loop that cannot tell them apart spins
forever on a real finding — the exact "loop where you're not actually making progress" that
`progress()` exists to detect.
"""

import pytest

from conftest import good
from core import inventory as inventory_mod


def _plan(ledger, records, files, admission, action="commit"):
    return inventory_mod.heal_plan(config=ledger.config, records=records, action=action,
                                   files=files, admission=admission)


# -- ⭐⭐ the distinction ------------------------------------------------------

def test_a_failed_step_is_never_auto(ledger):
    """⭐⭐ THE HEADLINE. Re-running a FAIL finds the same finding — putting it in `auto`
    builds a loop that never terminates and calls itself self-healing."""
    ledger.append(good(step="check_invariants", verdict="FAIL", reason="found a thing",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40}, ["check_invariants"])

    assert [e["step"] for e in out["auto"]] == []
    assert [e["step"] for e in out["blocked"]] == ["check_invariants"]
    assert "re-running finds it again" in out["blocked"][0]["why_not_auto"]


def test_a_stale_mechanical_step_is_auto(ledger):
    """⚠ Stale means the content moved, so the answer is simply unknown again.
    Deterministic, cheap, no judgement — the only thing honestly called self-healing."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    moved = {"x.lean": "c" * 40}          # same path, new blob
    out = _plan(ledger, ledger.store.records(), moved, ["check_invariants"])

    assert [e["step"] for e in out["auto"]] == ["check_invariants"]
    assert "re-running the checker" in out["auto"][0]["heals_by"]
    assert out["summary"]["healable"] == 1


def test_a_satisfied_step_appears_in_no_bucket(ledger):
    """⚠ A plan that lists work already done is a plan nobody finishes."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40}, ["check_invariants"])

    assert out["auto"] == [] and out["agent"] == [] and out["blocked"] == []
    assert out["summary"]["healable"] == 0


def test_a_missing_step_is_auto_when_mechanical(ledger):
    """⚠ Never recorded and gone stale are different facts with the SAME remedy: run it.
    Both belong in `auto`, or a fresh checkout reports nothing to do."""
    out = _plan(ledger, [], {"x.lean": "b" * 40}, ["check_invariants"])
    assert [e["step"] for e in out["auto"]] == ["check_invariants"]


# -- ⚠⚠ family is the second split, and it is not negotiable ------------------

def test_a_review_step_is_never_auto(ledger):
    """⚠⚠ A review step needs an agent and a judgement. Calling that automatic is how a
    review becomes a rubber stamp — so it lands in `agent` whatever its status."""
    out = _plan(ledger, [], {"x.lean": "b" * 40}, ["editorial"], action="push")

    assert [e["step"] for e in out["auto"]] == []
    assert [e["step"] for e in out["agent"]] == ["editorial"]
    assert "rubber stamp" in out["agent"][0]["why_not_auto"]


def test_the_three_buckets_are_disjoint(ledger):
    """⚠ One step, one bucket. Overlapping buckets would let a FAIL be counted as healable
    somewhere else in the same report."""
    ledger.append(good(step="check_invariants", verdict="FAIL", reason="found a thing",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40},
                ["check_invariants", "editorial", "check_prose"], action="push")

    steps = ([e["step"] for e in out["auto"]] + [e["step"] for e in out["agent"]]
             + [e["step"] for e in out["blocked"]])
    assert len(steps) == len(set(steps))


# -- ⚠ the report has to say what its own numbers mean ------------------------

def test_the_summary_states_what_each_bucket_means(ledger):
    """⚠ Three counts with no stated meaning is how a reader picks the flattering one —
    the defect the WHICH INDICATOR table exists to fix. The note travels with the numbers."""
    ledger.append(good(step="check_invariants", verdict="FAIL", reason="found a thing",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40}, ["check_invariants"])

    note = out["summary"]["note"]
    assert "re-running will not" in note and "finding has to be fixed" in note
    assert out["summary"]["auto"] == 0 and out["summary"]["blocked"] == 1


def test_it_reports_why_not_just_what(ledger):
    """⚠ `subjects_stale` and `evidence_stale` have different CAUSES and the same mechanical
    remedy. A reader told only "stale" who assumes a content change will look in the wrong
    place when it was the checker that moved."""
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "c" * 40}, ["check_invariants"])

    entry = out["auto"][0]
    assert "subjects_stale" in entry and "evidence_stale" in entry
    assert "evidence_moved" in entry


def test_a_failing_step_that_does_not_gate_is_named_not_hidden(ledger):
    """⚠⚠ MEASURED CONFUSION, 2026-08-30. ZeroParadox read `rely` as blocking its push and
    reported heal_plan for dropping a FAIL. It had not: `rely` is FAILING and REGISTERED but
    deliberately NOT in the push admission set — `admission.v1.json` removed it because its
    scope is `tools/verify/*`, so every fix to the tooling stales it while it gates the commit
    carrying that fix. It is documented there as unsatisfiable BY CONSTRUCTION.

    Silence was defensible (it does not gate, so it is not work) and was still wrong: a caller
    who believes a failing step blocks them will burn rounds on a gate that cannot close. Name
    it, and say it does not gate."""
    ledger.append(good(step="check_invariants", verdict="FAIL", reason="found a thing",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    # admitted set deliberately EXCLUDES the failing step
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40}, ["editorial"],
                action="push")

    assert [e["step"] for e in out["blocked"]] == []          # it is not work
    named = [e["step"] for e in out["failing_but_not_gating"]]
    assert named == ["check_invariants"]
    assert "does not block" in out["failing_but_not_gating"][0]["note"]


def test_a_failing_step_that_DOES_gate_stays_in_blocked(ledger):
    """⚠ The complement, so the two buckets cannot silently swap. A gating FAIL is work."""
    ledger.append(good(step="check_invariants", verdict="FAIL", reason="found a thing",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40}, ["check_invariants"])

    assert [e["step"] for e in out["blocked"]] == ["check_invariants"]
    assert out["failing_but_not_gating"] == []


def test_a_narrowed_step_cannot_hide_a_live_failure(ledger):
    """⭐⭐ THE HOLE THIS BUCKET HAD ON THE DAY IT WAS ADDED, AND IT COST THE MOST SERIOUS
    FINDING OF 2026-08-30. `prior_art` is narrowed to `actions: []` with `scope: 0`, so
    `inventory` evaluates no subjects, reports `record_id: null`, and the row's status is the
    NARROWING rather than any verdict. A real FAIL sat in the store — *"closest prior art
    located and uncited"*, naming a paper that documented the same phenomenon five months
    earlier — and it appeared in NO bucket, on the surface that decides whether to push.

    ⚠ "Narrowed out" and "nothing found" must not render identically. The first version of this
    bucket scanned ROWS, and a step with no scope has nothing to put in a row."""
    ledger.append(good(step="prior_art", verdict="FAIL", tier="A",
                       reason="closest prior art located and uncited",
                       decided={"how": "delegated", "who": "prior-art-review-agent",
                                "agreed": 1, "passes": 1},
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40},
                ["check_invariants"], action="push")

    named = [e["step"] for e in out["failing_but_not_gating"]]
    assert "prior_art" in named, "a narrowed step's live FAIL is invisible — the 2026-08-30 hole"
    entry = next(e for e in out["failing_but_not_gating"] if e["step"] == "prior_art")
    assert entry["live_subjects"] == 1
    assert "still true of these bytes" in entry["note"]


def test_a_narrowed_step_whose_findings_are_stale_is_not_reported(ledger):
    """⚠ THE COMPLEMENT, AND IT IS WHAT KEEPS THE BUCKET LEGIBLE. A FAIL against bytes that
    have since moved says nothing about the tree in front of you. Reporting every historical
    failure of every narrowed step would bury the one that still applies — the same argument as
    marking only genuinely stale `outstanding`, and as `skipped` being non-empty only when
    something was actually fenced."""
    ledger.append(good(step="prior_art", verdict="FAIL", tier="A",
                       reason="an old finding",
                       decided={"how": "delegated", "who": "prior-art-review-agent",
                                "agreed": 1, "passes": 1},
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    out = _plan(ledger, ledger.store.records(), {"x.lean": "c" * 40},   # content moved
                ["check_invariants"], action="push")

    assert "prior_art" not in [e["step"] for e in out["failing_but_not_gating"]]


def test_a_superseded_fail_is_not_reported(ledger):
    """⚠⚠ ZeroParadox'S CASE, AND IT ARRIVED WITHIN THE HOUR. Its `prior_art` went
    PASS -> FAIL -> PASS: the FAIL named uncited prior art, the next round cited it at the
    source and passed. If a superseded FAIL still surfaced because its subjects happen to match,
    the bucket would report a finding a later PASS has already answered — noise that trains the
    reader to ignore the bucket, which is how the signal dies.

    Handled by taking the LATEST record per step, not any failing one. Pinned because the
    behaviour is load-bearing and invisible in the code."""
    ledger.append(good(step="prior_art", verdict="FAIL", tier="A",
                       basis={"kind": "tree", "value": "5" * 40, "resolved_from": "explicit"},
                       reason="closest prior art located and uncited",
                       decided={"how": "delegated", "who": "prior-art-review-agent",
                                "agreed": 1, "passes": 1},
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    ledger.append(good(step="prior_art", verdict="PASS", tier="A",
                       basis={"kind": "tree", "value": "6" * 40, "resolved_from": "explicit"},
                       decided={"how": "delegated", "who": "prior-art-review-agent",
                                "agreed": 1, "passes": 1},
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))

    out = _plan(ledger, ledger.store.records(), {"x.lean": "b" * 40},
                ["check_invariants"], action="push")
    assert "prior_art" not in [e["step"] for e in out["failing_but_not_gating"]], \
        "a FAIL already answered by a later PASS was reported as live"
