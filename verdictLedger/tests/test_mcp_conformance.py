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

# ⚠ The repo's OWN config copies, suffixed `.sample` so nobody confuses them with the
# live bar in the consumer's tree (Tim, 2026-09-06).
ROOT_CONFIG = Path(__file__).resolve().parents[1] / "config"

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


# -- ⭐⭐ a caller's bad ARGUMENTS are a usage error, not an unhandled one ------

def _refuse(tool: str, arguments: dict):
    """Drive the real low-level handler `mcpcommon/iserror.py` installs, and return the
    parsed refusal payload. Nothing is stubbed — the classification under test happens
    inside that handler, so a stub would test the stub."""
    import asyncio
    from ledger_server import server as srv
    from mcpcommon import iserror

    captured = {}

    async def _run():
        try:
            await srv.mcp._tool_manager.call_tool(
                tool, arguments, context=None, convert_result=False)
        except Exception as exc:                       # noqa: BLE001
            bad = iserror._caller_argument_error(exc, tool)
            if bad is not None:
                fields, satisfied = iserror._satisfied_when(bad, tool)
                captured.update({"ok": False, "error_type": "usage", "tool": tool,
                                 "fields": fields, "satisfied_when": satisfied})
            else:
                captured.update({"ok": False, "error_type": "unhandled",
                                 "error": f"{type(exc).__name__}: {exc}", "tool": tool})
    asyncio.run(_run())
    return captured


def test_a_wrong_argument_name_is_reported_as_usage_not_unhandled():
    """⭐⭐ `usage` NAMES THE REMEDY; `unhandled` NAMES NOBODY.

    ZeroParadox, 2026-09-07, called `get(record_id=…)` — the field is `id` — and got
    `error_type: "unhandled"`. Their probe extracted `r.get("record", r)` and printed
    `verdict: None · subjects: 0`, and they nearly reported *"the rely round recorded
    nothing"* to Tim on the strength of it.

    ⚠⚠ The extraction bug was theirs. `unhandled` is what made it PLAUSIBLE: an unhandled
    exception is consistent with "the server is confused about my record", so the caller
    looks at the record. `usage` sends them to their own arguments in one hop.
    """
    out = _refuse("get", {"record_id": "rely@abc#1"})
    assert out["error_type"] == "usage", (
        "a pydantic error on the caller's own arguments is a USAGE error — the published "
        "inputSchema was not met, which is the caller's to fix")
    assert {"field": "id", "problem": "missing"} in out["fields"], (
        "and the OFFENDING FIELD must be named — read from errors(), never scraped from "
        "the rendered message")
    assert "inputSchema" in out["satisfied_when"] and "tools/list" in out["satisfied_when"], (
        "a refusal names the SUCCESS CONDITION: could a reader construct a passing next "
        "attempt from satisfied_when alone?")


def test_a_genuine_server_fault_is_still_unhandled():
    """⛔ THE CONTROL, AND IT IS THE HALF THAT KEEPS THIS HONEST. If every exception became
    `usage`, the taxonomy would blame the caller for the server's bugs — the same
    misdirection with the sign flipped. Only a pydantic error titled `<tool>Arguments`
    counts; anything else stays UNCLASSIFIED, which is the safe direction."""
    from mcpcommon import iserror

    assert iserror._caller_argument_error(RuntimeError("disk on fire"), "get") is None

    # a pydantic error that is NOT about this tool's arguments must not be claimed either
    import pydantic

    class Inner(pydantic.BaseModel):
        n: int

    try:
        Inner(n="not a number")
    except pydantic.ValidationError as exc:
        assert iserror._caller_argument_error(exc, "get") is None, (
            "an INTERNAL model failure is the server's fault; titled 'Inner', not "
            "'getArguments', so it must not be re-labelled as the caller's mistake")


def test_the_remedy_is_machine_actionable_not_only_readable():
    """⭐⭐ A PROGRAM MUST BE ABLE TO ACT ON IT, NOT ONLY A READER.

    The convention's test is *"could a reader construct a passing next attempt from
    `satisfied_when` alone, with `what` deleted?"* — and I asserted this shape passed it.
    ZeroParadox then RAN it: discarded `error`, read only the structured `fields`, rebuilt
    the arguments mechanically, and the retry succeeded.

    ⚠⚠ THAT PROPERTY WAS ASSERTED BY ME AND RUN BY NOBODY, which this codebase calls an
    unpriced exemption: *"a control whose surviving enforcement is ASSERTED rather than RUN."*
    Their verification was a one-off in a live session and would not survive the week. This
    is it, permanently.

    ⚠ SCOPE, DELIBERATELY NARROW. It asserts the ARGUMENT error clears — not that the record
    exists. `fields` promises "here is what is wrong with your call", never "your query will
    find something", and testing the second would make this fail for reasons that are not
    about the contract.
    """
    import asyncio
    from ledger_server import server as srv
    from mcpcommon import iserror

    bad = _refuse("get", {"record_id": "rely@abc#1"})
    assert bad["error_type"] == "usage"

    # Build the retry from `fields` ALONE — no English parsed, `error` never read.
    retry_args = {f["field"]: "rely@abc#1"
                  for f in bad["fields"] if f["problem"] == "missing"}
    assert retry_args == {"id": "rely@abc#1"}, (
        "the structured fields must be sufficient to name the argument that was wrong")

    still_a_usage_error = {}

    async def _go():
        try:
            await srv.mcp._tool_manager.call_tool(
                "get", retry_args, context=None, convert_result=False)
        except Exception as exc:                        # noqa: BLE001
            if iserror._caller_argument_error(exc, "get") is not None:
                still_a_usage_error["yes"] = str(exc)

    asyncio.run(_go())
    assert not still_a_usage_error, (
        f"arguments rebuilt from `fields` must satisfy the inputSchema; still refused as a "
        f"usage error: {still_a_usage_error.get('yes')}")


