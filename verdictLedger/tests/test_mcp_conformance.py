"""The MCP surface conformance controls — the convention, made enforceable.

⚠⚠ A CONVENTION WITH NO TEST IS A COMMENT. Measured 2026-09-05 across all four live
servers: 84 tools, ZERO tool annotations, zero `outputSchema`, zero titles, and twelve
parameters declared `{"type": "object", "additionalProperties": true}` — the shape that
constrains nothing. None of that was a decision; it is what FastMCP leaves unset when you
build a server from type hints and docstrings alone, so the contract migrated into prose.
Prose that used to be true is the thing that keeps costing us.

⭐ THE RATCHET IS THE POINT. `test_unconstrained_parameters_are_exactly_the_known_debt`
fails in BOTH directions — when a new unconstrained parameter appears AND when a listed
one is fixed without updating the list. That is deliberate. A one-directional check lets
debt sit forever as long as it does not grow; a ratchet makes every movement visible and
forces the number down to be green.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("ZPLEDGER_CONFIG", r"C:\Workspace\ZeroParadox\tools\verify")

from ledger_server.server import mcp  # noqa: E402

# ⚠ Everything that WRITES to the stream. Kept as a literal rather than derived from the
# annotations under test — a control that reads its expectation from the thing it is
# checking asserts only that the code equals itself.
WRITERS = {"append", "sign", "override", "narrow", "genesis"}

# ⚠⚠ THE KNOWN DEBT, NAMED. These four parameters publish `{"type":"object",
# "additionalProperties": true}` — "any object at all" — so `step`, `verdict`, `subjects`,
# `basis`, `run.id` and `failing` are invisible to the protocol and the real contract lives
# in a 50-line docstring on `append`. Replacing them with a Pydantic model is agreed work,
# blocked as of 2026-09-06 on the consumer's client landing `--failing-file` first: 118 of
# 118 tier-A blocking records carry no `failing`, so requiring it before that CLI exists
# would refuse every review gate on its next FAIL.
#
# ⛔ DO NOT ADD TO THIS SET TO MAKE A TEST PASS. Adding a line here is declaring new debt.
UNCONSTRAINED_DEBT = {
    ("append", "record"),
    ("validate", "record"),
    ("sign", "basis"),
    ("override", "basis"),
}


@pytest.fixture(scope="module")
def tools():
    return asyncio.run(mcp.list_tools())


def test_every_tool_declares_annotations(tools):
    """Without these a client cannot tell `append` from `find` at the protocol layer.

    For a server whose whole value is capability removal, the field that says "this one
    writes" is not decoration. The consumer session confirmed the cost of its absence on
    2026-09-05: it inferred which calls were safe to probe with from DOCSTRINGS.
    """
    missing = [t.name for t in tools if t.annotations is None]
    assert not missing, f"tools with no annotations: {missing}"


def test_every_tool_declares_a_title(tools):
    missing = [t.name for t in tools if not t.title]
    assert not missing, f"tools with no title: {missing}"


def test_writers_and_readers_are_correctly_marked(tools):
    """⚠ The dangerous error is one-directional.

    Marking a reader as a writer costs a needless confirmation prompt. Marking a WRITER as
    read-only invites a client to call it unattended. Both directions are checked, but that
    asymmetry is why this test exists at all.
    """
    marked_write = {t.name for t in tools if t.annotations.readOnlyHint is False}
    assert marked_write == WRITERS, (
        f"write set drifted — extra: {sorted(marked_write - WRITERS)}, "
        f"missing: {sorted(WRITERS - marked_write)}")


def test_nothing_here_is_destructive(tools):
    """⭐ AN APPEND-ONLY STREAM CANNOT DESTROY, AND THE ANNOTATION SAYS SO ON EVERY TOOL.

    This is a real claim about the design, not a default: a verdict is never removed or
    overwritten, and a wide FAIL is corrected by re-emitting at a higher revision rather
    than by withdrawing anything. If a tool ever needs `destructiveHint=True`, that is a
    change to what this server IS, and it should fail here first.
    """
    destructive = [t.name for t in tools if t.annotations.destructiveHint]
    assert not destructive, f"append-only stream cannot have destructive tools: {destructive}"


def test_unconstrained_parameters_are_exactly_the_known_debt(tools):
    """⭐⭐ A RATCHET, FAILING IN BOTH DIRECTIONS — see the module docstring.

    A new `dict` parameter fails this. Fixing a listed one ALSO fails it, which is the
    half that matters: it forces the set to shrink visibly rather than letting a stale
    allowlist quietly over-report the debt.
    """
    found = set()
    for tool in tools:
        for name, prop in ((tool.inputSchema or {}).get("properties") or {}).items():
            if prop.get("type") == "object" and prop.get("additionalProperties") is True:
                found.add((tool.name, name))

    assert found == UNCONSTRAINED_DEBT, (
        f"unconstrained-parameter debt moved.\n"
        f"  NEW (declare a real schema, do not add to the set): "
        f"{sorted(found - UNCONSTRAINED_DEBT)}\n"
        f"  FIXED (remove from UNCONSTRAINED_DEBT): "
        f"{sorted(UNCONSTRAINED_DEBT - found)}")


def test_the_debt_is_shrinking_not_load_bearing(tools):
    """⚠ A NUMBER NOBODY LOOKS AT STOPS BEING A DEBT AND BECOMES A FLOOR.

    Pins the count so it appears in the failure message of any change, and states the
    exit condition in the assertion rather than only in a comment.
    """
    assert len(UNCONSTRAINED_DEBT) <= 4, (
        "unconstrained parameters must not grow past the 2026-09-06 baseline of 4. "
        "SATISFIED WHEN: `record` and `basis` take Pydantic models, at which point this "
        "set is empty and both this test and the ratchet above can be deleted.")


def _call(name, arguments):
    """Drive the LOW-LEVEL handler, which is the only layer where `isError` exists."""
    from mcp.types import CallToolRequest, CallToolRequestParams
    handler = mcp._mcp_server.request_handlers[CallToolRequest]
    result = asyncio.run(handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments)))).root
    return result, result.content[0].text


def test_a_refusal_is_not_protocol_identical_to_a_success():
    """⭐⭐ ABSENCE RENDERING AS SUCCESS, AT THE TRANSPORT.

    Measured 2026-09-05: a usage refusal, a clean success and a four-violation validation
    rejection ALL returned `isError: false`. Three outcomes, one protocol result. The
    distinction lived only inside `content[0].text`, which every caller had to parse.
    """
    ok_result, _ = _call("find", {"verdict": "UNDECIDED"})
    assert ok_result.isError is False

    for name, args in (("find", {"verdict": "NONSENSE"}),
                       ("append", {"record": {"totally": "malformed"}})):
        result, _ = _call(name, args)
        assert result.isError is True, f"{name} refused but did not set isError"


def test_the_refusal_body_stays_pure_json():
    """⚠⚠ THE HALF THAT PROTECTS THE CONSUMER, AND THE REASON WE DID NOT JUST RAISE.

    `raise ToolError(json.dumps(...))` sets `isError` but the low-level server REWRITES the
    content to `Error executing tool <name>: {...}`, which is not valid JSON. The consumer
    does `json.loads(content[0].text)`, so every structured refusal would collapse to
    `None` — they would still block, but `error_type` and the whole `errors` list would be
    gone, which is exactly what tells a validation refusal from an outage.

    Returning a `CallToolResult` from the low-level handler keeps both. This test fails if
    anyone "simplifies" it back to raising.
    """
    result, text = _call("find", {"verdict": "NONSENSE"})
    assert result.isError is True
    payload = json.loads(text)          # must not need a brace-slice fallback
    assert payload["ok"] is False
    assert payload["error_type"] == "usage"
    assert not text.lstrip().startswith("Error executing tool"), \
        "content was rewritten by the raise path; error_type is lost to the consumer"


def test_a_validation_refusal_keeps_every_violation(tools):
    """A caller fixing one rule per round trip gives up and works around the server."""
    result, text = _call("append", {"record": {"totally": "malformed"}})
    payload = json.loads(text)
    assert result.isError is True
    assert payload["error_type"] == "validation"
    assert len(payload["errors"]) > 1, "V-rules must all be reported at once"


def test_a_raising_tool_still_returns_parseable_json():
    """⚠⚠ TWO SERVERS VERIFIED CLEAN IS NOT THE FLEET VERIFIED CLEAN.

    verdictLedger and gitRobot route every tool through a `_guard` that RETURNS
    `{ok: false, ...}`, so nothing raises. sjv's read tools call the store directly and
    RAISE — and on the first live check after this landed, `get(collection='nope')` came
    back as `"Error executing tool get: Unknown collection…"`: the prefixed, unparseable
    shape this module exists to prevent, still arriving on a third of the fleet.

    The handler now catches, so a raising tool produces JSON like any other refusal. This
    test drives a tool into an exception to prove it, rather than asserting it.
    """
    from mcp.types import CallToolRequest, CallToolRequestParams
    handler = mcp._mcp_server.request_handlers[CallToolRequest]

    # `narrow` on a record id that does not exist raises inside the ledger.
    result = asyncio.run(handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="narrow", arguments={
            "record_id": "no-such@nothing#0", "failing": ["a"]})))).root
    text = result.content[0].text

    assert result.isError is True
    assert not text.lstrip().startswith("Error executing tool"), \
        "a raising tool escaped to the prefixing path"
    payload = json.loads(text)
    assert payload["ok"] is False
    assert payload["error_type"], "a refusal must carry some error_type"


# ⭐⭐ PAID OFF 2026-09-06, FLEET-WIDE: 81 of 81 (verdictLedger 20, gitRobot 22, sjv 39). Was 20
# here and 81 across the fleet — every tool annotated `-> dict`, which FastMCP cannot turn into a
# schema, while CLAUDE.md asserted the standard anyway.
#
# ⚠ THE SHAPES WERE MEASURED, NOT INVENTED: reads off live responses from the running servers,
# writes off `_receipt` / `apply`, because calling a write to discover its shape is what put a
# probe verdict in the stream and blocked a tag.
#
# ⛔ THE RATCHET STAYS rather than being deleted, and stays at 0 rather than being loosened. It is
# now a REGRESSION guard, not a debt counter: a new tool shipped without a schema must fail here.
TOOLS_WITHOUT_OUTPUT_SCHEMA = 0


def test_output_schema_debt_is_exactly_the_declared_count(tools):
    """⭐ FAILS IN BOTH DIRECTIONS, so the gap cannot quietly persist OR quietly close.

    A tool gaining a real return model must move this number down. A new tool arriving
    without one must move it up. Either way somebody looks at CLAUDE.md's claim again.
    """
    missing = [t.name for t in tools if not t.outputSchema]
    assert len(missing) == TOOLS_WITHOUT_OUTPUT_SCHEMA, (
        f"outputSchema debt moved: {len(missing)} tools lack one, expected "
        f"{TOOLS_WITHOUT_OUTPUT_SCHEMA}. Missing: {sorted(missing)}. "
        f"SATISFIED WHEN: this reaches 0 and both this test and CLAUDE.md's ⛔ marker go.")


def test_every_refusal_carries_error_type_including_the_returned_one():
    """⭐⭐ A REFUSAL THAT WILL NOT SAY WHAT KIND IT IS, ON THE PATH WE TELL CALLERS TO USE.

    `_guard` replies `{"ok": True, **result}` and attaches `error_type` in its `except`
    branches — so RAISED refusals (`append` → ValidationFailure, `find` → UsageError) carry
    it, and the one refusal that is RETURNED rather than raised did not. That one is
    `validate`: the no-write dry run, the answer to "test a record without appending one",
    and therefore the exact tool a caller reaches for when classifying a problem.

    Measured 2026-09-06 by the consumer session, after this side asserted "error_type is on
    every refusal and always has been". It is not, it was not, and they built an extra
    `status` round trip to recover the distinction because the field they were told to key on
    was missing from the wire.

    ⚠ Keyed on violations, not on `ok`: a clean validate must NOT acquire an error_type.
    Absence of a problem is not a kind of problem.
    """
    bad = {"schema": "zp.record.v1", "step": "nope", "tier": "M", "verdict": "FAIL",
           "basis": {"kind": "tree", "value": "x"}, "subjects": []}

    for tool, args in (("validate", {"record": bad}),
                       ("append", {"record": bad}),
                       ("find", {"verdict": "NONSENSE"})):
        result, text = _call(tool, args)
        payload = json.loads(text)
        assert result.isError is True, f"{tool} refused without setting isError"
        assert payload["ok"] is False
        assert payload.get("error_type"), (
            f"{tool} refused without an error_type — a caller cannot tell a validation "
            f"refusal from an outage, which is the distinction errors.py exists to keep")

    # a PASSING validate must stay clean
    _, text = _call("validate", {"record": bad | {"step": "guards"}})
    assert "error_type" not in json.loads(text) or json.loads(text)["ok"] is False
