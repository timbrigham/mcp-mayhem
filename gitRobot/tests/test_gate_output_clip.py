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
