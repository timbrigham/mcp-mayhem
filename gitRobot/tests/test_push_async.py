"""`push` splits the act from the call — because the sanctioned route stopped working.

⭐⭐ MEASURED 2026-08-30, and all three numbers matter:

    MCP client call window        300s
    this method's git timeout     900s   (chosen when the pipeline took ~155s)
    pre-push hook, the BACKSTOP  1498s   (~25 min, runs on EVERY push by design)

**Both ceilings were below the floor**, so raising either alone would have fixed nothing. The
push aborted with "sent no response or progress for 300s", `ls-remote` was unchanged seven
minutes apart, and `history(op='push')` had no entry — it never reached a decision point.

⚠⚠ AND THE CAUSE IS THE PART WORTH KEEPING. The pipeline got slower BECAUSE the routing control
was repaired the same night (`RLY41-1`: it stopped inheriting a red baseline and started
constructing one). **A control made honest became, by the same change, expensive enough that the
compliant path stopped working** — leaving only: raise the timeout, gut the fresh control, or
skip the hook. Nobody decided to cheat; every honest route closed at once. **The cost of a
control is part of the control.**

`preflight` has had this split since 2026-08-22 and its docstring argues for it in terms.
`push` did not, and that is what this file pins.
"""

import subprocess
import time

import pytest

from core.errors import RefusalError, UsageError


