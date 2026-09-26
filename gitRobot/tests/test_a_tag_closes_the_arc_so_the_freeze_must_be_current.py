"""A tag may not be cut while the freeze is excusing pin drift.

⭐⭐ Tim ruled 2026-09-26 that the convergence freeze belongs at the ends of arcs. The guard that
ruling owes — the ZeroParadox session's phrasing — is that **an arc must not be able to CLOSE
without its freeze being re-taken.** A tag is the one arc-close event this server can observe, so
this is where the ruling becomes enforced instead of asserted.

⛔⛔ AND WHAT THIS IS NOT, BECAUSE THE TEMPTATION IS RIGHT THERE. Measured 2026-09-26:
`inventory()` is called with `"push"` and with no other action anywhere in this codebase, so
gitRobot has NEVER enforced the 23-step `tag` admission set. The consumer's own workflow document
says so in terms — *"The gate cannot hook `gh release create` (no git event for tag creation), so
enforcement is procedural."* Turning that on is a much larger decision than the freeze guard that
was authorised, so this guard reads ONE field and blocks on ONE condition.

⚠ THE CONSEQUENCE FOR THE DAY'S ARGUMENT, since it reframes it: `copy_editor.actions: ["tag"]`
was therefore enforced by NOTHING. Widening it to `["push","tag"]` did not move a gate from late
to early — it made the panel binding for the first time, and the unsatisfiable-inputs argument,
while true, was beside the operative point.
"""

import textwrap

import pytest

from core.errors import RefusalError


@pytest.fixture
def freeze(monkeypatch):
    """Control what `policy()` reports, since the guard reads exactly one field of it."""
    from core import engine as engine_mod

    def _set(bar):
        monkeypatch.setattr(engine_mod.ledger_client, "call",
                            lambda tool, args: {"bar": bar} if tool == "policy" else {})
    return _set


def _bar(active, **over):
    bar = {"basis": "rule_digest", "frozen": True, "held": True,
           "rule_digest": "r" * 64, "scope_digest": "s" * 64,
           "pin_exemption": {"active": active,
                             "scope_digest_frozen_at": "s" * 64,
                             "scope_digest_now": ("t" * 64) if active else ("s" * 64),
                             "what_it_excuses": "a pin substitution (approved_modules)",
                             "bounded_by": "THE ARC'S END, WHICH THIS SERVER CANNOT OBSERVE."}}
    bar.update(over)
    return bar


# -- ⭐⭐ the guard ------------------------------------------------------------

def test_a_tag_is_refused_while_a_pin_exemption_is_active(robot, repo, freeze):
    """⭐⭐ THE HEADLINE. The bar is GREEN — that is the point. It is green only because pin
    drift is being excused, and a tag closes the arc that the excuse was scoped to."""
    freeze(_bar(True))
    with pytest.raises(RefusalError) as exc:
        robot.tag_create("v9.9", reason="cutting a release")
    msg = str(exc.value)
    assert "pin substitution is being excused" in msg
    # ⚠ a refusal names the success condition, not just the failure
    assert "frozen_rule_digest" in msg and "frozen_scope_digest" in msg
    # ⛔ AND IT NAMES ITS OWN BLIND SPOT. An arc that closes without a release is not covered,
    # and a guard that implies otherwise is a control testing a proxy for the property.
    assert "without a release is not covered" in msg


def test_a_tag_goes_through_when_the_freeze_is_current(robot, repo, freeze):
    """⛔⛔ THE CONTROL. Without it, every assertion above is satisfied by a guard that refuses
    every tag unconditionally — which reads identically in the failing direction."""
    freeze(_bar(False))
    out = robot.tag_create("v9.8", reason="freeze is current")
    assert out["decision"] == "allowed", out


def test_a_freeze_with_no_exemption_block_at_all_goes_through(robot, repo, freeze):
    """⚠ The block renders only when both values are frozen, so its ABSENCE is the ordinary
    state and must not be read as an active exemption. Absence-is-never-success cuts the other
    way here: the claim being made is 'an exemption is active', and nothing supports it."""
    freeze({"basis": "scope_digest", "frozen": True, "held": True})
    assert robot.tag_create("v9.7", reason="no exemption block")["decision"] == "allowed"


