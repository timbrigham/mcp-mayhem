"""The receipt hands back a BOUNDED output, and narrows ONLY on visible success.

⛔⛔ THE DEFECT THESE PIN. `_receipt` clipped `detail` — and `detail` goes to the audit log
and never appears in the returned dict. The consumer receives `extra`, which fourteen call
sites fill with a raw subprocess stdout and which `_receipt` passed through untouched. So
the clip protected the copy written to disk and not the copy sent to the caller.

⚠ Measured 2026-09-09 off the call log, which prices the WIRE, not the stored excerpt:

    merge     2 calls   max 147,922 bytes
    commit    5 calls   max 147,812 bytes   median 1,011

The 147,922-byte payload reduced to "manifest reconciliation: 11 of 11 launched; 0 bad
exit(s)". Four consecutive merge/commit calls overflowed the consumer's context outright,
and an MCP response cannot be redirected to a file the way a shell command can — it lands
in the caller's context whole, the instant the call returns.

⛔⛔ THE FOURTH TEST IS THE ONE THAT MATTERS AND IT IS WRITTEN TO BE WATCHED FAILING. A
guard that demonstrates "success narrows" and merely ASSERTS the failure path is an
unpriced exemption bought with a fix — the worst way to buy one. Verified by inverting the
`succeeded` condition in `_bound_receipt_output`: `test_a_failure_is_not_narrowed` goes red.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.engine import _OK_TAIL_KEEP, _bound_receipt_output  # noqa: E402
from core.gates import _MAX_OUTPUT  # noqa: E402

# Long enough that both branches must truncate, so the two are told apart by HOW MUCH
# survives rather than by one of them happening to fit.
_HUGE = "PLAN\n" + ("ok   some passing check\n" * 9000) + "TAIL MARKER LINE"


def test_a_success_is_narrowed_to_the_tail():
    """The passing transcript answers a question nobody asked: the receipt already
    carries decision, head, branch, tree and ok."""
    out = _bound_receipt_output(
        {"decision": "allowed", "ok": True, "output": _HUGE})
    assert len(out["output"]) < _MAX_OUTPUT, "a success must be narrower than a failure"
    assert out["output"].endswith("TAIL MARKER LINE"), (
        "keep the TAIL — git prints its own result lines after the hook transcript")


def test_a_failure_is_not_narrowed():
    """⛔ THE LEG THIS WHOLE CHANGE IS HELD AGAINST. A caller reading a receipt after a
    failure needs the failing legs; a caller reading one after a success needs `ok`.
    Narrowing both would buy the context saving with the only case that needed the text.

    ⚠ SEEN TO FAIL: invert `succeeded` in `_bound_receipt_output` and this goes red while
    every other test in the file stays green."""
    out = _bound_receipt_output(
        {"decision": "failed", "ok": False, "output": _HUGE})
    assert len(out["output"]) > _OK_TAIL_KEEP * 4, (
        "a FAILURE must keep the generous clip, not the success budget")
    assert "TAIL MARKER LINE" in out["output"], (
        "a failing pipeline states its reason at the END — that is why _clip keeps the tail")


def test_an_unknown_state_takes_the_generous_branch():
    """⚠ "Absence is never success" cuts this way round. A receipt with no `ok` and no
    recognised decision must NOT be treated as a success and narrowed: a caller given too
    much output is inconvenienced, one given too little cannot see why something failed."""
    out = _bound_receipt_output({"output": _HUGE})
    assert len(out["output"]) > _OK_TAIL_KEEP * 4, (
        "an unrecognised decision must not be read as success")


def test_ok_false_under_an_allowed_decision_is_still_a_failure():
    """`merge` passes decision="allowed" together with ok=result.ok, so the two can
    disagree on exactly the path this was written for. `ok: False` wins."""
    out = _bound_receipt_output(
        {"decision": "allowed", "ok": False, "output": _HUGE})
    assert len(out["output"]) > _OK_TAIL_KEEP * 4


def test_output_bytes_prices_the_wire_and_never_the_excerpt():
    """⚠ `calllog.py` already holds this rule and it is the reason truncation here is
    safe: a clipped output that renders like a complete one is this project's recurring
    defect, and it would be worst in the record of what an operation did."""
    for decision, ok in (("allowed", True), ("failed", False)):
        out = _bound_receipt_output(
            {"decision": decision, "ok": ok, "output": _HUGE})
        assert out["output_bytes"] == len(_HUGE), "bytes must price the FULL output"
        assert out["output_truncated"] is True
        assert len(out["output"]) < out["output_bytes"]


def test_a_short_output_is_untouched_and_says_so():
    """No elision marker on text that was never elided — a marker on complete output is
    its own small lie."""
    out = _bound_receipt_output(
        {"decision": "allowed", "ok": True, "output": "[illustrated abc1234] msg"})
    assert out["output"] == "[illustrated abc1234] msg"
    assert out["output_truncated"] is False
    assert out["output_bytes"] == len("[illustrated abc1234] msg")


def test_the_error_field_is_bounded_too():
    """`stage` passes `extra={"error": result.output}` — a second raw-stdout field on the
    same path, and fixing only `output` would leave it to be found one incident later."""
    out = _bound_receipt_output({"decision": "refused", "error": _HUGE})
    assert len(out["error"]) < len(_HUGE)
    assert out["error_bytes"] == len(_HUGE)
    assert out["error_truncated"] is True


def test_non_string_fields_are_left_alone():
    """`worktree` and `admission` put lists and dicts in `extra`; only free text is text."""
    out = _bound_receipt_output(
        {"decision": "allowed", "ok": True, "output": None, "removed": ["a", "b"]})
    assert out["output"] is None
    assert out["removed"] == ["a", "b"]
    assert "output_bytes" not in out, "do not price a field that is not text"
