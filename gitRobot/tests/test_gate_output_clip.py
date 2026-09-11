"""A gate receipt must keep the END of a failing run — the reason lives there.

⭐⭐ MEASURED 2026-08-30 on preflight `025a6f16`. Exit 1, and the stored output ends mid-line at
`ok   prose ext ` with **no FAIL row anywhere in it**. The cap was `output[:8000]` — the FIRST
8000 characters — while the pre-push pipeline prints ~20 plan rows and hundreds of `ok` lines
before reaching the failure. The cause of a refusal was unrecoverable from the audit record of
the run that produced it.

⚠ AND IT COST THE SAME READER TWICE. ZeroParadox opening this arc: *"preflight_status truncated
the output before the failing row, so I reproduced the pipeline myself."* A receipt that makes you
re-run a 25-minute pipeline to learn why it failed is not a receipt.
"""

from core.gates import GateResult, _MAX_OUTPUT, _HEAD_KEEP


def _result(output, exit_code=1):
    return GateResult(phase="pre-push", ran=True, exit_code=exit_code, output=output)


def test_the_reason_at_the_end_survives(_unused=None):
    """⭐⭐ THE HEADLINE. The failing row is the last thing printed; it must be in the receipt."""
    body = "\n".join("    ok   check %d" % i for i in range(4000))
    output = body + "\n**FAIL: scan_pdfs found an unlisted asset**\n"
    stored = _result(output).record()["output"]

    assert len(output) > _MAX_OUTPUT, "the fixture must actually exceed the cap"
    assert "FAIL: scan_pdfs" in stored, "the failing row was truncated away — the 2026-08-30 bug"


def test_the_plan_at_the_start_also_survives(_unused=None):
    """⚠ The head is not worthless — the plan rows say WHICH legs were meant to run, and
    'the pipeline never reached leg 12' is a different diagnosis from 'leg 12 failed'."""
    output = "PRE-PUSH PIPELINE\n  1. build  BLOCK\n" + ("x" * 40000) + "\nFAIL at the end\n"
    stored = _result(output).record()["output"]
    assert "PRE-PUSH PIPELINE" in stored
    assert "FAIL at the end" in stored


def test_the_elision_is_stated_not_silent(_unused=None):
    """⚠⚠ A CUT OUTPUT THAT RENDERS LIKE A COMPLETE ONE IS THIS PROJECT'S RECURRING DEFECT, and
    it would be worst here — in the record of why something was refused. The marker names the
    number of characters dropped, so a reader can tell 'this is all of it' from 'this is an end'."""
    output = "y" * 50000
    stored = _result(output).record()["output"]
    assert "elided by gitRobot" in stored
    assert "characters elided" in stored


def test_short_output_is_untouched(_unused=None):
    """⚠ The complement: nothing is clipped or annotated when it fits. A marker on every
    receipt would train the reader to ignore it, which is how the signal dies."""
    output = "PRE-PUSH PIPELINE\n  all good\n"
    stored = _result(output, exit_code=0).record()["output"]
    assert stored == output
    assert "elided" not in stored


def test_the_receipt_stays_bounded(_unused=None):
    """⚠ Still a receipt, not a warehouse — the cap is the reason this function exists."""
    stored = _result("z" * 200000).record()["output"]
    assert len(stored) <= _MAX_OUTPUT + 200, "the marker must not blow the bound"
    assert _HEAD_KEEP < _MAX_OUTPUT


def test_the_receipt_detail_is_clipped_not_only_the_gate_record(robot, repo):
    """⛔⛔ THE CLIP COVERED ONE COPY AND MISSED THE OTHER. Reported by ZeroParadox 2026-09-04:
    every commit receipt blew the tool-result cap — eight times in one day, each spilling to a
    file they then had to grep for `ok` and `head`. Measured on the LIVE audit:

        total 79,300 chars   gates 8,364 (CLIPPED, working)   detail 68,954 (RAW)

    ⚠ `gates.output` was bounded by `_clip`; `detail` carried the SAME pipeline output unclipped
    and was 87% of the receipt. In production it arrives because gitRobot never passes
    `--no-verify`, so git runs the repo's own pre-commit hook and its whole run lands in
    `git commit`'s stdout, which the receipt then reports verbatim.

    ⚠⚠ Bounded at `_receipt` rather than per call site — `commit`, `push` and `merge` all hand a
    subprocess's stdout to `detail`, so a per-caller fix would leave the rest to be found one
    incident at a time. This asserts the choke point, which is the line that changed."""
    from core.gates import _MAX_OUTPUT

    robot._receipt("probe", {}, "allowed", detail="pipeline chatter\n" * 20_000)

    detail = robot.audit.read()[-1].get("detail") or ""
    assert len(detail) <= _MAX_OUTPUT + 500, (
        f"receipt detail is {len(detail)} chars — the pipeline output is riding unclipped")
    assert "elided by gitRobot" in detail, "the cut must be visible, never silent"
    assert detail.startswith("pipeline chatter"), "the head must survive"
    assert detail.rstrip().endswith("pipeline chatter"), (
        "the TAIL must survive — a failing gate states its reason at the end, which is why "
        "_clip keeps both ends rather than truncating")


# -- an exit code names WHAT happened, not merely whether it happened ----------

def test_gate_outcome_distinguishes_every_non_zero_state():
    """⭐⭐ Tim, 2026-09-10: "we should never have, for example zero and non-zero as the
    appropriate exit codes. they need to be specific as to exactly what they mean."

    `GateResult.passed` was exactly that collapse, at the gate guarding every commit and every
    push: a FINDING, an outage, an UNDETERMINED, a terminal REFUSAL and the 124 gates.py sets
    ITSELF on timeout all rendered as `passed: False`.

    ⚠ It fails CLOSED, so it was never a safety hole -- a remedy hole. Those states have
    different next actions (fix the content / retry / investigate / read the rule / widen the
    budget) and a boolean carries none of them.
    """
    from core.gates import GateResult

    def g(rc, ran=True):
        return GateResult(phase="pre-commit", ran=ran, exit_code=rc, output="")

    seen = {rc: g(rc).outcome for rc in (0, 1, 2, 3, 4, 124)}
    assert seen == {0: "clean", 1: "finding", 2: "could_not_ask",
                    3: "undetermined", 4: "refused", 124: "timed_out"}
    assert len(set(seen.values())) == len(seen), "two codes collapsed to one label"

    # ⛔ AN UNPUBLISHED CODE MUST NOT BORROW A NEIGHBOUR'S MEANING, AND ESPECIALLY NOT `clean`.
    assert g(7).outcome == "unpublished_7"
    assert g(None, ran=False).outcome == "did_not_run"


def test_outcome_is_additive_and_passed_is_untouched():
    """⛔ THE GATE ITSELF MUST NOT HAVE MOVED. `outcome` is a new field; `passed` keeps its
    exact prior meaning, so nothing that branches on it permits anything it did not before.
    A change that loosened the gate while claiming to only describe it would be the worst
    possible version of this."""
    from core.gates import GateResult

    for rc in (0, 1, 2, 3, 4, 7, 124):
        r = GateResult(phase="pre-commit", ran=True, exit_code=rc, output="")
        assert r.passed is (rc == 0), "passed changed meaning for exit %s" % rc
    assert GateResult(phase="p", ran=False, exit_code=None, output="").passed is False

    # and the audit row carries it, or nothing downstream can ever read it
    rec = GateResult(phase="pre-commit", ran=True, exit_code=4, output="x").record()
    assert rec["outcome"] == "refused" and rec["passed"] is False and rec["exit_code"] == 4
