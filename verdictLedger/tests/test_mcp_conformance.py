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

# ⭐⭐ THE DEBT IS PAID. 2026-09-07: every parameter on this server declares a real shape.
# `append`/`validate` take a `Record` model and `sign`/`override` take a `Basis` — so `step`,
# `verdict`, `subjects`, `basis`, `run.id` and `failing` are visible to the protocol instead
# of living in a fifty-line docstring a direct caller never reads.
#
# ⚠ THE SET IS KEPT, EMPTY, RATHER THAN DELETED WITH ITS TESTS. The ratchet below fails when
# NEW debt appears, and that is the half that still has work to do — an empty allowlist is a
# working control, not a finished one. The exit condition the old comment stated ("both this
# test and the ratchet can be deleted") was written when the set could only shrink to zero
# once; deleting the ratchet would let the next `dict` parameter arrive unremarked.
UNCONSTRAINED_DEBT = set()


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
    assert not UNCONSTRAINED_DEBT, (
        f"unconstrained-parameter debt has been RE-DECLARED: {sorted(UNCONSTRAINED_DEBT)}. "
        f"The set reached empty on 2026-09-07 and adding a line here is declaring new debt, "
        f"not recording an inconvenience. SATISFIED WHEN: the parameter takes a real shape.")


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
    """A caller fixing one rule per round trip gives up and works around the server.

    ⚠⚠ THE PROBE CHANGED 2026-09-08 AND THE REASON IS THE POINT. It used to send
    `{"totally": "malformed"}` and expect `error_type: "validation"`. Now that `step`,
    `verdict`, `basis`, `subjects` and `run` are REQUIRED at the door, that record never
    reaches the V-rules — it is refused as `usage`, naming the missing fields.

    ⭐ Both refusals are correct and they answer different questions, so this test now needs
    a record that SATISFIES the shape and still breaks several rules. Otherwise it would be
    asserting "many violations" about a payload the rule engine never sees, which is a
    control measuring the wrong layer — the exact substitution this file exists to catch.
    """
    result, text = _call("append", {"record": {
        "step": "definitely_not_registered", "verdict": "PASS", "tier": "M",
        "basis": {"kind": "tree", "value": "a" * 40},
        "subjects": [{"path": "a.md", "git_blob_id": "b" * 40}],
        "run": {},                       # no id -> V9; no config_sha -> V10
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
    }})
    payload = json.loads(text)
    assert result.isError is True
    assert payload["error_type"] == "validation", (
        "a well-SHAPED record that breaks rules must be a validation refusal, not usage")
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
        want = set([declared] if isinstance(declared, str) else list(declared))
        # ⭐ SECOND SOURCE, ADDED 2026-09-08: a harness loop break also excludes paths, and it
        # is deliberately NOT in the consumer's registry — carving is the harness's decision.
        # So the invariant tightens rather than relaxes: served must equal the registry's
        # declaration UNION this step's carve, and NOTHING ELSE. A path appearing in neither
        # is still exactly the silent divergence this control was written for.
        carve = set(((cfg.loopbreaks.get("breaks") or {}).get(step) or {}).get("exclude") or [])
        assert set((served.get(step) or {}).get("scope_exclude") or []) == want | carve, (
            f"{step}: served exclusions are neither the registry's declaration nor the "
            f"harness carve. The consumer would carve out a different set than either file "
            f"declares, and neither side would see the disagreement.")


# -- ⭐⭐ the input contract, and the control that keeps it honest --------------