# -- ⭐⭐ the contract's FETCH PATH — see the corpus/harness tenancy terms -------

def test_requirements_serves_the_fields_the_consumer_must_stop_parsing():
    """⭐⭐ THE CONTRACT DEPENDS ON THIS AND NOTHING PINNED IT.

    Agreed 2026-09-07 (Tim): the config files move to this repo, and ZeroParadox stops reading
    them off disk. Two call sites parse `required.v2.json` by FILESYSTEM PATH today —
    `guards.py:461` for `types.rely.scope`, and `check_release_ready.py:363` for the whole
    `types` dict. Both convert to `requirements()` BEFORE custody moves, because moving the file
    first breaks them.

    ⚠⚠ SO `requirements()` BECOMES LOAD-BEARING FOR ANOTHER REPO, and the field it must carry is
    exactly the one this function has already dropped once. `Config.requirements()` rebuilds each
    spec KEY BY KEY from a whitelist: measured 2026-09-06, V16c was written, the registry was
    pinned, the spec read correctly from disk — and nothing fired, because `approved_modules`
    never survived the rebuild. **A validator can only enforce what that dict carries, and now so
    can a consumer.**

    ⛔ `scope_exclude` IS THE ONE THAT MATTERS MOST. Under term 2 the harness owns the carve-outs
    — carving is deciding — so it is the field the consumer must fetch rather than hold. If it
    silently stopped being served, the consumer would fetch a policy with no exclusions and
    every excluded path would read as in-scope. That is a widening, in the direction of more
    work rather than less, so it would look like diligence rather than a defect.
    """
    from core import config as config_mod

    cfg = config_mod.load(policy_path=ROOT_CONFIG / "policy.v1.sample.json",
                          required_path=ROOT_CONFIG / "required.v2.sample.json")
    served = cfg.requirements()

    declared_scope = {s for s, v in (cfg.required.get("types") or {}).items()
                      if isinstance(v, dict) and v.get("scope")}
    declared_excl = {s for s, v in (cfg.required.get("types") or {}).items()
                     if isinstance(v, dict) and v.get("scope_exclude")}
    assert declared_scope and declared_excl, (
        "the sample registry must exercise BOTH fields or this test proves nothing — a control "
        "over data that does not contain the case is the warrant-satisfied-while-empty shape")

    missing_scope = {s for s in declared_scope if not (served.get(s) or {}).get("scope")}
    assert not missing_scope, (
        f"`requirements()` dropped `scope` for {sorted(missing_scope)}. `guards.py` fetches this "
        f"instead of parsing the file; dropping it silently un-scopes a step.")

    missing_excl = {s for s in declared_excl if not (served.get(s) or {}).get("scope_exclude")}
    assert not missing_excl, (
        f"`requirements()` dropped `scope_exclude` for {sorted(missing_excl)}. The harness OWNS "
        f"the carve-outs under term 2 — a consumer fetching policy with no exclusions reads "
        f"every excluded path as in-scope, which widens the gate while looking like diligence.")


def test_the_served_exclusions_are_the_declared_ones_not_merely_present():
    """⚠ PRESENCE IS NOT VALUE, and this project has paid for that distinction already.

    `RLYB4-1`: a verdict row was PRESENT and held a zero the leg never earned — *"Presence was
    checked and value was not."* A `scope_exclude` served as `[]` would pass a presence check and
    carve out nothing. So compare the CONTENT against the registry, not the key against None.
    """
    from core import config as config_mod

    cfg = config_mod.load(policy_path=ROOT_CONFIG / "policy.v1.sample.json",
                          required_path=ROOT_CONFIG / "required.v2.sample.json")
    served = cfg.requirements()
    for step, spec in (cfg.required.get("types") or {}).items():
        if not isinstance(spec, dict):
            continue
        declared = spec.get("scope_exclude")
        if not declared:
            continue
        want = [declared] if isinstance(declared, str) else list(declared)
        assert (served.get(step) or {}).get("scope_exclude") == want, (
            f"{step}: served exclusions differ from the registry. The consumer would carve out a "
            f"different set than the file declares, and neither side would see the disagreement.")
