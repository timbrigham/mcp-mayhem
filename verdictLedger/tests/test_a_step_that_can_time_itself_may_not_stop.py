"""V22 — a save does not complete without a wall clock, ratcheted per step.

⭐⭐ Tim's ruling 2026-09-26: *"Let me make the cost a mandatory field in order to, for the save
to be completed correctly."* And on the other half: *"I don't think that the actual US dollars
cost is of particular use or honestly something that's all of that measurable… I would think
that the wall clock time would be a hell of a lot more interesting."*

⚠⚠ THE MEASUREMENT THAT SHAPED THE RULE, taken before a line was written. Across 5,940 live
records there are exactly THREE distinct `cost` shapes and **not one populated value in any
of them**:

    5928   {"seconds": null, "usd": 0.0}
       9   {"lock_wait_seconds": null, "seconds": null, "usd": 0.0}
       3   {"seconds": null, "usd": 0}

The field was present on every record for the life of the stream and measured nothing. That is
worse than an absent field: a present empty one reads as "measured, and it was nothing", which
is why the one question anyone asked of it — what does a panel run cost — was unanswerable in
either direction.

⛔⛔ WHY IT IS A PER-STEP RATCHET AND NOT A REQUIREMENT. All ~22 emit call sites in the consumer
route through ONE function in a repository this server cannot touch. A flat requirement refuses
every append from ~30 GATING steps at once, every step reads MISSING, and no push is possible
until another repo changes. **A rule that locks the fleet in order to acquire a field is a rule
that gets switched off.** So the obligation is earned: a step that has PROVED it can report a
wall clock may never stop; a step that never has is untouched.

⚠ THE CONTROL BELOW IS THE DELIVERABLE. Without `test_a_step_that_never_timed_itself_is_left
_alone`, every assertion here is satisfied by a rule that simply requires `seconds` from
everyone — which is the outage this design exists to avoid, passing as the design.
"""

import pytest

from conftest import good
from core import validate as validate_mod


STEP = "check_invariants"
# ⚠ THE NEIGHBOUR IS PICKED FOR TWO REASONS AND BOTH COST A RED RUN TO LEARN.
# `check_paths` declares `switches`, so a generic record for it trips V15; `agent_gate` is
# in the LIVE registry but not in `required.v2.sample.json`, which is what the fixtures
# copy, so it trips V8. `decls` is declaration-free AND in the sample — so a red result
# here can only mean V22 leaked across steps, which is the only thing this probe is for.
OTHER = "decls"


def errs(ledger, record):
    return ledger.validate(record)["errors"]


def v22(ledger, record):
    """Assert V22 fired, and report what DID fire when it did not."""
    found = errs(ledger, record)
    assert any(e.startswith("V22") for e in found), f"V22 did not fire; got {found}"
    return found


def timed(**over):
    """A record that reports a wall clock — what a converted emitter produces."""
    cost = {"seconds": 12.5, "seconds_prices": "emitter import to record emission"}
    cost.update(over.pop("cost", {}))
    return good(cost=cost, **over)


def untimed(**over):
    """A record with the shape every emitter produces TODAY: cost present, empty."""
    cost = {"seconds": None, "seconds_prices": None, "usd": None}
    cost.update(over.pop("cost", {}))
    return good(cost=cost, **over)


# -- ⭐⭐ the ratchet ----------------------------------------------------------

def test_a_step_that_has_timed_itself_may_not_go_back(ledger):
    """⭐⭐ THE HEADLINE. Once a step reports a wall clock, a later record for that step
    without one is refused — a step that CAN measure itself and stops is indistinguishable
    from one that never could."""
    ledger.append(timed())                                  # the step converts
    assert STEP in ledger.store.steps_timing()

    found = v22(ledger, untimed(basis={"kind": "tree", "value": "d" * 40,
                                       "resolved_from": "explicit"}))
    joined = " ".join(found)
    assert "already reported" in joined
    # ⚠ the refusal must name the success condition, not merely the failure
    assert "cost.seconds" in joined and "cost.seconds_prices" in joined
    # ⛔ and it must NOT name a function, flag or helper in the caller's repo — the V9 lesson,
    # where a remedy that did not exist for the checker in hand cost a whole preflight cycle.
    for foreign in ("emit_verdict", "common.py", "record.py", "--record", "batch.py"):
        assert foreign not in joined, (
            f"the refusal names {foreign!r}, which is a claim about a caller this server "
            f"cannot see — exactly the defect V9's message was rewritten to remove")


