"""`status.in_flight` — is my job still running, or is it wedged?

⭐⭐ Tim, 2026-09-21, after watching the ZeroParadox session conclude twice that a LIVE
preflight was dead: *"Is that the kind of thing that might actually make sense to make into a
dedicated MCP endpoint? A way to be able to check in and make sure that our jobs are done?"* —
then ruled EXTEND rather than mint, so the facts land on the status a caller already reads.

⛔⛔ THE FAILURE THIS REPLACES IS A FALSE NEGATIVE, TWICE, SAME READER, NINETEEN DAYS APART.
2026-09-02 and 2026-09-21: `Get-Process` filtered to python/lean/lake returned zero matches and
`running` was read as a stale lock over a dead run. Both times the pipeline was alive; the
second time it finished normally FOUR MINUTES after being declared dead, in 15.5 minutes total.
The work is a THREAD inside the gitRobot process, so process enumeration answers a different
question and its zero is indistinguishable from a real absence — a careful operator measures six
times and concludes wrongly with full rigour.

⚠⚠ SO THE DESIGN CONSTRAINT IS ASYMMETRIC, AND EVERY TEST BELOW IS SHAPED BY IT. A `stuck` that
fired early would have CONFIRMED that wrong conclusion in an authoritative-looking field, which
is strictly worse than the silence it replaces. It must be hard to trip and obvious when it
trips — so the tests spend most of their weight on the cases where it must stay FALSE.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from core import engine as engine_mod
from core import gates as gates_mod


PREFLIGHT_CAP = gates_mod.PHASE_TIMEOUT["pre-push"]      # 1800 — ONE gate phase
PUSH_CAP = engine_mod.PUSH_TIMEOUT                        # 3600 — the whole git subprocess


def _ago(seconds):
    """An ISO-8601 stamp `seconds` in the past, UTC with an explicit offset.

    ⚠ THE OFFSET IS THE POINT. Every stamp this fleet writes ends `+00:00`, and a fixture that
    produced naive stamps would be testing a shape the server never sees — while quietly
    exercising the one branch that refuses to guess.
    """
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def flight(robot, monkeypatch):
    """Drive `in_flight` by replacing what the DELEGATES answer.

    ⭐ This is also the delegation test's instrument: if `in_flight` re-derived state from the
    audit rows instead of calling `preflight_status()`/`push_status()`, none of these fixtures
    would reach it and every assertion below would read the real (empty) store.
    """
    def _set(preflight=None, push=None):
        monkeypatch.setattr(robot, "preflight_status",
                            lambda: dict(preflight or {"state": "none"}))
        monkeypatch.setattr(robot, "push_status",
                            lambda: dict(push or {"state": "none"}))
        return robot.in_flight()
    return _set


# -- the field exists, on the status a caller already reads -------------------

def test_status_carries_the_check_in(robot, repo, ledger_ok):
    """⚠ On `status`, not behind a tool a caller must know to ask for — Tim's ruling."""
    answer = robot.status()
    assert "in_flight" in answer, "the check-in is absent from the surface it was put on"
    assert set(answer["in_flight"]) >= {"preflight", "push"}
    for kind in ("preflight", "push"):
        row = answer["in_flight"][kind]
        assert row["state"] == "none", "a fresh store has started nothing"
        assert row["stuck"] is False
        assert row["detail_via"] == f"{kind}_status()", (
            "the row must name where the transcript lives, since it does not carry one")


def test_the_rows_are_delegated_and_not_re_derived(flight):
    """⛔⛔ THE STATE MACHINES LIVE IN `preflight_status`/`push_status` AND MUST STAY THERE.

    Six states and five, with `orphaned` vs `died` and the push's "may already have published"
    all encoded in them. A second reader of the same audit rows would be a second copy of that
    logic, and the copy is the one that goes wrong: this repo already measured `status`
    surfacing `19/19` beside a broken convergence bar because it embedded one fact and
    re-derived another.

    ⚠ The fixture answers with a state NO audit store could produce, so a re-deriving
    implementation cannot coincidentally agree.
    """
    out = flight(preflight={"state": "orphaned", "run_id": "deadbeef",
                            "started_at": _ago(10)},
                 push={"state": "died", "run_id": "cafe1234", "started_at": _ago(20)})
    assert out["preflight"]["state"] == "orphaned"
    assert out["preflight"]["run_id"] == "deadbeef"
    assert out["push"]["state"] == "died"
    assert out["push"]["run_id"] == "cafe1234"


# -- `stuck` must stay FALSE, which is most of the job ------------------------

