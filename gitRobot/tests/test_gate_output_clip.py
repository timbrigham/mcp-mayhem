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
