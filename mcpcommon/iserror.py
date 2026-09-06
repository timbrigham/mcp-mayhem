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

⚠ `ok` IS THE ONLY SIGNAL, AND IT IS ALREADY UNIVERSAL. Every tool on these servers goes
through a `_guard` that returns `{"ok": True, ...}` or `{"ok": False, "error_type": ...}`.
This reads that one key and nothing else — it does not re-derive success, and it never
inspects `error_type`, because a tool that answers `ok: false` has already decided.
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types


def _text(value: Any) -> str:
    """Serialise exactly as FastMCP would, so the bytes a caller sees do not move."""
    return json.dumps(value, indent=2, default=str)


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
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=_text(
                    {"ok": False, "error_type": "unhandled",
                     "error": f"{type(exc).__name__}: {exc}", "tool": name}))],
                isError=True,
            )

        # ⚠ A tool that does not return a dict cannot be judged, so it is reported as a
        # success rather than guessed at. Every tool here returns `_guard`'s dict; if one
        # ever does not, silence is the honest answer and `isError` stays false.
        refused = isinstance(result, dict) and result.get("ok") is False

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