def test_the_input_model_accepts_every_record_in_the_stream():
    """⭐⭐ A MODEL STRICTER THAN REALITY REFUSES TRAFFIC THAT WORKS TODAY.

    `append` and `validate` published `{"type":"object","additionalProperties": true}` — any
    object at all — so the real contract lived in a fifty-line docstring a direct caller never
    reads. Declaring a shape closes that. Declaring the WRONG shape closes the server.

    ⚠⚠ THIS CONTROL EARNED ITS KEEP ON ITS FIRST RUN. The first draft gave `failing` the same
    shape as `subjects` — a list of objects — by analogy rather than by measurement. The stream
    refused it: 37 records carry `failing`, 308 elements, **every one a `str`**, some not even
    paths (`tools/verify/(roster)`). Modelled from the docstring, contradicted by the data.

    ⚠ So the assertion is not "the model is correct" — it is "the model admits everything the
    ledger has ever accepted". Anything this rejects, V1-V18 would have to reject too, never
    the reverse.
    """
    import json
    from pydantic import ValidationError
    from ledger_server.inputs import Record

    # ⛔⛔ THIS TEST SKIPPED ON ITS FIRST RUN AND THAT WAS THE DEFECT, NOT THE SETUP. The real
    # stream lives in the gitignored `.mcp-local`, so `pytest.skip` made a control that never
    # ran and reported green — the exact shape this file exists to catch, committed while
    # writing a control against it.
    #
    # ⚠ The stream cannot be committed: it carries consumer paths and reason prose, and THIS
    # REPO IS PUBLIC. So the always-runs half is a SYNTHETIC fixture of shapes MEASURED off the
    # real stream, and the live stream is checked additionally when present. The fixture guards
    # the shapes we know about; the live check guards the ones we do not.
    fixture = [
        # a mechanical PASS, the common case
        {"schema": "zp.record.v1", "id": "s@t#0", "step": "s", "tier": "M", "verdict": "PASS",
         "basis": {"kind": "tree", "value": "a" * 40, "resolved_from": "explicit"},
         "subjects": [{"path": "a.md", "git_blob_id": "b" * 40}],
         "evidence": [{"path": "t.py", "git_blob_id": "c" * 40}],
         "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
         "revision": 0, "cost": {"seconds": None, "usd": 0.0},
         "run": {"id": "r", "started": "2026-09-07T00:00:00+00:00", "config_sha": "d" * 64,
                 "env": {}}},
        # ⚠ `failing` as a list of STRINGS — the shape the first draft of the model got wrong
        {"step": "s", "verdict": "FAIL", "tier": "A",
         "basis": {"kind": "tree", "value": "a" * 40},
         "subjects": [{"path": "a.md", "git_blob_id": "b" * 40}], "run": {"id": "r"},
         "failing": ["tools/verify/x.py", "tools/verify/(roster)"]},
        # ⛔ WAS "a minimal record: almost everything absent, which must remain legal", and
        # that is no longer the contract. Tim, 2026-09-08: *"both the shape and existence
        # should be being tested."* `step`+`verdict` alone was legal AT THE DOOR while V1-V21
        # rejected it three ways over (missing basis, subjects, run.id) — a published contract
        # admitting traffic the server always refused. The minimum is now the measured set.
        # ⚠ It is still MINIMAL: schema, tier, decided, revision, cost, inputs and evidence
        # stay absent here on purpose, because the rules accept their absence and the model
        # must never outrun the rules.
        {"step": "s", "verdict": "UNDECIDED",
         "basis": {"kind": "tree", "value": "a" * 40},
         "subjects": [{"path": "a.md", "git_blob_id": "b" * 40}], "run": {"id": "r"}},
        # ⚠ the pre-2026-08-25 run key, which V10 names rather than the schema rejecting
        {"step": "s", "verdict": "PASS",
         "basis": {"kind": "tree", "value": "a" * 40},
         "subjects": [{"path": "a.md", "git_blob_id": "b" * 40}],
         "run": {"policy_sha": "e" * 64}},
    ]
    records = list(fixture)

    data = os.environ.get("ZPLEDGER_DATA")
    live = Path(data) if data else (Path(__file__).resolve().parents[1] / "data"
                                    / "records.jsonl")
    if live.is_file():
        records += [json.loads(l) for l in live.read_text(encoding="utf-8").splitlines()
                    if l.strip()]

    rejected = []
    for rec in records:
        try:
            Record.model_validate(rec)
        except ValidationError as exc:
            rejected.append((rec.get("id"), exc.errors()[0].get("loc"),
                             exc.errors()[0].get("type")))
    assert not rejected, (
        f"the declared input shape REJECTS {len(rejected)} of {len(records)} records already "
        f"in the stream. Every one is a call that works today and would stop. "
        f"First three: {rejected[:3]}")