# -- ⛔ the direction of the failure ------------------------------------------

def test_an_unreadable_freeze_blocks_the_tag(robot, repo, monkeypatch):
    """⛔⛔ ABSENCE IS NEVER SUCCESS, AND THIS IS A REAL NEW DEPENDENCY FOR `tag_create`, WHICH
    HAD NONE. A tag is a permanent public marker that mints a DOI, so "I could not check the
    freeze" must never render as "the freeze is current".

    ⚠ The cost is stated rather than hidden: an unreachable ledger now blocks a tag where
    previously it could not affect one. That is the correct direction for an irreversible public
    act, and it is the direction this repo's §"absence is never success" requires.
    """
    from core import engine as engine_mod

    def boom(tool, args):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(engine_mod.ledger_client, "call", boom)

    with pytest.raises(RefusalError) as exc:
        robot.tag_create("v9.6", reason="ledger is down")
    msg = str(exc.value)
    assert "could not be read" in msg and "connection refused" in msg
    assert "blocks rather than passes" in msg


def test_the_guard_runs_before_git_is_touched(robot, repo, freeze, monkeypatch):
    """⚠ A REFUSAL AFTER THE TAG EXISTS IS NOT A REFUSAL. There is no tag deletion verb here by
    design, so a guard that fired after `git tag -a` would leave the object it was meant to
    prevent and no way to remove it."""
    freeze(_bar(True))
    calls = []
    real = robot.git.run
    monkeypatch.setattr(robot.git, "run", lambda a, **k: calls.append(a) or real(a, **k))
    with pytest.raises(RefusalError):
        robot.tag_create("v9.5", reason="must not reach git")
    assert not any(a and a[0] == "tag" for a in calls), (
        f"git tag ran despite the refusal: {calls}")


# -- ⚠ the finding that scopes this guard -------------------------------------

def test_this_guard_does_not_start_enforcing_the_tag_admission_set():
    """⛔⛔ PINS THE SCOPE OF THE CHANGE, because the adjacent hole is large and inviting.
    gitRobot consults `inventory()` for `"push"` only; the `tag` admission set — 23 steps — is
    enforced by nothing here, and the consumer's workflow documents tag enforcement as
    PROCEDURAL. Whether to change that is a decision of its own, and this test fails if the
    freeze guard quietly grows into it.

    ⚠ Asserted over the SOURCE rather than by behaviour, because the property is "this function
    does not consult the admission set" — a behavioural probe would pass just as well against a
    version that consulted it and happened to find it satisfied.

    ⛔⛔ AND THE DOCSTRING IS STRIPPED FIRST, BECAUSE THE FIRST VERSION OF THIS TEST FAILED ON THE
    PROSE THAT EXPLAINS THE RULE. The guard's docstring necessarily says the words "inventory"
    and "admission set" — that is where the measurement justifying the scope lives — so a scan
    over the whole source counted the explanation as the violation. That is `DC-51` exactly, a
    detector counting prose about the marker, and it is the second time this arc I have written
    it: the earlier one nearly reported 52 of 57 filenames as defects for the same reason.
    **A source-scanning control must scan CODE, and the docstring is not code.**
    """
    import ast
    import inspect
    from core import engine
    src = inspect.getsource(engine.GitRobot._require_current_freeze)
    tree = ast.parse(textwrap.dedent(src))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body = fn.body[1:]          # drop the docstring, keep every statement
    assert fn.body, "the guard has no body left to check — the strip removed too much"
    src = ast.unparse(fn)
    assert "inventory" not in src, (
        "the freeze guard now pulls an inventory — it was scoped to read `policy().bar` so it "
        "could not become tag admission gating by accident, and so it would not pay for the "
        "range walk that made a push look like it hung")
    assert "admission" not in src.replace("admission set", ""), (
        "the freeze guard now consults an admission set; that is a separate, larger decision")
