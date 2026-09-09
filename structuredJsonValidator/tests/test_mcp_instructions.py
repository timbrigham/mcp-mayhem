"""The instructions channel - is what it tells a caller actually callable?"""


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

    from mcp_server import server as _srv

    tools = [{"name": t.name, "inputSchema": t.inputSchema}
             for t in asyncio.run(_srv.mcp.list_tools())]
    problems = unsupported_calls(_srv.mcp.instructions or "", tools)
    assert not problems, "uncallable signatures in instructions: %s" % problems
