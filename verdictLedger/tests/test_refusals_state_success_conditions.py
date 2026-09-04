"""Every refusal says what a PASSING next attempt looks like, not only what went wrong.

⭐⭐ TIM, 2026-09-04: *"why wouldn't you want to call out exactly what the success conditions are?
It's like a teacher grading homework. **The next iteration is already going to be on a different
blob.**"*

That is content-keying applied to refusals. A refusal phrased as a fact about the CURRENT bytes is
stale the moment the caller acts on it — they come back with different content and everything the
message said no longer applies. **The success condition is the only part that survives the change**,
which is the same reason a verdict binds to `(step, path, blob)` rather than to a basis.

⚠⚠ CALIBRATED ON TWO REAL FAILURES FROM THE SIBLING SERVER, 2026-09-03:

    "gate_round.json IS STAGED"                  a state fact, and false in the ordinary case
    "reset it to 0 and commit that"              an instruction — and the action that ERASED
                                                 the record of a walked cap

Neither says what a correct next submission contains. Both describe the attempt that just failed.
The rewrite — *"the tracked copy must carry round 0, cleared via `gate_round.py reset` so
`reset_from` survives"* — is true regardless of the file's current state, and could never have told
anyone to hand-write a zero.

⛔⛔ WHAT THIS FILE CANNOT DO, STATED PLAINLY BECAUSE THE OPPOSITE MISTAKE WAS MADE TWICE TODAY.
**A required field is satisfiable vacuously.** ZeroParadox shipped two controls this session that
could not fail — the second a probe whose three populations were all equal, so it could never
separate the columns it was labelling. It was present, it was green, and it tested nothing.

**A check that `satisfied_when` is PRESENT will pass over conditions that each merely paraphrase
their own `what`.** So presence is necessary and nowhere near sufficient, and the property that
matters is one only a reader can judge:

    Can a reader construct a passing next submission from `satisfied_when` ALONE,
    with `what` deleted?

That question was run by hand over every site here. The mechanical part below stops the field being
DROPPED; it does not and cannot stop it being filled badly.
"""

import ast
import pathlib

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "core").glob("*.py")) + sorted((ROOT / "ledger_server").glob("*.py"))


def _usage_error_calls():
    """Every `UsageError(...)` construction in the package, with its file and line."""
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "UsageError"):
                yield path.relative_to(ROOT), node


def test_every_refusal_carries_a_success_condition():
    """⭐ THE MECHANICAL HALF: the field cannot be dropped. `UsageError.__init__` takes
    `satisfied_when` with NO DEFAULT, so an omission is a TypeError at the raise site — the same
    property gitRobot's `_refuse` already has via a required positional.

    ⚠ This walks every site rather than trusting the signature, because a site could still pass
    `None` or an empty string and satisfy the interpreter while saying nothing."""
    thin = []
    for rel, node in _usage_error_calls():
        if len(node.args) < 2:
            thin.append(f"{rel}:{node.lineno} — no success condition")
            continue
        cond = node.args[1]
        # a literal we can inspect; f-strings and concatenations are checked for non-emptiness
        text = ""
        for sub in ast.walk(cond):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                text += sub.value
        if len(text.strip()) < 40:
            thin.append(f"{rel}:{node.lineno} — condition is {len(text.strip())} chars, too "
                        f"thin to build a next attempt from")
    assert not thin, (
        "refusal sites without a usable success condition:\n  " + "\n  ".join(thin))


def test_a_refusal_renders_both_halves_separately():
    """⚠⚠ TWO CLAIMS, TWO FIELDS — the same separation `subjects` and `failing` needed, for the
    same reason: sharing one slot lets a description of the failure pass for guidance.

    `what` is perishable (about these bytes); `satisfied_when` is blob-independent. A caller must
    be able to read the second without the first."""
    from core.errors import UsageError

    err = UsageError("the index copy carries round=7", "the tracked copy must carry round 0")
    assert err.what == "the index copy carries round=7"
    assert err.satisfied_when == "the tracked copy must carry round 0"
    assert "SATISFIED WHEN:" in str(err), "the two halves must be distinguishable in the message"


def test_omitting_the_condition_is_a_type_error_not_a_default():
    """⚠ NO DEFAULT, ON PURPOSE. A default makes omission the quiet path, and the quiet path was
    taken at twelve sites here before this landed. Absence must be impossible, not discouraged."""
    from core.errors import UsageError

    with pytest.raises(TypeError):
        UsageError("something went wrong")          # type: ignore[call-arg]


def test_the_find_condition_is_derived_from_the_authority_not_restated():
    """⭐⭐ DERIVE, NEVER RESTATE. A condition that copies its values from somewhere else is prose,
    and prose goes stale exactly as the `reason` field does. `find`'s refusal names the members of
    `schema.VERDICTS` — the same constant the validator enforces — so the message cannot drift
    from what is actually storable.

    ⚠ This test fails if someone adds a verdict and hand-maintains the message instead."""
    from core import schema
    from core.errors import UsageError
    from core.ledger import Ledger

    led = Ledger(pathlib.Path(__file__).parent / "_nonexistent.jsonl")
    try:
        led.find(verdict="definitely-not-a-verdict")
    except UsageError as exc:
        for v in schema.VERDICTS:
            assert v in exc.satisfied_when, (
                f"{v!r} is storable but the refusal does not offer it — the message has drifted "
                f"from schema.VERDICTS")
    else:
        pytest.fail("an unrecognised verdict must refuse")
