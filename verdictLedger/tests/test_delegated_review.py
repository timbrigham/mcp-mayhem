"""V17 — a delegated agent records its own verdict, under a named brief.

⚠⚠ THIS FILE EXISTS BECAUSE THE STREAM PROVED THE GAP. Measured 2026-08-25 across
every review record ever written: `editorial`, `adversary` and `rely` had THREE
records each, and all nine were FAIL. `claim_review`'s three PASSes came from a
checker, and `genesis` from a human. **No delegated review had ever recorded a PASS**,
because there was no honest way to — `agreement` refuses one round (V3 wants 3
unanimous), `mechanical` is a lie about a computation, and `signature` means a HUMAN
accepted a verdict the round did not produce.

⚠ AND THE ONE ROUTE THAT WORKED WAS THE WRONG ONE. `signature` with `who:
"adversary-agent"` validated clean — LED-6's shape one field over. `schema.py`
forbade it in a comment and nothing enforced it, so it was simultaneously the only
way to pass and the thing the design said not to do.

Tim, 2026-08-25: *"the entire idea having these agents is so that I can delegate trust
to them."* That intent was in NEITHER contract, which is how a stale transitional
comment — "the sanctioned cheap route WHILE EMITTERS ARE LANDING" — came to overrule
it after the emitters landed.

⚠ THE ACCOUNTABILITY IS THE BRIEF, NOT A PROCESS IDENTITY. §2 rules out keys; `sign`
concedes attribution is not authentication. "Prove you are that agent" was never
available. What is checkable is which instructions governed the round and whether they
have changed — so `evidence` names the brief, and editing the brief stales the key.
"""

import pytest

from conftest import good
from core.errors import ValidationFailure

BRIEF = ".claude/commands/adversary-review.md"


def errs(ledger, record):
    return ledger.validate(record)["errors"]


def review(**over):
    """A delegated review record: one agent, one brief, no consensus claimed."""
    rec = good(step="adversary", tier="A", verdict="PASS",
               reason="reviewed; no findings",
               subjects=[{"path": "README.md", "git_blob_id": "b" * 40}],
               evidence=[{"path": BRIEF, "git_blob_id": "e" * 40}],
               decided={"how": "delegated", "passes": 1, "agreed": 1,
                        "who": "adversary"})
    rec.update(over)
    return rec


# -- ⭐⭐ the thing that could not be done before -------------------------------

def test_one_agent_can_finally_record_a_review_pass(ledger):
    """⭐⭐ THE HEADLINE, and the whole point of the change. Nine review records in
    the stream, every one a FAIL, because a single round had no honest route to PASS."""
    assert errs(ledger, review()) == []
    assert ledger.append(review())["appended"] is True


def test_it_claims_no_consensus_and_v3_is_untouched(ledger):
    """⚠⚠ THE OBJECTION THIS ANSWERS. `schema.py` refused a fifth enum value on the
    grounds that it would "re-open precisely what V3 exists to close — single-pass AI
    verdicts wearing a consensus badge — under a new name". That is a non-sequitur:
    V3 closes MISLABELLING, a single pass claiming `agreed == passes >= 3`. `delegated`
    wears no badge. V3 must still refuse the thing it always refused."""
    with pytest.raises(ValidationFailure, match="V3"):
        ledger.append(review(decided={"how": "agreement", "passes": 1,
                                      "agreed": 1, "who": "adversary"}))


# -- ⭐ what a delegated record must carry -------------------------------------

def test_a_delegated_pass_must_name_its_brief(ledger):
    """⭐ The expiry is the point. Without evidence the verdict names no instructions,
    so editing the brief can never stale it and a review outlives the rules it was
    made under."""
    found = [e for e in errs(ledger, review(evidence=[])) if e.startswith("V17")]
    assert found and "brief" in found[0]


def test_editing_the_brief_stales_the_review(ledger):
    """⭐⭐ THE PROPERTY THE WHOLE DESIGN RESTS ON, and it is V16's machinery pointed
    at review. The record NAMES the brief's blob, so changing the brief moves it: the
    key goes STALE and the gate re-runs. A delegated verdict cannot outlive its
    instructions — which is what makes delegation safe WITHOUT authentication."""
    from core import inventory as inventory_mod
    ledger.append(review())
    recs = ledger.store.records()

    def inv(brief_blob):
        return inventory_mod.build(
            config=ledger.config, records=recs, action="push",
            files={"README.md": "b" * 40, BRIEF: brief_blob}, ref="t",
            admission=["adversary"])

    before = next(r for r in inv("e" * 40)["rows"] if r["step"] == "adversary")
    after = next(r for r in inv("f" * 40)["rows"] if r["step"] == "adversary")
    assert before["status"] == "SATISFIED"
    assert after["status"] == "STALE"


def test_a_delegated_verdict_must_say_which_gate(ledger):
    """⚠ `who` on EVERY delegated record, not just a PASS. A finding attributed to
    nobody is the anonymous-approval hole V5 closes, arriving through the review door.
    It costs nothing — the gate knows its own name."""
    for verdict, reason in (("PASS", None), ("FAIL", "found three things")):
        rec = review(verdict=verdict, reason=reason,
                     decided={"how": "delegated", "passes": 1, "agreed": 1,
                              "who": None})
        assert any(e.startswith("V17") for e in errs(ledger, rec)), verdict


def test_a_delegated_fail_needs_no_brief(ledger):
    """⚠ PASS-only for evidence, like V2 and V16. A FAIL blocks, so it cannot
    fail-open — and requiring the brief there would stop an agent that could not read
    it from reporting the finding at all."""
    assert not any(e.startswith("V17") for e in errs(
        ledger, review(verdict="FAIL", reason="three findings", evidence=[])))


# -- ⚠ tier must agree with how, for this value at least ----------------------

@pytest.mark.parametrize("tier", ["M", "H"])
def test_a_delegated_round_is_an_ai_round(ledger, tier):
    """⚠ The NARROW case of LED-7, closed here for `delegated` only: 'M' claims a
    computation and 'H' claims a person decided. Both describe a different verdict
    than the one that happened. LED-7 stays open for the rest — one moving part at a
    time."""
    found = [e for e in errs(ledger, review(tier=tier)) if e.startswith("V17")]
    assert found and "must be 'A'" in found[0]


# -- ⚠⚠ the route that was wrong and worked -----------------------------------

def test_the_agent_signature_hole_is_what_this_replaces(ledger):
    """⚠⚠ MEASURED 2026-08-25: `signature` with `who: "adversary-agent"` validated
    CLEAN. `schema.py` forbade exactly that in prose and nothing enforced it, so it
    was simultaneously the only working route to a review PASS and the thing the
    design said not to do — LED-6's shape, one field over.

    ⚠ THIS TEST DOES NOT ASSERT IT IS NOW REFUSED, because it is not. Closing it means
    deciding who may appear in `who` for a genuine human `signature`, which is LED-8
    and is a separate change. What this pins is that a HONEST route now exists, so
    nobody has to take the dishonest one. Delete this test when LED-8 lands.
    """
    agent_sig = review(decided={"how": "signature", "passes": 1, "agreed": 1,
                                "who": "adversary-agent"}, tier="A")
    assert errs(ledger, agent_sig) == [], (
        "still open — LED-8; the point is that `delegated` now exists as the honest "
        "alternative")
    assert errs(ledger, review()) == []
