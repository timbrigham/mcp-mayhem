"""Make a refused tool call look refused AT THE PROTOCOL LAYER.

⚠⚠ THE DEFECT. Measured 2026-09-05 on the live servers: a `UsageError` refusal, a clean
success, and a four-violation validation rejection ALL returned `isError: false`. Three
protocol-identical results for three different outcomes. The distinction survived only as
JSON inside `content[0].text`, which every caller had to parse for itself.

That is *absence rendering as success*, at the one layer nobody had audited — and
`errors.py` states the promise it was breaking: "never a transport crash, never a bare
string a caller has to parse". At the MCP surface it was exactly a string the caller had
to parse.

⚠⚠ WHY NOT JUST RAISE. FastMCP offers no seam to set `isError` on a returned value —
`FastMCP.call_tool` returns `Sequence[ContentBlock] | dict`, never a `CallToolResult`. The
obvious fix is `raise ToolError(json.dumps(payload))`, and it is WRONG in a way that only
shows up on the consumer's side. Measured: the low-level server's `_make_error_result`
REWRITES the content to

    Error executing tool append: {"ok": false, ...}

which is no longer valid JSON. The consumer's `_call` does `json.loads(content[0].text)`
and falls back to `None`, so every structured refusal would silently collapse — they would
still block, but they would lose `error_type` and the whole `errors` list, which is
precisely the information that tells a validation refusal from an outage. A safety
improvement here would have been an information loss there, looking like nothing changed.

⭐⭐ SO GO ONE LAYER DOWN INSTEAD. The LOW-LEVEL `call_tool` handler accepts a
`types.CallToolResult` as a return value, which lets us set `isError` AND keep the content
pure JSON. Same bytes the consumer already parses, plus a correct protocol flag. The
consumer built an instrumented brace-slice fallback to survive the prefixed shape; this
route means that fallback stays at ZERO firings, which is their measurement that this
landed. A non-zero count after this is a defect, not noise.

⛔⛔ THIS DOCSTRING USED TO SAY "`ok` IS THE ONLY SIGNAL, AND IT IS ALREADY UNIVERSAL", AND
`CLAUDE.md` SAID THE OPPOSITE IN BOLD ON THE SAME DAY: "`ok` IS NOT UNIVERSAL AND MUST NOT BE
ASSUMED — sjv's reads do not have it at all." Two documents in one repository contradicting
each other about the contract, and this one was the one running.

⛔ WHAT IT COST, measured 2026-09-10 by a test session sweeping the read-only surface:
`sjv.check_head` returned `isError: true`, NO `structuredContent`, and NO `error_type`, while
its body was a COMPLETE DOMAIN REPORT — the check ran, it worked, it found 1717 unresolvable
entries. A strict client got nothing at all from a call that succeeded.

⭐⭐ THE CAUSE IS ONE OVERLOADED KEY, AND IT IS THE UNITS DEFECT AT THE TRANSPORT LAYER.
`check_head`'s `ok` is the FINDING axis — `core/cli.py` reads it as `return 0 if report["ok"]
else 1`, which is exit-code 0-vs-1, "found nothing" versus "found something". This handler read
the same key as the REFUSAL axis, "the call was accepted" versus "the call was refused". Same
name, two axes, and `mcpcommon/vocabulary.py` forbids exactly this collapse one layer down:
exit 1 is "a real finding, NOT an error".

⭐ SO THE DISCRIMINATOR IS `error_type`, NOT `ok` ALONE, and it is structurally safe rather
than conventional: `_guard` on verdictLedger and gitRobot has exactly two failure branches and
BOTH stamp `error_type`, and every exception class in each `errors.py` sets it through `_kind()`,
which RAISES on a value the fleet has not published. A refusal without `error_type` is therefore
not a thing this fleet can currently emit — and `test_a_refusal_always_carries_error_type` keeps
it that way, so the ambiguous case fails loudly instead of quietly becoming a success.

⚠ A DOMAIN RESULT MAY SAY `ok: false` AND MEAN IT. That is now part of the contract rather than
an accident: `ok: false` WITHOUT `error_type` is a finding, keeps its `structuredContent`, and
is not an error at the protocol layer.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types


def _text(value: Any) -> str:
    """Serialise exactly as FastMCP would, so the bytes a caller sees do not move."""
    return json.dumps(value, indent=2, default=str)



def _caller_argument_error(exc: BaseException, tool: str):
    """The pydantic `ValidationError` for THIS tool's arguments, or None.

    ⭐⭐ WHY THIS EXISTS AND WHY IT IS NARROW. ZeroParadox, 2026-09-07, called `get` with
    `record_id=` instead of `id=` and got back

        {"ok": false, "error_type": "unhandled",
         "error": "ToolError: Error executing tool get: 1 validation error for getArguments
                   id  Field required ..."}

    Their probe extracted `r.get("record", r)` and printed `verdict: None · subjects: 0`, and
    they nearly reported *"the rely round recorded nothing"* on the strength of it. The
    extraction bug was theirs; `unhandled` is what made it PLAUSIBLE. **`usage` names the
    remedy; `unhandled` names nobody, so the caller looks in the wrong place** — an unhandled
    exception reads as "the server is confused about my record" rather than "check your
    arguments". `coverage_gap` already does this right, refusing a missing `admission` with
    `usage` and a `SATISFIED WHEN:` line.

    ⚠⚠ AND IT DOES NOT CONTRADICT THE `unhandled` RULE ABOVE, which says inventing a class
    here would be "a guess wearing a taxonomy". This guesses nothing: a pydantic
    `ValidationError` whose title is `<tool>Arguments` is a STRUCTURAL fact — the caller's
    arguments did not match the published `inputSchema` — read off the exception TYPE, never
    off its message. Two of my own errors today came from matching strings where I should
    have parsed; this deliberately does not.

    ⚠ THE TITLE CHECK IS THE DISCRIMINATOR AND IT MATTERS. A tool that validates a pydantic
    model INTERNALLY also raises `ValidationError`, and that is the server's fault, not the
    caller's — blaming the caller for it would be the same misdirection with the sign flipped.
    `<tool>Arguments` is FastMCP's naming for the generated argument model. If that convention
    ever changes this returns None and the error stays `unhandled`: unclassified, which is the
    safe direction to be wrong in.
    """
    try:
        from pydantic import ValidationError
    except ImportError:                       # pragma: no cover -- pydantic is a hard dep
        return None
    seen, err = 0, exc
    while err is not None and seen < 10:      # bounded: __context__ chains can cycle
        if isinstance(err, ValidationError) and getattr(err, "title", None) == f"{tool}Arguments":
            return err
        err = err.__cause__ or err.__context__
        seen += 1
    return None


def _satisfied_when(err, tool: str):
    """The field-level remedy, so a refusal names the SUCCESS CONDITION rather than the fault.

    ⚠ `errors()` is structured -- `[{'type': 'missing', 'loc': ('id',), ...}]` -- so the
    fields are READ, never scraped from the rendered message.
    """
    fields = []
    for item in err.errors():
        loc = ".".join(str(part) for part in (item.get("loc") or ())) or "(root)"
        fields.append({"field": loc, "problem": item.get("type") or "invalid"})
    named = ", ".join(f"{f['field']} ({f['problem']})" for f in fields) or "the arguments"
    return fields, (
        f"call `{tool}` with arguments matching its published inputSchema. Fix: {named}. "
        f"The schema is discoverable through `tools/list` and is the contract -- a shape you "
        f"FETCH cannot go stale the way a docstring can.")


def install(mcp) -> None:
    """Re-register the low-level `call_tool` handler so refusals set `isError`.

    ⚠ MUST BE CALLED AFTER FastMCP's own `_setup_handlers`, which happens in its
    constructor. Re-registering replaces the handler rather than chaining, which is the
    intent: FastMCP's version cannot express `isError` at all.

    ⚠ `validate_input=False` MATCHES WHAT FASTMCP REGISTERS. It disables the low-level
    schema check because FastMCP does its own ad-hoc coercion first; passing True here
    would start rejecting arguments that work today, which is a behaviour change smuggled
    in under an unrelated fix.
    """

    @mcp._mcp_server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict) -> types.CallToolResult:
        try:
            result = await mcp._tool_manager.call_tool(
                name, arguments, context=mcp.get_context(), convert_result=False)
        except Exception as exc:                        # noqa: BLE001
            # ⚠⚠ A RAISING TOOL MUST NOT ESCAPE TO THE PREFIXING PATH, AND ON THIS FLEET
            # SOME DO. Measured 2026-09-06 against the LIVE servers immediately after
            # this landed: verdictLedger and gitRobot were clean because every tool goes
            # through a `_guard` that RETURNS `{ok: false, ...}` — but sjv's read tools
            # (`get`, `find`, `view`) call the store directly and RAISE. So
            # `get(collection='nope')` came back
            #
            #     isError: true, text: "Error executing tool get: Unknown collection…"
            #
            # — the exact prefixed, unparseable shape this module exists to avoid, still
            # arriving on a third of the fleet. Two servers verified clean is not the
            # fleet verified clean; the third is the one that had a different internal
            # convention, and only calling all three found it.
            #
            # ⚠ `unhandled` is deliberately NOT one of the typed `error_type` values. The
            # tool did not classify this failure, and inventing a class for it here would
            # be a guess wearing a taxonomy — the same move as reconstructing `failing`
            # from a reason string.
            bad_args = _caller_argument_error(exc, name)
            if bad_args is not None:
                fields, satisfied = _satisfied_when(bad_args, name)
                payload = {"ok": False, "error_type": "usage",
                           "error": f"arguments do not match the inputSchema for {name!r}",
                           "tool": name, "fields": fields,
                           "satisfied_when": satisfied}
            else:
                payload = {"ok": False, "error_type": "unhandled",
                           "error": f"{type(exc).__name__}: {exc}", "tool": name}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=_text(payload))],
                isError=True,
            )

        # ⚠ A tool that does not return a dict cannot be judged, so it is reported as a
        # success rather than guessed at. Every tool here returns `_guard`'s dict; if one
        # ever does not, silence is the honest answer and `isError` stays false.
        #
        # ⛔⛔ `ok is False` ALONE WAS THE TEST UNTIL 2026-09-10 AND IT MISCLASSIFIED A WHOLE
        # TOOL. `sjv.check_head` answers `ok: false` to mean "I ran and FOUND DRIFT" — the
        # finding axis, the same one `core/cli.py` turns into exit 0-vs-1 — and this handler
        # read it as the refusal axis and stripped the report's `structuredContent`. One key,
        # two axes: the units defect, at the transport layer, in the module written to stop a
        # refusal looking like a success.
        #
        # ⭐ `error_type` is the honest discriminator because it is STRUCTURAL: `_guard` has two
        # failure branches and both stamp it, and every `errors.py` class sets it via `_kind()`,
        # which raises on an unpublished value. A refusal cannot currently reach here without it.
        refused = (isinstance(result, dict)
                   and result.get("ok") is False
                   and result.get("error_type") is not None)

        # ⚠⚠ `structuredContent` ON SUCCESS ONLY, AND THE ASYMMETRY IS THE POINT. A declared
        # `outputSchema` describes what a SUCCESSFUL call returns; a refusal has a different
        # shape entirely (`ok: false` plus `error_type`, `error`, `errors`). Attaching a refusal
        # to a success schema would publish a contract the response violates — a client that
        # actually validates would then break on exactly the calls it most needs to read.
        #
        # ⭐ So a refusal travels as `isError` plus JSON in `content`, which is what the consumer
        # already parses, and carries no structuredContent to be checked against the wrong shape.
        # Absence here is a fact about the result, not an omission.
        #
        # ⚠ Returning a CallToolResult BYPASSES the low-level server's own structuredContent
        # validation (measured 2026-09-06: declaring an outputSchema against this handler raised
        # nothing either way). That is why this had to be done deliberately rather than inherited
        # — the safety net that would have caught a mismatch is not in this path.
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=_text(result))],
            structuredContent=(result if (not refused and isinstance(result, dict)) else None),
            isError=refused,
        )


def install_resource_classification(mcp) -> None:
    """Make a failed `resources/read` say WHICH KIND of failure it was.

    ⛔⛔ THE GAP, FOUND FROM OUTSIDE 2026-09-08. `_install_is_error` above wraps `call_tool`
    and nothing else, so the resource path had no classification at all. Measured: an unknown
    URI returns a JSON-RPC error with `code: 0` and NO `error_type` field.

    ⚠⚠ AND A CALLER CANNOT TELL THE TWO FAILURES APART. The consumer hit both within an hour
    of each other, on the same call:

        "Unknown resource"   the server is up and does not have it   -> TERMINAL, do not retry
        "Connection closed"  the transport died mid-call             -> RETRY, it is probably
                                                                        a reconnect to a new pid

    Their words, and they are right: *"a caller who reads 'Connection closed' as 'not there
    yet' waits for a restart that already happened, and one who reads 'Unknown resource' as
    transient retries forever."*

    ⭐ THAT IS THE EXACT SPLIT `mcpcommon/vocabulary.py` DRAWS ONE LAYER UP — `validation` is
    terminal, `unavailable` is retryable, *"and conflating the two is how a rule gets retried
    past."* The tool path has held that line since the ledger was built; the resource path was
    never given it. So this applies the same vocabulary rather than inventing a second one.

    ⚠ THE TRANSPORT HALF CANNOT BE FIXED FROM HERE and this does not pretend to. When the
    connection dies there is no response to classify — the client sees a dead socket and the
    server never learns the call happened. What this fixes is the half the server owns: an
    error IT returns now says whether retrying could ever help. A caller that sees a classified
    `usage` knows to stop; anything unclassified reaching it is, by elimination, transport.
    """
    import mcp.types as types
    from mcp.shared.exceptions import ErrorData, McpError

    handlers = mcp._mcp_server.request_handlers
    original = handlers.get(types.ReadResourceRequest)
    if original is None:                     # nothing registered; nothing to wrap
        return

    async def _classified(req):
        try:
            return await original(req)
        except Exception as exc:
            # ⚠ An unknown URI is the CALLER's mistake, not a server fault — the same
            # classification a bad argument name gets on the tool path. `unhandled` is
            # reserved for a genuine server bug and must not absorb this.
            text = str(exc)
            kind = "usage" if "Unknown resource" in text else "unhandled"
            payload = {
                "ok": False,
                "error_type": kind,
                "error": text,
                "retryable": False,
                "note": ("A CLASSIFIED error means the server answered. If you instead saw the "
                         "connection drop, that is the transport and IS worth one retry — "
                         "typically a reconnect after a server restart."),
            }
            # ⚠ `McpError` lives in `mcp.shared.exceptions`, NOT in `mcp.types` — the first
            # draft raised an AttributeError from inside its own error handler, which the
            # client then saw as the resource's error message. A wrapper that fails is worse
            # than none, so this import is checked at wrap time below rather than at raise
            # time, where it would only surface on the failure path.
            raise McpError(
                ErrorData(code=types.INVALID_PARAMS if kind == "usage"
                          else types.INTERNAL_ERROR,
                          message=json.dumps(payload))) from exc

    handlers[types.ReadResourceRequest] = _classified


class SessionErrorClassifier:
    """Middleware: make a stale-session response say it is RETRYABLE.

    ⛔⛔ I TOLD THE CONSUMER THIS WAS NOT FIXABLE FROM HERE AND I WAS WRONG. My words were
    "when the connection dies there is no response to classify". Measured 2026-09-09 by
    driving the actual case instead of reasoning about it — the server answers cleanly:

        stale session id  ->  HTTP 404  {"code": -32600, "message": "Session not found"}
        no session id     ->  HTTP 400  {"code": -32600, "message": "Bad Request: Missing
                                         session ID"}

    Nothing dies. The client tears the connection down on the 404 and surfaces it as
    "Connection closed", so the transport-looking error is the CLIENT's rendering of a clean
    server answer that carried no classification.

    ⚠⚠ AND IT IS DETERMINISTIC, NOT FLAKY. The consumer measured three for three: every first
    resource read in the ~90 minutes after a restart failed and every retry succeeded. That is
    not a blip to tolerate, it is a documented state — a client holding a session from a dead
    pid — and it has exactly one correct remedy: retry once.

    ⭐ WHICH IS THE SPLIT THIS FLEET ALREADY OWNS. `vocabulary.ERROR_TYPES` says `unavailable`
    is retryable and `validation` is terminal, "and conflating the two is how a rule gets
    retried past." Here the cost runs the other way: an unclassified retryable error makes a
    caller give up on a real presence. The consumer nearly reported a shipped resource as
    never having shipped, twice.

    ⚠ SCOPE: this classifies the RESPONSE. Whether a given client surfaces the body or
    collapses it to a transport message is the client's to decide and not reachable from here.
    What changes is that the answer now carries `error_type` and `retryable`, so a client that
    reads it CAN tell "reconnect and retry" from "this genuinely does not exist".
    """

    NOTE = ("Your session belongs to a process that is gone - almost always a server restart. "
            "RETRY ONCE: re-initialize and repeat the call. This is NOT 'the resource does not "
            "exist'; an absent resource answers with error_type 'usage' and retryable false.")

    def __init__(self, app):
        self.app = app

    @classmethod
    def _reclassify(cls, body):
        """The rewritten body, or None to leave the response untouched."""
        if b"Session not found" not in body and b"Missing session ID" not in body:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None
        err = payload.get("error")
        if not isinstance(err, dict):
            return None
        err["error_type"] = "unavailable"
        err["retryable"] = True
        err["note"] = cls.NOTE
        payload["error"] = err
        return json.dumps(payload).encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # ⛔⛔ THE START MESSAGE IS HELD, AND THAT IS THE WHOLE CORRECTNESS ARGUMENT. The first
        # draft rewrote the body and forwarded the original headers, so `Content-Length` still
        # claimed the OLD size and the client raised IncompleteRead(0 bytes read, 91 more
        # expected). A clean 404 became a truncated read — strictly worse than the
        # unclassified error it was fixing. Caught by driving the case rather than reasoning
        # about it, which is the only reason it is not shipped.
        start = {"msg": None}

        async def _send(message):
            kind = message.get("type")
            if kind == "http.response.start":
                start["msg"] = message           # hold it; length is not known yet
                return
            if kind == "http.response.body":
                body = message.get("body") or b""
                rewritten = self._reclassify(body)
                head = start["msg"]
                start["msg"] = None
                if head is not None:
                    if rewritten is not None:
                        headers = [(k, v) for (k, v) in head.get("headers") or []
                                   if k.lower() != b"content-length"]
                        headers.append((b"content-length", str(len(rewritten)).encode()))
                        head = dict(head, headers=headers)
                        message = dict(message, body=rewritten)
                    await send(head)
                await send(message)
                return
            if start["msg"] is not None:         # anything else: flush the held head first
                head, start["msg"] = start["msg"], None
                await send(head)
            await send(message)

        await self.app(scope, receive, _send)
