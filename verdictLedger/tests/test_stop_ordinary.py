"""V18 — STOP-ORDINARY: a PASS that carries the findings it did not clear.

ZeroParadox's `R-LOOPCAP` gives a review round three outcomes, not two:

    BEDROCK   up to 5 rounds, MUST NOT SHIP
    ORDINARY  2 rounds, then STOP and push normally

Editorial round 6 returned STOP-ORDINARY — all three bedrock kill-list items verified
fixed on the rendered PDF bytes, no over-correction, four ordinary findings left, cap
reached. The process has a word for that state and it means PROCEED. The ledger had
only pass and fail, so the agent recorded FAIL and said why:

    "The ledger row reads FAIL; my verdict is STOP-ORDINARY… fail with the reason line
     stating STOP-ORDINARY is the only honest option… If that record blocks your push,
     it came from me and it is a ledger-vocabulary gap, not a new finding."

Refusing to paper over a vocabulary gap was right, and this file is the vocabulary.

⚠⚠ A CLEAN PASS AND A CAPPED PASS ARE DIFFERENT FACTS AND MUST NOT RENDER ALIKE. One
says nothing was found; the other says things WERE found, were judged ordinary, and
the loop was capped. Collapsing them rebuilds the ambiguity this ledger exists to
remove — the same argument that made `BACKFILLED` a finding rather than a footnote.
"""

import pytest

from conftest import good
from core import inventory as inventory_mod
from core.errors import ValidationFailure

BRIEF = ".claude/commands/editorial-review.md"


def errs(ledger, record):
    return ledger.validate(record)["errors"]


def capped(**over):
    """The STOP-ORDINARY shape: a delegated PASS carrying ordinary findings."""
    rec = good(step="editorial", tier="A", verdict="PASS",
               reason="STOP-ORDINARY at round 6; bedrock items verified fixed",
               subjects=[{"path": "README.md", "git_blob_id": "b" * 40}],
               evidence=[{"path": BRIEF, "git_blob_id": "e" * 40}],
               outstanding=[
                   {"severity": "ordinary", "path": "LEAN_CUSTOM_REGISTRY.md",
                    "note": "line 35 still says 'all three fields become theorems'"},
                   {"severity": "ordinary", "path": "OntBridge.lean",
                    "note": "line 78, same claim family as KILL-1"}],
               decided={"how": "delegated", "passes": 1, "agreed": 1,
                        "who": "editorial", "round": 6})
    rec.update(over)
    return rec


# -- ⭐⭐ the state that had no word -------------------------------------------

def test_a_pass_may_carry_ordinary_findings(ledger):
    """⭐⭐ THE HEADLINE. Round 6's verdict is now expressible: it admits, and the four
    findings ride on the record instead of evaporating into prose."""
    assert errs(ledger, capped()) == []
    assert ledger.append(capped())["appended"] is True


def test_it_admits_so_the_push_proceeds(ledger):
    """⚠ Tim's ruling, 2026-08-26: STOP-ORDINARY is a PASS condition. The verdict
    admits and `complete` is unaffected — that is the whole point of the change."""
    ledger.append(capped())
    inv = inventory_mod.build(config=ledger.config, records=ledger.store.records(),
                              action="push", files={"README.md": "b" * 40},
                              ref="t", admission=["editorial"])
    row = next(r for r in inv["rows"] if r["step"] == "editorial")
    assert row["status"] == "SATISFIED"
    assert inv["complete"] is True


def test_it_does_not_render_like_a_clean_pass(ledger):
    """⭐⭐ THE HALF THAT KEEPS IT HONEST. Everything downstream treats it as
    SATISFIED, so the row a human reads is the ONE place the two states can still be
    told apart — at exactly the moment someone is deciding whether to trust it."""
    from core import render as render_mod
    ledger.append(capped())
    rec = ledger.get(ledger.append(capped())["id"])
    line = render_mod.render(rec)
    assert "2 outstanding" in line

    clean = render_mod.render(ledger.get(ledger.append(
        capped(outstanding=[], basis={"kind": "tree", "value": "c" * 40,
                                      "resolved_from": "explicit"}))["id"]))
    assert "outstanding" not in clean


def test_the_inventory_row_carries_them_too(ledger):
    """⚠ A number a caller has to fetch a record to discover is one nobody fetches.
    It rides on the row and on the inventory, like `subjects_unexamined`."""
    ledger.append(capped())
    inv = inventory_mod.build(config=ledger.config, records=ledger.store.records(),
                              action="push", files={"README.md": "b" * 40},
                              ref="t", admission=["editorial"])
    row = next(r for r in inv["rows"] if r["step"] == "editorial")
    assert row["outstanding"] == 2
    assert inv["outstanding"] == 2
    assert "all three fields become theorems" in row["outstanding_notes"][0]


# -- ⚠⚠ the failure mode this must never become ------------------------------

@pytest.mark.parametrize("severity", ["bedrock", "BEDROCK", "blocking", "critical"])
def test_a_pass_can_never_carry_a_non_ordinary_finding(ledger, severity):
    """⚠⚠ THE SEVERITY SPLIT IS THE ENTIRE SAFETY OF THIS. STOP-ORDINARY admits
    BECAUSE the findings were judged ordinary. A bedrock or blocking finding riding a
    PASS is the thing the whole review loop exists to prevent, and `R-LOOPCAP` says
    bedrock MUST NOT SHIP."""
    rec = capped(outstanding=[{"severity": severity, "note": "the successor-bottom "
                               "novelty is asserted unfenced"}])
    found = [e for e in errs(ledger, rec) if e.startswith("V18")]
    assert found, f"{severity!r} was allowed onto a PASS"
    assert "never become a route to ship" in found[0]


def test_an_unrecognised_severity_refuses_rather_than_assuming_minor(ledger):
    """⚠⚠ THE DIRECTION THAT MATTERS. Enumerating every gate's vocabulary here would
    mean a gate inventing a new word gets a free pass until someone updates a list.
    `rely` grades BLOCKING/ORDINARY and editorial grades BEDROCK/ORDINARY; only the
    shared word admits, and anything unheard-of fails closed."""
    assert [e for e in errs(ledger, capped(
        outstanding=[{"severity": "moderate-ish", "note": "?"}]))
        if e.startswith("V18")]


def test_a_fail_may_carry_any_severity(ledger):
    """⚠ THE CONTROL. A FAIL already blocks; constraining severity there would only
    stop a gate reporting what it actually found."""
    rec = capped(verdict="FAIL", reason="bedrock outstanding",
                 outstanding=[{"severity": "bedrock", "note": "unfenced novelty"}])
    assert not [e for e in errs(ledger, rec) if e.startswith("V18")]


# -- ⚠ the finding has to be readable to be carried --------------------------

def test_a_finding_with_no_note_is_refused(ledger):
    """⚠ A finding nobody can read is not carried, it is lost — and the record would
    then assert that findings exist while saying nothing about them, which is worse
    than not carrying them at all."""
    assert any("needs a note" in e for e in
               errs(ledger, capped(outstanding=[{"severity": "ordinary"}])))


def test_outstanding_is_in_the_payload_so_it_cannot_be_edited_away(ledger):
    """⚠ Two records at one key with different outstanding sets are a V11 CONFLICT,
    not a silent dedupe. Otherwise re-recording the same verdict with the findings
    dropped would quietly succeed and read as identical."""
    ledger.append(capped())
    with pytest.raises(ValidationFailure, match="V11"):
        ledger.append(capped(outstanding=[
            {"severity": "ordinary", "note": "only one left now"}]))
