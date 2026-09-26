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
    # ⛔ WHAT `passed` IS SCOPED TO. ⚠ This assertion was rewritten when the second half of the
    # ruling landed: it used to require "does NOT consult", which became FALSE once
    # `admission_at_tip` shipped — preflight does consult now, just not in `passed`. The test
    # moved with the truth rather than pinning a sentence that had stopped being one.
    assert "admission set" in scope
    assert "`passed` PRICES THE GATE PIPELINE ONLY" in scope
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


def test_preflight_now_consults_the_admission_set_in_its_own_field():
    """⭐⭐ THE SECOND HALF OF THE RULING, AND THIS TEST REPLACED ITS OWN PREDECESSOR.

    Until this landed, `test_preflight_still_does_not_consult_the_admission_set` asserted the
    opposite and carried its own expiry note: *"when that second half lands, this test must fail —
    and the text above must be rewritten in the same change."* It did, and it was. **A disclosure
    that outlives its cause is a lie with provenance**, and the only thing that reliably retires
    one is a test that breaks when the truth moves.

    ⛔ `passed` IS UNTOUCHED, WHICH IS THE WHOLE SHAPE OF TIM'S CALL. It is a value the consumer
    branches on, and CLAUDE.md requires such a change to be coordinated client-first — the one
    time that was skipped, flipping `isError` unilaterally collapsed every structured refusal the
    consumer received into None.
    """
    src = inspect.getsource(engine.GitRobot.preflight)
    assert "_admission_at_tip" in src, "preflight does not consult the admission set"
    assert '"admission_at_tip": admission' in src, (
        "the admission answer is computed and not reported — the absent check, one layer in")
    # ⛔⛔ AND `passed` MUST STILL COME STRAIGHT FROM THE GATE RESULT, MATCHED WITH ITS TERMINATOR.
    # ⚠ The first version asserted the substring `"passed": gate.passed` and a mutant reading
    # `"passed": gate.passed and bool(admission…)` SURVIVED it — the forbidden client-breaking
    # flip, passing a control written to forbid it, because the mutant CONTAINS the substring.
    # Fourth proxy-matching assertion of my own caught by mutation in one arc. The comma is the
    # guard: it pins that nothing is composed onto the value.
    assert '"passed": gate.passed,' in src, (
        "`passed` no longer comes straight from the gate result; composing the admission answer "
        "into it is the client-first coordinated change CLAUDE.md forbids doing unilaterally, "
        "and the whole reason `admission_at_tip` is a separate field")


def test_the_admission_field_reports_and_never_refuses(robot, repo, monkeypatch):
    """⛔⛔ DISCLOSURE, NOT A GATE. Two things must not both be the authority: `can_push` refuses a
    push, and this reports. A preflight that began refusing on admission would change what a green
    MEANS for a caller mid-arc, and preflight is advisory by construction."""
    from core import engine as engine_mod
    monkeypatch.setattr(engine_mod.ledger_client, "inventory",
                        lambda *a, **k: {"admission_state": "SET", "complete": False,
                                         "required": 21, "satisfied": 20, "stale": ["copy_editor"]})
    monkeypatch.setattr(engine_mod.ledger_client, "admission_for", lambda action: ["copy_editor"])
    out = robot._admission_at_tip("a" * 40)
    assert out["would_push_be_allowed_at_this_tip"] is False
    assert out["required"] == 21 and out["satisfied"] == 20
    assert "DISCLOSURE, NOT A GATE" in out["authority"]
    # ⚠ the tip caveat survives the fix — consulting admission closed one gap, not both
    assert "THE TIP ONLY" in out["scope"] and "can_push" in out["scope"]


def test_an_unreachable_ledger_is_UNKNOWN_and_says_it_is_not_a_pass(robot, repo, monkeypatch):
    """⛔⛔ ABSENCE IS NEVER SUCCESS, ON THE ONE SURFACE THAT HAS PRODUCED THREE FALSE GREENS.
    `preflight` previously had NO ledger dependency, so a silent None here would read as "nothing
    to report" — which is exactly how the first two false greens were read."""
    from core import engine as engine_mod

    def boom(*a, **k):
        raise engine_mod.ledger_client.LedgerUnreachable("connection refused")
    monkeypatch.setattr(engine_mod.ledger_client, "inventory", boom)
    monkeypatch.setattr(engine_mod.ledger_client, "admission_for", lambda action: ["x"])
    out = robot._admission_at_tip("a" * 40)
    assert out["state"] == "UNKNOWN"
    assert out["would_push_be_allowed_at_this_tip"] is None, (
        "an unreachable ledger produced a boolean — True or False both claim knowledge here")
    assert "NOT a pass" in out["note"]


def test_the_scope_constant_now_points_at_the_new_field(robot):
    """⚠ The disclosure and the mechanism must move together. If the constant still said preflight
    does not consult admission, it would be false the moment the field shipped."""
    scope = engine.PREFLIGHT_SCOPE
    assert "admission_at_tip" in scope, "the disclosure does not name where the answer now lives"
    assert "`passed` PRICES THE GATE PIPELINE ONLY" in scope, (
        "the disclosure no longer scopes `passed`, which is still gate-pipeline-only")
    # ⛔ the tip-vs-range half is NOT fixed by this change and must still be stated
    assert "TIP-SCOPED" in scope and "can_push" in scope