def test_failing_is_still_optional_because_the_emitter_is_not_at_a_hundred():
    """⛔ STEP ONE OF TWO, AND THE ORDER IS TIM'S: structure, then emitter, then require.

    Requiring `failing` is the point of modelling the record at all — a FAIL that does not say
    which bytes it condemns indicts everything it examined, which is how one FAIL condemned a
    sixteen-commit push. But measured 2026-09-07: **118 of 123 tier-A blocking records carry no
    `failing`**, and only 37 of 92 recent ones do. Requiring it now refuses every review gate
    on its next FAIL.

    ⚠ THIS TEST INVERTS WHEN THE EMITTER LANDS. It asserts the field is OPTIONAL, so it fails
    the moment someone makes it required — deliberately, so that step two is a decision with a
    red test in front of it rather than a quiet tightening. Delete it in the same change that
    requires the field.
    """
    from ledger_server.inputs import Record

    assert Record.model_fields["failing"].default is None, (
        "`failing` must remain OPTIONAL until the consumer's emitter reaches 100%")
    # ⚠ carries the fields required at the door since 2026-09-08; `failing` is still absent,
    # which is the only thing this test is about.
    Record.model_validate({"step": "check_prose", "verdict": "FAIL",
                           "basis": {"kind": "tree", "value": "a" * 40},
                           "subjects": [{"path": "a.md", "git_blob_id": "b" * 40}],
                           "run": {"id": "r"}})                        # must not raise


def test_the_model_declares_every_field_the_RULES_read():
    """⭐⭐ THE CONVERSE RATCHET, AND THE REASON IT EXISTS SEPARATELY.

    `test_the_input_model_accepts_every_record_in_the_stream` pins ONE direction: the model
    must not be stricter than reality. Nothing pinned the other — that the model KNOWS about
    every field the rules actually depend on.

    ⚠⚠ Tim, 2026-09-08: *"both the shape and existence should be being tested."* A model can
    be perfectly correct about the SHAPE of what it declares and silently blind to a field it
    never declared at all: `extra="allow"` absorbs it, the published `inputSchema` never
    mentions it, and a caller reading the contract cannot discover a key the server will judge
    them on. That is the contract migrating back into prose, one field at a time — the exact
    defect this whole file exists to have closed.

    ⛔ IT IS THE ONE-OF-TWO-ROUTES SHAPE AGAIN, which is why it earns a test rather than a
    habit. Three instances on 2026-09-08 alone: `unpinned_modules` read the `module` route and
    certified the no-module route clean; `circular_gates`' first draft read the registry route
    and missed `adversary`/`editorial` entirely; and V16 read only `how == "mechanical"` and so
    never once applied to the two steps that record most often. **A check that reads one of two
    routes does not report a smaller number — it certifies the other route clean.**

    Measured 2026-09-08: 14 keys read by the rules, all 14 declared. The gap is ZERO today and
    this test exists to keep it there.
    """
    import re
    from pathlib import Path
    from ledger_server.inputs import Record

    src = Path(__file__).resolve().parents[1] / "core" / "validate.py"
    read_by_rules = set(re.findall(r'record\.get\(\s*["\']([a-zA-Z_]+)["\']',
                                   src.read_text(encoding="utf-8")))
    assert read_by_rules, "the scrape found nothing — the pattern broke, not the code"

    declared = set()
    for name, f in Record.model_fields.items():
        declared.add(f.alias or name)
        declared.add(name.rstrip("_"))          # schema_ -> schema

    gap = sorted(k for k in read_by_rules if k not in declared)
    assert gap == [], (
        "these keys are judged by V-rules but absent from the published inputSchema, so a "
        "caller cannot discover them from the contract: %s" % gap)


def test_every_required_field_is_one_the_rules_also_demand(ledger):
    """⭐⭐ THE EXISTENCE HALF OF THE CONTRACT, MEASURED RATHER THAN ASSERTED.

    Tim, 2026-09-08: *"both the shape and existence should be being tested."* The sibling
    control pins that the model admits every record the stream holds. This pins the other
    edge of the same invariant: **every field the model REQUIRES must be one the V-rules
    would reject the absence of.** A required field the rules do not demand is the model
    outrunning the judge — it refuses callers for something nothing would have judged.

    ⛔ AND THE OBVIOUS WAY TO PICK THAT SET IS WRONG, which is why this runs rather than
    trusting a list. "Present on 100% of the stream" also returns `id`, `run.started` and
    `run.config_sha` — all three STAMPED by `_prepare` server-side. Requiring them would
    refuse every caller for omitting fields no caller has ever sent. The stream is
    post-normalisation; the door is not. So the test deletes each required field from a
    known-good record and asks the rule engine directly.
    """
    from ledger_server.inputs import Record
    from conftest import good

    base = good()
    base["evidence"] = [{"path": "tools/verify/check_invariants.py", "git_blob_id": "c" * 40}]
    assert ledger.validate(dict(base))["errors"] == [], (
        "the baseline must be clean or every deletion below proves nothing")

    required = sorted(n for n, f in Record.model_fields.items() if f.is_required())
    assert required, "no required fields — the door is not gating existence at all"

    unjudged = []
    for name in required:
        key = Record.model_fields[name].alias or name
        probe = dict(base)
        probe.pop(key, None)
        if not ledger.validate(probe)["errors"]:
            unjudged.append(key)

    assert unjudged == [], (
        "these are REQUIRED at the door but the rules accept their absence, so the model is "
        "stricter than the judge and refuses callers nothing would have judged: %s" % unjudged)