def test_a_running_job_inside_its_budget_is_not_stuck(flight):
    """⭐ THE 2026-09-21 RUN ITSELF: alive, unobservable by process enumeration, and fine.

    15.5 minutes (930s) against a 1800s cap. Declared dead by a reader four minutes before it
    finished; this field must not agree with that reader.
    """
    out = flight(preflight={"state": "running", "run_id": "r1", "started_at": _ago(930)})
    row = out["preflight"]
    assert row["stuck"] is False, "called a live, in-budget run wedged"
    assert row["elapsed_seconds"] >= 929
    assert "note" not in row, "a healthy running row needs no alarm text"


def test_a_concluded_run_is_never_stuck_however_old(flight):
    """⛔ THE 'NO TERMINAL ROW' HALF OF THE DEFINITION, and the one an elapsed-only rule breaks.

    A preflight that passed a week ago has an elapsed time far past any cap. If `stuck` were
    `elapsed > cap` alone, every store with an old run in it would report wedged forever —
    an alarm that is always on is an alarm nobody reads.
    """
    for state in ("passed", "failed", "none"):
        out = flight(preflight={"state": state, "run_id": "old", "started_at": _ago(604800)})
        assert out["preflight"]["stuck"] is False, f"{state!r} read as stuck"


def test_a_dead_run_is_reported_dead_and_not_stuck(flight):
    """⚠ `died` AND `orphaned` HAVE NO TERMINAL ROW EITHER, AND THEY ARE STILL NOT STUCK.

    They are CONCLUDED: nothing is executing and nothing will change on its own. `stuck` is a
    claim about a run still asserting it is working, and the remedies differ — a stuck push
    must not be restarted before asking the remote, an orphaned preflight simply re-runs. One
    field for both would tell a caller to do SOMETHING while refusing to say what.
    """
    out = flight(preflight={"state": "orphaned", "run_id": "o", "started_at": _ago(99999)},
                 push={"state": "died", "run_id": "d", "started_at": _ago(99999)})
    assert out["preflight"]["stuck"] is False and out["preflight"]["state"] == "orphaned"
    assert out["push"]["stuck"] is False and out["push"]["state"] == "died"


def test_an_unreadable_age_says_so_instead_of_reporting_calm(flight):
    """⛔⛔ ABSENCE IS NEVER SUCCESS. A run whose age cannot be established is not `stuck`, and
    a reader must not take that `false` for "checked and fine" — so the row says which.

    ⚠ A NAIVE TIMESTAMP IS REFUSED RATHER THAN GUESSED. Reading it as local would produce an
    `elapsed` wrong by the offset — five to six hours on this machine — and a `stuck` silently
    derived from it. This fleet writes nothing naive; if one appears, unknown is the true answer.
    """
    for bad in (None, "", "not-a-timestamp", "2026-09-21T12:00:00"):   # last one: no offset
        out = flight(preflight={"state": "running", "run_id": "x", "started_at": bad})
        row = out["preflight"]
        assert row["elapsed_seconds"] is None, f"{bad!r} produced an age"
        assert row["stuck"] is False
        assert "for want of evidence" in row.get("note", ""), (
            f"{bad!r}: a false `stuck` was left to read as a clean bill of health")


# -- `stuck` must go TRUE when it should, against the RIGHT cap ---------------

def test_a_running_job_past_its_cap_is_stuck_and_says_what_to_do(flight):
    out = flight(preflight={"state": "running", "run_id": "r", "started_at": _ago(PREFLIGHT_CAP + 60)})
    row = out["preflight"]
    assert row["stuck"] is True
    assert "NO TERMINAL ROW" in row["note"]
    # ⚠ A refusal names the success condition; an alarm names the next action.
    assert "preflight_status()" in row["note"], "the alarm must say where the evidence is"


def test_the_push_is_priced_against_its_own_cap_not_the_gate_phase(flight):
    """⛔⛔ THE FACTOR-OF-TWO TRAP, AND IT IS THE OBVIOUS GUESS.

    `PHASE_TIMEOUT['pre-push']` is 1800 and bounds ONE PHASE of the hook running INSIDE the
    `git push` subprocess. `PUSH_TIMEOUT` is 3600 and bounds the whole thing, hook and network
    together. A `stuck` computed against 1800 would call a legitimately-running push wedged at
    the 31-minute mark — a true elapsed time read against the wrong ceiling, in the one state
    where the caller is already anxious and primed to believe it.

    ⚠ The gap between the two caps is exactly where this test lives: 2400s is past the gate
    phase budget and well inside the push's.
    """
    assert PUSH_CAP > PREFLIGHT_CAP, "fixture: the caps must differ or this proves nothing"
    between = (PREFLIGHT_CAP + PUSH_CAP) // 2      # 2700 — past 1800, inside 3600

    out = flight(preflight={"state": "running", "run_id": "p", "started_at": _ago(between)},
                 push={"state": "running", "run_id": "q", "started_at": _ago(between)})

    assert out["preflight"]["stuck"] is True, "the preflight IS past its 1800s phase budget"
    assert out["push"]["stuck"] is False, (
        "a push inside its 3600s budget was called wedged — the gate-phase cap was applied "
        "to the wrong object")
    assert out["push"]["cap_seconds"] == PUSH_CAP
    assert out["preflight"]["cap_seconds"] == PREFLIGHT_CAP