def _wait_for(fn, want, timeout=30.0):
    """Poll until `fn()['state']` is in `want`. Returns the final status dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = fn()
        if status.get("state") in want:
            return status
        time.sleep(0.05)
    raise AssertionError(f"never reached {want}; last was {fn()}")


# -- ⭐⭐ the split ------------------------------------------------------------

def test_the_mcp_path_returns_a_run_id_instead_of_blocking(robot, repo, ledger_ok):
    """⭐⭐ THE HEADLINE. `wait=False` is what the MCP tool passes, because the 300s ceiling
    is a property of the TRANSPORT rather than of pushing."""
    out = robot.push("illustrated", reason="publish", wait=False)

    assert out["state"] == "running"
    assert out["run_id"]
    assert out["branch"] == "illustrated"

    done = _wait_for(robot.push_status, {"allowed", "failed"})
    assert done["state"] == "allowed"
    assert done["run_id"] == out["run_id"]


def test_the_default_is_synchronous_so_every_other_caller_is_unchanged(robot, repo, ledger_ok):
    """⚠⚠ THE DEFAULT SITS ON THE SAFE SIDE ON PURPOSE. Defaulting to async would make the
    CLI, tests and any script report success for a push that had not happened yet — the exact
    confusion the `started` decision exists to prevent. Only the MCP tool opts out."""
    out = robot.push("illustrated", reason="publish")
    assert out["decision"] == "allowed"
    assert "run_id" not in out or out.get("state") != "running"


def test_the_run_id_ties_the_started_row_to_its_receipt(robot, repo, ledger_ok):
    """⚠ An outcome-only log cannot distinguish a run that FAILED from one that never
    happened. Once the receipt no longer arrives in the call that asked for it, the two rows
    must be joinable or `push_status` cannot match them."""
    out = robot.push("illustrated", reason="publish", wait=False)
    _wait_for(robot.push_status, {"allowed", "failed"})

    rows = [r for r in robot.audit.read() if r.get("run_id") == out["run_id"]]
    assert [r["decision"] for r in rows] == ["started", "allowed"]


# -- ⚠⚠ refusals stay in the caller's hands -----------------------------------

def test_a_refused_push_refuses_in_the_call_not_in_a_later_poll(robot, repo, ledger_refuses):
    """⚠⚠ THE PROPERTY THAT MAKES THE SPLIT SAFE. Only the irreversible ACT is backgrounded.
    A caller must learn "this push is not allowed" from the call it made — a refusal that
    surfaced only via polling would be a gate that answers after you stopped listening, which
    is the same defect `preflight` exists to fix one level up."""
    with pytest.raises(RefusalError):
        robot.push("illustrated", reason="publish", wait=False)

    # and nothing was launched
    assert robot.push_status()["state"] in ("none", "refused")


@pytest.mark.parametrize("branch", ["-force", "private/secret"])
def test_branch_shape_is_refused_before_anything_starts(robot, repo, ledger_ok, branch):
    with pytest.raises(RefusalError):
        robot.push(branch, reason="publish", wait=False)
    assert robot.push_status()["state"] == "none"


def test_a_missing_reason_is_refused_before_anything_starts(robot, repo, ledger_ok):
    with pytest.raises(RefusalError):
        robot.push("illustrated", reason=None, wait=False)
    assert robot.push_status()["state"] == "none"


def test_a_second_push_while_one_runs_is_refused(robot, repo, ledger_ok):
    """⚠ Same guard `preflight` uses. Two concurrent pushes of one branch race, and the audit
    could not say which receipt belonged to which act — and the hook would spend the ~25 minute
    pipeline twice."""
    robot.push("illustrated", reason="first", wait=False)
    try:
        with pytest.raises(RefusalError) as exc:
            robot.push("illustrated", reason="second", wait=False)
        assert "already running" in str(exc.value)
    finally:
        _wait_for(robot.push_status, {"allowed", "failed"})


# -- ⚠⚠ died means something different here than for a preflight --------------

def test_died_never_claims_nothing_was_pushed(robot, repo, ledger_ok, monkeypatch):
    """⚠⚠ THE ONE PLACE THIS IS NOT A COPY OF `preflight_status`. A preflight that dies
    provably changed nothing. A push that dies MAY ALREADY HAVE PUBLISHED — git can be killed
    after the remote accepted the ref and before the receipt is written. So the state must name
    the remote as the only authority rather than implying the push did not happen."""
    # a started row with no worker and no receipt is exactly the post-restart shape
    robot.audit.append(actor=robot.actor, op="push", args={"branch": "illustrated"},
                       decision="started", head=robot.git.head(), branch="illustrated",
                       reason="publish", detail="push started", run_id="pushabc123")

    status = robot.push_status()
    assert status["state"] == "died"
    assert status["check"] == "ls-remote"
    note = status["note"].lower()
    assert "does not mean nothing was pushed" in note
    assert "ls-remote" in note
    # it must NOT tell the caller to just try again
    assert "do not retry" in note


def test_no_push_started_reads_as_none_not_as_died(robot, repo):
    """⚠ "nothing has happened" and "something happened and we lost it" are different facts;
    the same distinction `started` was added for."""
    assert robot.push_status()["state"] == "none"


# -- ⚠ the timeout that was the actual bug ------------------------------------

def test_the_git_timeout_clears_the_hook_not_just_the_network(robot, repo):
    """⚠⚠ THE NUMBER THAT KILLED THE PUSH, PINNED. 900s was chosen when the pre-push pipeline
    took ~155s. That hook is the BACKSTOP — it runs on every push by design — and it now takes
    1498s, so the old ceiling killed the push mid-gate and it looked like a network fault.

    Read from source rather than exercised, because reproducing it means a 25-minute run: the
    claim is about which ceiling was chosen, not about behaviour on a fast test remote.

    ⚠ REWRITTEN 2026-09-21 WHEN THE LITERAL MOVED TO A CONSTANT. This asserted the TEXT
    `timeout=3600` inside `push`, so lifting the number to module scope — so `status.in_flight`
    could quote the cap that actually bounds a running push — failed a test whose subject had
    not changed at all. ⭐ The repair makes it stricter, not looser: it pins the VALUE, and
    separately pins that `push` passes THAT object rather than a number of its own. The old
    form would have passed a second hardcoded 3600 sitting beside a constant saying something
    else, which is the two-copies shape the lift existed to prevent.
    """
    import inspect
    from core import engine
    src = inspect.getsource(engine.GitRobot.push)
    assert 'timeout=900' not in src, "900s is below the measured 1498s hook"
    assert engine.PUSH_TIMEOUT >= 1800, (
        f"the ceiling is {engine.PUSH_TIMEOUT}s; the measured hook alone took 1498s and its "
        f"own phase budget is {engine.gates_mod.PHASE_TIMEOUT['pre-push']}s")
    assert engine.PUSH_TIMEOUT == 3600
    assert 'timeout=PUSH_TIMEOUT' in src, (
        "push no longer passes the published constant, so the cap a caller is quoted and the "
        "cap git runs under would be free to drift apart")


def test_the_push_names_the_remote_by_url_not_by_alias(robot, repo, tmp_path, fake_gate,
                                                       ledger_ok):
    """⛔⛔ `origin` IS A LOCAL ALIAS AND EVERY SENTENCE CONTAINING IT IS ROUTED THROUGH A
    MUTABLE CONFIG VALUE.

    Tim's question 2026-09-25 opened this: *"origin main should be safe in theory, as long as
    the URL it means doesn't change."* It was not pinned and nothing verified it — `push` ran
    `git push origin <branch>` and trusted that `origin` meant today what it meant yesterday.
    A name that reads as a stable published reference and is actually a pointer: the defect
    class this repo is named for, sitting under the whole push path.

    ⛔ NOT HYPOTHETICAL. Measured the same day in the consumer's checkout: a SECOND remote named
    `fake` was configured, aimed at a scratchpad temp directory left by a probe. So "is this
    commit on a remote" was already the wrong question at that moment.

    ⭐ DISCLOSURE, NEVER A GATE. A push to a deliberately different remote is legitimate —
    `.claude-local` has its own — so this does not refuse a re-point. It removes the SILENCE:
    a re-point shows up in the audit and on the receipt at the moment it is used.

    ⚠ `get-url --push`, not `-v`: fetch and push URLs can differ, and a push must report where
    the PUSH goes.
    """
    fake_gate(0)
    receipt = robot.push("illustrated", reason="checking the remote is named by url")

    assert receipt.get("remote_url"), f"the receipt does not name the remote: {receipt}"
    assert receipt["remote_url"] != "origin", (
        "the receipt names the ALIAS, which is the thing that can be re-pointed")

    started = [r for r in robot.audit.read()
               if r.get("op") == "push" and r.get("decision") == "started"]
    assert started, "no started row for the push"
    assert started[-1].get("remote_url") == receipt["remote_url"], (
        "the audit row and the receipt disagree about where this push went — two answers to "
        "one question, which is the defect this field exists to remove")
    # ⚠ and push_status must read it from the STARTED row, not resolve it again: re-resolving
    # would price the remote as it is TODAY against a push that happened earlier.
    assert robot.push_status().get("remote_url") == receipt["remote_url"]


def test_an_unresolvable_remote_is_named_unresolved_rather_than_omitted(robot, repo, tmp_path,
                                                                        fake_gate, ledger_ok,
                                                                        monkeypatch):
    """⚠ ABSENCE IS NEVER SUCCESS, ON THIS FIELD TOO. A push whose remote cannot be resolved
    must say so — an absent field reads as "nothing to say", and here the thing there is to say
    is that we do not know where this went."""
    fake_gate(0)
    real = robot.git.run

    def no_remote(args, **kw):
        if args and args[0] == "remote":
            raise RuntimeError("remote unreadable")
        return real(args, **kw)
    monkeypatch.setattr(robot.git, "run", no_remote)

    receipt = robot.push("illustrated", reason="remote cannot be resolved")
    assert receipt.get("remote_url") == "unresolved", (
        f"an unresolvable remote was omitted rather than named: {receipt}")