def test_no_served_description_understates_the_rules_it_runs():
    """⛔⛔ A DESCRIPTION THAT UNDERSTATES COVERAGE MAKES EVERY CLEAN RESULT UNCITEABLE.

    Found by the consumer 2026-09-08, and it is the INVERSE of the usual hazard. `validate`'s
    served description said "Schema plus V1-V18" while the function demonstrably ran V19, V20
    and V21. They posted an agreement-route record to `validate`, got no V21 objection, and
    could not cite the result — because if the description were true, V21 was never checked
    there and a clean answer proved nothing. An overstated claim gets caught the first time it
    is wrong; an understated one silently voids every green result taken against it.

    ⚠ SEVEN PLACES CLAIMED A RANGE AND TWO OF THEM WENT OVER THE WIRE. This is the
    second-copy-of-the-policy shape: a hand-maintained range in prose beside the rules it
    describes, drifting the moment a rule lands. So the range is DERIVED from the source here
    rather than pinned to a literal, and this fails when the next rule ships without the
    descriptions moving with it.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    src = (root / "core" / "validate.py").read_text(encoding="utf-8")
    highest = max(int(n) for n in re.findall(r'"V(\d+):', src))

    stale = []
    for rel in ("core/validate.py", "core/errors.py", "ledger_server/server.py",
                "ledger_server/inputs.py"):
        text = (root / rel).read_text(encoding="utf-8")
        for claimed in re.findall(r"V1[-–]V(\d+)", text):
            if int(claimed) != highest:
                stale.append("%s claims V1-V%s, code implements V1-V%d"
                             % (rel, claimed, highest))
    assert not stale, (
        "a served or documented rule range disagrees with the code. An UNDERSTATED range is "
        "the dangerous direction: it makes clean results from that path uncitable. %s" % stale)


def test_the_server_teaches_a_caller_through_every_channel_it_advertises():
    """⭐⭐ THREE CHANNELS, AND UNTIL 2026-09-08 THIS SERVER USED ONE.

    An outside cold-read audit registered all seven MCP servers to a fresh instance and asked
    a question the conformance suite never had: not "do the tools respond correctly" — they
    all did — but **is a cold agent TOLD how to use them.** Its finding: three channels teach
    a caller (server-level `instructions`, MCP resources, tool docstrings) and NO SERVER USED
    MORE THAN ONE. Six of seven shipped no instructions.

    ⛔ AND EVERY SERVER ADVERTISED A `resources` CAPABILITY WHILE SERVING AN EMPTY LIST.
    FastMCP advertises it by default. That is an untrue served contract of the same class as
    `validate` claiming V1-V18 while running V21 — and it sat one layer ABOVE all 22 checks in
    this file, every one of which audits tools.

    ⚠ WHY IT BITES HARDER THAN IT LOOKS: in the auditor's session every MCP tool was DEFERRED.
    It received ~200 bare tool names and no schemas. A docstring answers "how do I use this?"
    only after "which tool do I want?" is already settled. **`instructions` is the only
    channel that reaches an agent before it commits** — and it found gitRobot's requirements(),
    the best onboarding artifact in the set, BY ACCIDENT in a speculative batch load.
    """
    import asyncio

    from ledger_server import server as srv

    instructions = srv.mcp.instructions or ""
    assert instructions.strip(), (
        "no server-level instructions: the only channel that reaches an agent BEFORE it picks "
        "a tool")
    for required in ("START HERE", "MISTAKE"):
        assert required in instructions, (
            "instructions must name the first call to make and the mistake that will bite — "
            "missing %r" % required)

    resources = asyncio.run(srv.mcp.list_resources())
    assert resources, (
        "this server advertises a `resources` capability; serving none makes that capability "
        "an untrue claim — either serve something or stop advertising it")
    for r in resources:
        assert r.name and r.description and r.mimeType, (
            "every resource declares uri/name/description/mimeType per CLAUDE.md's resource "
            "contract; %s is missing one" % r.uri)


def test_every_call_signature_in_instructions_is_actually_callable():
    """A CONFIDENTLY WRONG INSTRUCTION IS WORSE THAN NO INSTRUCTION.

    Added `instructions` on 2026-09-08 after an outside cold-read audit found no server here
    used more than one of the three channels that teach a caller. Then wrote the call
    signatures from MEMORY rather than from the schemas, and the same auditor caught it:

        sjv            view() REQUIRES kind.  validate(collection=...) takes NO parameters.
        verdictLedger  inventory(ref=...) REQUIRES action.

    Their judgement is the one to keep: "As written this is a DOWNGRADE from having no START
    HERE, because it directs confidently to a dead end." A cold agent burns two failed calls
    and still lacks the answer it was promised.

    IT IS LOAD-BEARING FOR THIS AUDIENCE. Under deferred tool loading an agent receives
    `instructions` but NOT the schemas, so a signature written in prose is the only signature
    it has until it spends a schema load.

    This control is the auditor's own suggestion and closes the CLASS rather than the two
    instances. Run against the live surface it found FIVE problems, two of which the manual
    audit missed - a bare merge() and find(count_only=True) - which is the argument for a
    parser over a proofread.
    """
    import asyncio
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from mcpcommon.instructioncheck import unsupported_calls

    from ledger_server import server as _srv

    tools = [{"name": t.name, "inputSchema": t.inputSchema}
             for t in asyncio.run(_srv.mcp.list_tools())]
    problems = unsupported_calls(_srv.mcp.instructions or "", tools)
    assert not problems, "uncallable signatures in instructions: %s" % problems


def test_no_server_defines_an_error_type_the_fleet_has_not_published():
    """ONE VOCABULARY, IMPORTED - not three, restated.

    Measured 2026-09-08. error_type was defined in two errors.py files that had diverged with
    only `usage` in common:

        verdictLedger   config, ledger, unavailable, usage, validation
        gitRobot        gate, gitrobot, refusal, repo, usage
        mcpcommon/iserror.py emits `unhandled` and READS the field on every refusal from
                        every server while owning none of it

    Nine values, three definition sites, no shared source. A caller could not enumerate what
    it might receive, and two servers answering the same question with different words is the
    second-copy-of-the-policy defect at fleet scale.

    Tim, 2026-09-08: "the standard and the definitions themselves are under the control of the
    mcp instance, and the zeroparadox framework is strictly a consumer."

    Both errors.py now take their VALUE from mcpcommon.vocabulary via _kind(), which raises if
    a server invents one. This test is the other half: it walks the exception classes and
    asserts every published error_type is in the shared table, so the next one cannot be added
    locally.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from mcpcommon.vocabulary import ERROR_TYPES

    from core import errors as vl_errors

    found = set()
    for name in dir(vl_errors):
        obj = getattr(vl_errors, name)
        if isinstance(obj, type) and issubclass(obj, Exception):
            kind = getattr(obj, "error_type", None)
            if isinstance(kind, str):
                found.add(kind)
    assert found, "no error_type values found - the scrape broke, not the code"
    unpublished = sorted(found - set(ERROR_TYPES))
    assert not unpublished, (
        "these error_type values are defined locally and published by nobody, so a caller "
        "cannot enumerate them: %s" % unpublished)


def test_the_vocabulary_resource_is_generated_not_transcribed():
    """A vocabulary resource must RENDER the constants, never carry a copy of them.

    CLAUDE.md's resource contract: "generated from the constants the code imports, never
    hand-authored. A hand-written dictionary is the FOURTH copy, not the replacement for
    three." This asserts the served document actually contains every published value, which a
    transcription would drift out of the moment a value was added.
    """
    import asyncio
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from mcpcommon.vocabulary import VOCABULARIES

    from ledger_server import server as srv

    uris = [str(r.uri) for r in asyncio.run(srv.mcp.list_resources())]
    assert any("vocabulary" in u for u in uris), "no vocabulary resource is served"

    rendered = asyncio.run(srv.mcp.read_resource("docs://verdictledger/vocabulary"))
    text = "".join(getattr(c, "content", "") or "" for c in rendered)
    for table in VOCABULARIES.values():
        for key in table:
            assert str(key) in text, (
                "%r is published in the constants but missing from the rendered resource - "
                "the document is a copy, not a rendering" % key)
