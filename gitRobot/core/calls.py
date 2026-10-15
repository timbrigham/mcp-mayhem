"""One compact row per MCP tool call, reads included: which call, from which client call id.

Added 2026-10-15 for the guard-coverage metric, whose unit changed from an MCP session to an
AGENT INSTANCE (one agent context, such as a subagent). Approved by Tim; logging only, nothing
allowed or refused changes.

Why a second log rather than more fields on the audit rows:

  - The audit (`core/audit.py`) skips Tier 3 reads by design, but the metric's denominator must
    count every instance that called gitRobot at all, and many subagents only read.
  - The HTTP call log (`mcpcommon/calllog.py`) does carry the id, but it ROTATES and deletes its
    oldest file in about a day. A rotating file cannot carry a count over weeks.
  - And neither recorded the client's own per-call id. Measured 2026-10-14: gitRobot logged
    2026-10-13 15:02Z .. 10-14 22:46Z as ONE MCP session, because one long-lived Claude Code
    process (kept across a /clear) spawned 283 subagents over one connection. The session id
    cannot tell them apart; the per-call id can be traced to the agent that made the call.

What a row holds, and what it deliberately does not:

    ts               UTC, with offset
    tool             the tool name
    surface, session, versions     exactly as the audit rows carry them (core/callctx.py)
    client_call_id   the client's own id for this call, from the request's `_meta`, or null.
                     Claude Code's key is "claudecode/toolUseId". The field name is generic
                     because other clients may send their own.
    client_call_id_state   present | absent (no known key) | unusable (a known key whose value
                     is not a string of 1..MAX_CALL_ID characters): "sent nothing" and "sent
                     something unusable" are different facts, and both leave the id null
    outcome          how the CALL ended, from CALL_OUTCOMES below. ⚠ Deliberately NOT the audit
                     rows' `decision`: its published `failed` means "it ran and git returned
                     non-zero", and many calls here end in an error without running anything
    error_type       null on success, else the refusal's or error's published type
    exception        null unless an exception propagated out of the tool: its class name
    refusal_id       null unless the refusal carried one. ⚠ NOT A UNIQUE KEY: it hashes the op
                     and the refusal text, so a retried refusal repeats it, and the commit and
                     merge gates raise without one. Join a refusal to its audit rows by
                     `client_call_id`, which the audit rows now carry too (core/callctx.py).
                     ⚠ ONE CALL, POSSIBLY SEVERAL AUDIT ROWS: a gate refusal writes more than
                     one, and a preflight or push writes its `started` row and, later on its
                     own thread, its completion row, all carrying the initiating call's id.

Calls that never reach the tool function write NO row: arguments rejected by schema or pydantic
validation, and unknown tool names. The HTTP call log still sees them. The CLI writes none
either: this log describes the MCP surface only.

NO ARGUMENTS AND NO RESULT. Arguments carry consumer content (paths, reasons), and the audit
already keeps them for every mutation. This log answers who called and how it ended, nothing more.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from core import callctx as _callctx
from core.audit import _now_iso

# The `_meta` keys a client's per-call id may arrive under, first match wins. Recorded as given;
# a key not listed here is a client this log cannot attribute, which reads as null, not as an error.
CLIENT_CALL_ID_KEYS = ("claudecode/toolUseId",)

FILENAME = "tool_calls.jsonl"

# How a call ended. Bound: `append` raises on any other value, so the set a reader enumerates is
# the set the code can write. Kept here, not in mcpcommon.vocabulary: only this log uses it, and
# publishing it would change what every server's vocabulary() serves.
CALL_OUTCOMES = {
    "returned": "the tool returned a result: the operation ran.",
    "refused": ("gitRobot declined (a RefusalError, a gate included): nothing was changed by "
                "the refused operation. error_type is 'refusal'."),
    "error": ("the tool returned an error result other than a refusal; error_type names it. "
              "The operation may or may not have started."),
    "raised": ("an exception propagated out of the tool, a cancellation included; `exception` "
               "names its class. The operation may never have started."),
}

# A client controls this value. Anything longer is not an id we know how to read, and is
# recorded as null rather than written at whatever size the client chose.
MAX_CALL_ID = 256

_LOCK = threading.Lock()


def client_call_id(meta) -> tuple:
    """(id or None, state) from a request's `_meta` (a pydantic model allowing extra keys, or a
    dict). state: present | absent | unusable. Never raises: attribution must not break a call."""
    if meta is None:
        return None, "absent"
    try:
        extra = meta if isinstance(meta, dict) else (getattr(meta, "model_extra", None) or {})
        for key in CLIENT_CALL_ID_KEYS:
            if key in extra:
                value = extra[key]
                if isinstance(value, str) and 0 < len(value) <= MAX_CALL_ID:
                    return value, "present"
                return None, "unusable"
    except Exception:
        return None, "unusable"
    return None, "absent"


def path_beside(audit_path) -> Path:
    """The call log lives beside the audit log, so one data directory holds both."""
    return Path(audit_path).parent / FILENAME


def append(path, *, tool: str, call_id: Optional[str], call_id_state: str, outcome: str,
           error_type: Optional[str] = None, refusal_id: Optional[str] = None,
           exception: Optional[str] = None) -> dict:
    """Append one row and return it. Keys are always present, null when unknown."""
    if outcome not in CALL_OUTCOMES:
        raise AssertionError("outcome %r is not in CALL_OUTCOMES" % (outcome,))
    if call_id_state not in ("present", "absent", "unusable") or \
            (call_id_state == "present") != (call_id is not None):
        raise AssertionError("call_id_state %r does not describe call_id %r"
                             % (call_id_state, call_id))
    caller = _callctx.current()
    row = {
        "ts": _now_iso(),
        "tool": tool,
        "surface": caller["surface"],
        "session": caller["session"],
        "client_call_id": call_id,
        "client_call_id_state": call_id_state,
        "outcome": outcome,
        "error_type": error_type,
        "exception": exception,
        "refusal_id": refusal_id or None,
        "versions": caller["versions"],
        "pid": os.getpid(),
    }
    path = Path(path)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
    return row
