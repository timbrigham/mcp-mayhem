"""Are the call signatures written in a server's `instructions` actually callable?

⚠⚠ THE DEFECT THIS EXISTS FOR, AND IT WAS MINE. On 2026-09-08 an outside cold-read audit
found that no server here used more than one of the three channels that teach a caller
(`instructions`, resources, tool docstrings). I added `instructions` to all three servers the
same day — and wrote call signatures into them from memory rather than from the schemas:

    sjv            "START HERE: view() ... then validate(collection=...)"
                   view REQUIRES kind; validate takes NO parameters. Neither call is callable.
    verdictLedger  "then inventory(ref=...)"
                   inventory REQUIRES action. Refused with fields:[{action, missing}].

⛔ THE AUDITOR'S JUDGEMENT IS THE POINT: *"As written this is a DOWNGRADE from having no
START HERE, because it directs confidently to a dead end."* A cold agent burns two failed
calls and still lacks the answer it was promised. An absent instruction costs nothing; a
wrong one costs trust in the whole surface.

⭐ AND IT IS LOAD-BEARING FOR THIS AUDIENCE SPECIFICALLY. Under deferred tool loading an agent
receives `instructions` but NOT the schemas — so a call signature written in prose is THE ONLY
SIGNATURE IT HAS until it spends a schema load. Prose signatures matter here in a way they
would not in a client that ships every schema up front.

⭐ The remedy is the auditor's, and it closes the class rather than the two instances: PARSE
THE SIGNATURES OUT OF `instructions` AND ASSERT THEM AGAINST THE LIVE `inputSchema`. Unknown
tool, unknown parameter, missing required parameter — all three are mechanically detectable.

⚠ ONE IMPLEMENTATION AT THE REPO ROOT, never copied into each server. That is the same rule
`calllog.py` holds and the defect `verdictLedger/client/record.py` exists to warn about: three
copies of this check would drift, and the weakest copy is the one nobody notices.
"""

from __future__ import annotations

import re

# A call written in prose: `name(` ... `)`, no nesting. Prose forms like
# `requirements(action='push'|'commit'|'tag')` are fine — only the ARGUMENT NAMES are read.
_CALL = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(([^()]*)\)")
_KWARG = re.compile(r"([a-z_][a-z0-9_]*)\s*=")


def unsupported_calls(instructions: str, tools: list) -> list:
    """Every signature in `instructions` that the live schemas would refuse.

    `tools` is what `tools/list` returns: dicts carrying `name` and `inputSchema`.
    Returns a list of human-readable problems; empty means every signature is callable.

    ⚠ A name that matches no tool is IGNORED, not reported. Instructions legitimately contain
    prose parentheticals and shell fragments, and flagging those would make the control noisy
    enough to be switched off — which is worse than not having it.
    """
    schema_of = {t["name"]: (t.get("inputSchema") or {}) for t in tools}
    problems = []
    for name, arglist in _CALL.findall(instructions or ""):
        if name not in schema_of:
            continue
        schema = schema_of[name]
        props = set((schema.get("properties") or {}).keys())
        required = set(schema.get("required") or [])
        given = set(_KWARG.findall(arglist))

        unknown = sorted(given - props)
        if unknown:
            problems.append(
                "%s(%s): no such parameter %s — the schema takes %s"
                % (name, arglist.strip(), ", ".join(unknown), sorted(props) or "nothing"))

        # ⚠ `...` and a bare name stand in for a value a caller supplies, so an ellipsis
        # counts as satisfying a parameter it is written against. What it cannot do is
        # supply a REQUIRED parameter the instruction never mentions at all.
        missing = sorted(required - given)
        if missing:
            problems.append(
                "%s(%s): missing required parameter %s — not callable as written"
                % (name, arglist.strip(), ", ".join(missing)))
    return problems