def test_a_step_that_never_timed_itself_is_left_alone(ledger):
    """⛔⛔ THE CONTROL, AND THE WHOLE REASON THIS IS A RATCHET. Without it every assertion in
    this file is satisfied by a rule requiring `seconds` from everyone — which refuses ~30
    gating steps at once and locks the push. The absence of an obligation is the feature."""
    assert ledger.store.steps_timing() == set()
    assert errs(ledger, untimed()) == [], (
        "a step that has never reported a wall clock was refused — this is the flag-day "
        "outage the per-step ratchet exists to prevent")


def test_the_ratchet_does_not_leak_to_another_step(ledger):
    """⚠ One step converting must not oblige its neighbours."""
    ledger.append(timed())
    assert ledger.store.steps_timing() == {STEP}
    other = untimed(step=OTHER,
                    evidence=[{"git_blob_id": "c" * 40,
                               "path": "tools/verify/%s.py" % OTHER}])
    assert errs(ledger, other) == [], (
        "one step reporting a wall clock obliged a different step — the ratchet is per-step")


# -- ⚠ the number must be readable, ratchet or not ----------------------------

@pytest.mark.parametrize("value", ["12.4s", "12.4", True, [12.4], {"s": 12.4}])
def test_a_duration_that_must_be_parsed_is_refused(ledger, value):
    """⚠ A string "12.4s" would have passed before this rule. A duration two readers parse
    differently is not a measurement. `True` is in the list because `isinstance(True, int)`
    is True in Python, so a bare numeric check accepts a boolean as a duration."""
    v22(ledger, good(cost={"seconds": value, "seconds_prices": "x"}))


def test_a_negative_elapsed_names_the_wrong_origin(ledger):
    """⚠ A negative duration is the clock read against the wrong origin — the usual cause is
    subtracting a start captured in a different process, which is exactly the in-process-import
    hazard the message warns about."""
    found = v22(ledger, good(cost={"seconds": -3.0, "seconds_prices": "x"}))
    assert "wrong origin" in " ".join(found)


def test_zero_is_a_legitimate_duration(ledger):
    """⛔ 0.0 IS A MEASUREMENT AND MUST NOT BE REFUSED. A checker that finishes inside the
    clock's resolution honestly reports 0.0; refusing it would teach emitters to round up, and
    a fabricated floor is worse than a true zero."""
    assert errs(ledger, good(cost={"seconds": 0.0, "seconds_prices": "step main"})) == []


# -- ⛔ a number without its object is the founding defect ---------------------

@pytest.mark.parametrize("prices", [None, "", "   "])
def test_a_wall_clock_must_say_what_it_prices(ledger, prices):
    """⛔⛔ THE SAME ELAPSED TIME IS THREE DIFFERENT FACTS. From an emitter module's import it
    is a LOWER BOUND on the step; around the step's entry point it is the step; across a
    process that ran two steps it is neither and reads as a step duration while pricing a
    process. Not hypothetical: the consumer's `batch.py` runs each checker as a SUBPROCESS,
    while `guards.py` and `move_ridealong.py` import `check_*` modules IN-PROCESS."""
    found = v22(ledger, good(cost={"seconds": 4.0, "seconds_prices": prices}))
    assert "what it prices" in " ".join(found)


def test_seconds_prices_is_not_demanded_when_there_is_no_number(ledger):
    """⚠ The obligation attaches to the NUMBER, not to the field's existence. Demanding a
    `prices` string from a record carrying no duration would refuse every unconverted step,
    which is the flag day again by a side door."""
    assert errs(ledger, untimed()) == []


# -- ⚠ usd stays optional, and absent is not zero ------------------------------

def test_usd_is_never_required(ledger):
    """⛔⛔ REQUIRING IT WOULD FORCE 30 CHECKERS TO ASSERT A 0.0 NONE OF THEM CAN CLAIM. Of
    ~31 registered steps exactly one (`agent_gate`) invokes a model and can read a real
    `total_cost_usd`; the rest are mechanical and cannot spend. That is Tim's point in the
    ruling, and it is the reason `seconds` is the mandatory half."""
    assert errs(ledger, good(cost={"seconds": 1.0, "seconds_prices": "x"})) == []


