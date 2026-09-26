"""`preflight` prices the gate pipeline and not the admission set, and now says so.

⛔⛔ THE THIRD FALSE GREEN FROM ONE FUNCTION, measured 2026-09-26. The consumer ran `preflight()`,
got **PASSED 21/21 exit 0**, and `can_push()` REFUSED the same range on `copy_editor` — tip
required 21, satisfied 20, stale 1. Both answers were correct and neither was a bug:

    preflight()   the GATE PIPELINE at this HEAD.  0 references to ledger_client / inventory /
                  admission in its 104 lines. The 21/21 is GATES.
    can_push()    every commit in the range against the ADMISSION SET.

⭐ SO IT IS AN ABSENT CHECK RATHER THAN A WRONG ANSWER, and the computation it was suspected of
was verified correct in the same measurement (`complete: false`, not a fail-open). That is
"absence is never success" where the absence is an entire question.

⚠ THE PRIOR TWO ARE ALREADY RECORDED AT THAT FUNCTION, which is the argument for a FIELD rather
than a fourth comment: 2026-09-05, `would_block_push` read as the list of what blocks a push — a
27-minute preflight, green, then refused on eleven intermediate commits; 2026-09-15, `passed` at a
HEAD whose push failed on 76 files eighteen minutes later. Three misreadings, three distinct
causes, one shape.

⛔ `status.would_block_push` earned `would_block_push_scope` and `range_question` for exactly this
and `preflight` earned nothing. This file pins the field onto ALL THREE surfaces from ONE
constant, because a scope warning on one path and silence on another is the half-applied guard
that already shipped once here (the 2026-09-22 freeze caveat, which rendered only in the BROKEN
state and was silent in the one that produced the defect).
"""

import inspect

import pytest

from core import engine


def test_the_constant_names_what_is_not_priced_and_the_remedy():
    """⚠ A refusal-shaped disclosure still owes the success condition: a reader must be able to
    construct the next action from this text alone."""
    scope = engine.PREFLIGHT_SCOPE
    assert "GATE PIPELINE" in scope
    # ⛔ the absent check, named
    assert "does NOT consult" in scope and "admission set" in scope
    # ⛔ and it must deny the inference that actually got made, not merely describe itself
    assert "NOT a prediction" in scope
    # ⭐ THE REMEDY, AND IT IS MATCHED AS A CALLABLE RATHER THAN AS A WORD. ⛔ The first
    # version asserted `"can_push" in scope` and a mutation that deleted the whole remedy
    # sentence SURVIVED — because `can_push` also appears in the measurement clause ("while
    # can_push REFUSED the same range"). A detector matching a name that occurs incidentally is
    # testing a proxy for the property, which is `DC-51` in the control rather than the code.
    assert "can_push(rev_range=" in scope, (
        "the scope names no CALLABLE remedy — the V9 lesson is that a refusal must hand over a "
        "route, and a bare tool name is not one")
    # ⚠ tip-vs-range is the OTHER half; omitting it would trade one false green for a narrower
    assert "TIP-SCOPED" in scope


@pytest.mark.parametrize("surface", ["preflight_running", "preflight_done", "preflight_status"])
def test_every_preflight_surface_carries_the_scope(surface):
    """⛔⛔ ALL THREE, FROM THE SAME CONSTANT. The consumer read `preflight_status`, not
    `preflight`, so a field on the call and not the poll would have missed the actual reader.

    ⚠ Asserted over source because two of the three are only reachable by running a ~25-minute
    pipeline, and a behavioural probe that cannot run is worse than a structural one that does:
    it reads as covered while testing nothing.
    """
    src = {"preflight_running": inspect.getsource(engine.GitRobot.preflight),
           "preflight_done": inspect.getsource(engine.GitRobot.preflight),
           "preflight_status": inspect.getsource(engine.GitRobot.preflight_status)}[surface]
    assert "PREFLIGHT_SCOPE" in src, (
        f"{surface} does not attach the scope disclosure — a green from it can still be read "
        f"as 'the push will go', which is what it was three times")
    assert '"passed_prices"' in src or "'passed_prices'" in src


def test_the_two_returns_of_preflight_both_carry_it():
    """⚠ `preflight` has a RUNNING return and a COMPLETION return, and the running one is what a
    caller holds for the 25 minutes it could be fetching the other answer in parallel. A field on
    only the post-mortem arrives after the window it exists to open."""
    src = inspect.getsource(engine.GitRobot.preflight)
    # ⛔ COUNT THE USE, NOT THE MENTION. The first version counted `PREFLIGHT_SCOPE` anywhere in
    # the source and a mutation deleting the running return's field SURVIVED — because a COMMENT
    # in the other branch says "See PREFLIGHT_SCOPE." The control was counting prose about the
    # marker, which is the third instance of that shape in this arc.
    uses = src.count('"passed_prices": PREFLIGHT_SCOPE')
    assert uses >= 2, (
        f"only {uses} of preflight's two returns attaches the scope to a field; a comment "
        f"mentioning the constant is not a disclosure a caller receives")


def test_it_is_one_constant_and_not_a_restatement():
    """⛔ THE ANTI-DRIFT ASSERTION. Three surfaces quoting one constant cannot disagree; three
    hand-written paragraphs will, and the one that goes stale is the one nobody re-reads. This is
    the same argument `docs://*/vocabulary` makes and the same one `EXIT_CODES` makes."""
    import re
    src = inspect.getsource(engine)
    # the sentence must appear as a literal EXACTLY once — its definition
    literal = "PRICES THE GATE PIPELINE ONLY"
    assert src.count(literal) == 1, (
        f"{src.count(literal)} copies of the scope text; it must be defined once and referenced")


def test_preflight_still_does_not_consult_the_admission_set():
    """⚠⚠ PINS THE CURRENT TRUTH SO THE DISCLOSURE CANNOT OUTLIVE IT. Tim ruled 2026-09-26:
    disclose now, THEN make preflight actually consult the ledger. When that second half lands,
    this test must fail — and the text above must be rewritten in the same change.

    ⛔ Without this, the honest disclosure becomes a false one the moment the behaviour improves,
    which is the exact failure mode of a hand-maintained claim about code: it is written true and
    nothing makes it stay true. **A disclosure that outlives its cause is a lie with provenance.**
    """
    src = inspect.getsource(engine.GitRobot.preflight)
    consults = [t for t in ("ledger_client", "inventory(", "admission_for") if t in src]
    assert not consults, (
        f"preflight now consults {consults} — the second half of the ruling has landed, so "
        f"PREFLIGHT_SCOPE is now FALSE and must be rewritten in this same change. Delete this "
        f"test and replace it with one asserting the admission set is checked.")