def test_every_row_names_what_its_cap_prices(flight):
    """⚠ NEVER A NUMBER WITHOUT ITS OBJECT. Two caps on one response, differing by 2x, is
    exactly the shape that gets read as one number — so each row carries `cap_prices`."""
    out = flight(preflight={"state": "running", "started_at": _ago(5)},
                 push={"state": "running", "started_at": _ago(5)})
    assert "gate phase" in out["preflight"]["cap_prices"].lower()
    assert "subprocess" in out["push"]["cap_prices"].lower()
    assert "1800" in out["push"]["cap_prices"], (
        "the push row must warn off the gate-phase number, which is the wrong guess")


def test_the_cap_is_the_one_the_push_actually_runs_under(repo):
    """⛔ ONE OBJECT, NOT TWO COPIES. `status` quotes `PUSH_TIMEOUT` and `_do_push` passes it.
    A quoted cap that had been copied would be free to drift from the one holding the knife,
    and a caller would compare an elapsed time against a ceiling nothing enforces.

    ⚠ Read out of the SOURCE rather than asserted in prose: the guard has to fail if someone
    re-inlines the literal.
    """
    src = (engine_mod.__file__ or "")
    text = open(src, encoding="utf-8").read()
    assert "timeout=PUSH_TIMEOUT" in text, (
        "_do_push no longer passes the published constant, so the cap `status` quotes and the "
        "cap git runs under are now two objects")


# -- the surface must not go quiet when it cannot answer ----------------------

def test_an_unreadable_flight_state_renders_as_its_own_state(robot, repo, ledger_ok,
                                                             monkeypatch):
    """⛔⛔ AN OMITTED BLOCK READS AS 'NOTHING IS RUNNING'. `status` is the check-in surface, so
    swallowing the error would be absence rendering as success — the bug this repo names first —
    and it would do it in the field built to answer "is my job still going".

    ⚠ It is reported rather than raised because the branch, the tree and the blockers in the
    same answer are still true; losing them to an unreadable audit is the wrong trade.
    """
    def boom():
        raise OSError("audit log is not readable")
    monkeypatch.setattr(robot, "in_flight", boom)

    answer = robot.status()
    assert answer["branch"], "the rest of the status was lost to one unreadable field"
    block = answer["in_flight"]
    assert "error" in block and "audit log is not readable" in block["error"]
    assert "Do not read it as idle" in block["note"]
    assert "preflight" not in block, (
        "an empty row beside the error would read as a measured 'nothing running'")


# -- the delegate had to publish the fact before status could consume it ------

def test_push_status_publishes_when_a_running_push_started(robot, repo, monkeypatch):
    """⭐ WITHOUT THIS, `running` READ THE SAME AT 30 SECONDS AND AT 40 MINUTES.

    `preflight_status` has published `started_at` on every non-terminal state since it was
    written; `push_status` published none, so the state where elapsed time IS the question was
    the one state a caller could not date. `status` consumes the delegate's fact rather than
    re-deriving it from the audit, so the gap had to be closed here first.

    ⚠ `ts` IS NOT REUSED FOR IT. `ts` is when a run CONCLUDED and rides the terminal states;
    a start stamp and a finish stamp sharing one key is the WHEN-vs-WHOSE collapse in miniature.
    """
    import threading

    robot.audit.append(actor=robot.actor, op="push", decision="started", head="0" * 40,
                       run_id="rid1", args={"branch": "illustrated"}, repo=str(robot.repo))

    # a thread wearing the worker's name, so the liveness probe finds it and reports `running`
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait, name="push-rid1", daemon=True)
    worker.start()
    try:
        answer = robot.push_status()
        assert answer["state"] == "running"
        assert answer.get("started_at"), "a running push still cannot be dated"
        assert "ts" not in answer, "the start stamp must not arrive wearing the finish key"
        assert answer.get("cap_seconds") == PUSH_CAP
    finally:
        stop.set()
        worker.join(timeout=5)