def test_zero_dollars_is_allowed_because_it_can_be_measured(ledger):
    """⚠ An emitter that genuinely reads a cost of nothing may say so. The defect was never
    the value 0.0 — it was 0.0 arriving as a DEFAULT, where it claimed a measurement nobody
    took."""
    assert errs(ledger, good(cost={"seconds": 1.0, "seconds_prices": "x", "usd": 0.0})) == []


@pytest.mark.parametrize("value", [-0.01, "3.00", True])
def test_an_unreadable_spend_is_refused(ledger, value):
    found = v22(ledger, good(cost={"seconds": 1.0, "seconds_prices": "x", "usd": value}))
    assert "ABSENT AND ZERO ARE DIFFERENT CLAIMS" in " ".join(found)


def test_the_default_record_no_longer_claims_a_spend_of_zero(ledger):
    """⛔⛔ THE LIVE DEFECT THIS RULING EXPOSED. `schema.empty_record()` defaulted `usd` to 0.0, so a
    step that spent real money and did not report it and a step that CANNOT spend rendered as
    the same bytes — 5,928 of 5,940 records, byte-identically. An absent measurement wearing
    the costume of a figure."""
    from core import schema
    assert schema.empty_record()["cost"]["usd"] is None, (
        "the default asserts a measured spend of zero on every record that never measured one")
    assert schema.empty_record()["cost"]["seconds"] is None
    assert "seconds_prices" in schema.empty_record()["cost"], (
        "a number is defaulted without the field that says what it prices")


# -- ⛔⛔ the wiring, which no other test in this file can see ------------------

def test_the_ledger_actually_passes_the_ratchet_index(ledger, monkeypatch):
    """⛔⛔ THE ONE CONTROL THAT CANNOT BE WRITTEN AS A RECORD PROBE, AND THE RULE WOULD DIE
    SILENTLY WITHOUT IT. `timed_steps=None` is indistinguishable from "no step has ever
    reported", so if `ledger.py` ever stops passing the index, V22's ratchet switches off and
    **every other test in this file keeps passing** — they all go through `Ledger.validate`,
    which would still supply it via its own call.

    ⚠ So this asserts the KWARG ARRIVES, by intercepting `rules` and reading what it was
    handed. Asserting behaviour here would be asserting a proxy: the behaviour is produced by
    the same call whose wiring is in question.
    """
    seen = {}
    real = validate_mod.rules

    def spy(record, **kw):
        seen.update(kw)
        return real(record, **kw)
    monkeypatch.setattr(validate_mod, "rules", spy)

    ledger.append(timed())
    assert "timed_steps" in seen, (
        "Ledger.validate no longer passes timed_steps — V22's ratchet is disabled and every "
        "other probe in this file still passes, which is why this control exists")
    assert seen["timed_steps"] is not None, (
        "timed_steps arrived as None, which V22 cannot distinguish from 'no step has ever "
        "reported a wall clock' — the rule would be off with nothing to show it")


def test_the_index_reads_the_whole_stream_not_only_the_tip(ledger):
    """⚠ A step converts, then is regraded at a NEW basis without a clock. The ratchet must
    remember the earlier record — `tips` is keyed per basis and would have forgotten it."""
    ledger.append(timed())
    ledger.append(timed(basis={"kind": "tree", "value": "e" * 40,
                               "resolved_from": "explicit"}))
    assert ledger.store.steps_timing() == {STEP}
    v22(ledger, untimed(basis={"kind": "tree", "value": "f" * 40,
                               "resolved_from": "explicit"}))


# -- ⚠ the retired rule this one replaces --------------------------------------

def test_a_duration_cannot_make_a_rerun_look_like_a_conflict(ledger):
    """⭐⭐ V14 EXISTED TO FORBID EXACTLY WHAT V22 NOW REQUIRES, and this pins the reason that
    reversal is safe. `validate.py` still carries the note: V14 (deterministic `reason`) was
    written because `reason` fed a per-record hash, so *"a checker reporting its own duration
    would silently break dedupe."*

    ⛔ The thing that changed is the KEY, not the policy: `schema.payload()` excludes `cost`
    by name as observational. So the same fact re-reported with a different duration dedupes
    instead of colliding at V11. **If cost ever enters the payload, V22 becomes a
    self-inflicted V11 generator** — and this test is what notices.
    """
    from core import schema
    a = timed(cost={"seconds": 1.0, "seconds_prices": "p"})
    b = timed(cost={"seconds": 99.0, "seconds_prices": "p"})
    assert schema.payload(a) == schema.payload(b), (
        "cost is inside the dedupe payload, so two runs of one unchanged step differ only in "
        "their duration and the second is a V11 CONFLICT — V14's hazard, reintroduced by the "
        "rule that replaced it")

    ledger.append(a)
    assert errs(ledger, b) == [], (
        "a re-run of an unchanged step reporting a different duration was refused — check "
        "whether it is V11, which would mean cost reached the payload")


# -- ⛔⛔ the operations on THIS side must be able to satisfy this rule ----------

def test_narrowing_a_fail_carries_the_wall_clock_forward(ledger):
    """⛔⛔ THE DEFECT THE EXISTING SUITE FOUND, AND IT WAS MINE. V22 landed and two tests in
    `test_indictment_is_not_coverage.py` went red — because `Ledger.narrow()` copies subjects,
    evidence, decided and reason and DROPPED `cost`, so the moment a step ratcheted, this
    server's own narrow operation could no longer produce a record this server's own validator
    would accept.

    ⚠⚠ THAT IS THE UNREACHABLE-REMEDY SHAPE, arriving by the route V11's message was rewritten
    to warn about: a rule added without walking the operations that CONSTRUCT records here. The
    refusal would have told a caller to supply `cost.seconds` through an API that has no
    parameter for it.

    ⭐ And carrying it forward is honest rather than merely convenient: a narrow re-emits the
    same examination with its indictment reduced, so the clock that produced it still did.
    Recomputing here would price this server's copy and label it the checker's run.
    """
    fail = ledger.append(timed(verdict="FAIL", failing=["docs/x.md"],
                               reason="one path is bad"))
    out = ledger.narrow(record_id=fail["id"], failing=["docs/x.md"], reason="narrowed")

    got = ledger.store.get(out["id"])
    assert (got.get("cost") or {}).get("seconds") == 12.5, (
        "narrow dropped the wall clock, so a ratcheted step cannot be narrowed on this server")
    assert (got.get("cost") or {}).get("seconds_prices"), (
        "narrow carried a number forward without what it prices")


@pytest.mark.parametrize("how", ["signature", "override"])
def test_a_human_accept_owes_no_wall_clock(ledger, how):
    """⛔⛔ THE SECOND DEFECT, FOUND THE SAME WAY. `Ledger._decided()` builds the record behind
    `sign`, `override` and `accept`. There is no checker, no subprocess and no elapsed anything,
    so the only ways to satisfy a timing requirement would be to fabricate a number or to price
    this server's own write and call it the step's cost — which is precisely what the `usd`
    default was just fixed for, one field over.

    ⚠ NOT A BYPASS, and this asserts the reason: reaching this branch means naming a human
    (V5 for `signature`, V12 for `override`), which is a far larger claim than a missing
    duration. A mechanical emitter cannot take this route to dodge the ratchet.
    """
    ledger.append(timed())                     # the step ratchets
    assert STEP in ledger.store.steps_timing()

    rec = good(cost={"seconds": None, "seconds_prices": None},
               decided={"how": how, "passes": 1, "agreed": 1, "who": "Tim"},
               verdict="PASS",
               basis={"kind": "tree", "value": "9" * 40, "resolved_from": "explicit"})
    found = [e for e in errs(ledger, rec) if e.startswith("V22")]
    assert found == [], (
        "a human %s was required to report a wall clock it has no way to measure: %s"
        % (how, found))


def test_an_agent_round_is_not_exempt(ledger):
    """⛔⛔ THE CONTROL ON THE EXEMPTION, AND WITHOUT IT THE EXEMPTION IS UNBOUNDED. `agreement`
    and `delegated` are agent rounds: they spend real wall clock and real money, which is the
    case this entire field exists for. If the exempt set ever widened to cover them, the one
    step that can actually report a cost would be the one excused from reporting it."""
    ledger.append(timed())
    rec = good(cost={"seconds": None, "seconds_prices": None},
               decided={"how": "delegated", "passes": 1, "agreed": 1, "who": "adversary"},
               basis={"kind": "tree", "value": "8" * 40, "resolved_from": "explicit"})
    assert any(e.startswith("V22") for e in errs(ledger, rec)), (
        "an agent round was excused from reporting a wall clock — it is the case the field is "
        "for, not an exception to it")
