"""The verdictLedger client, and the admission set that says what gates an action.

⚠⚠ THIS EXISTS BECAUSE OF A MEASURED FAILURE (2026-08-23). A push of `55f2d6a` was
ALLOWED — 19 blocking checks green, preflight passed, audited, pushed — while the
ledger's inventory for that exact hash reported `0/19 keys, complete: false`. Two
systems, opposite answers, and the enforcement point never asked.

`push` REQUIRED a passing `preflight()`, `preflight` ran `hooks.py pre-push`, and
that read exit codes and `*_cleared.txt`. **The ledger was never consulted.** This
module is that wire, and the preflight precondition is gone -- it was a second
answer to the same question, and the weaker of two answers is the one that lets
things through.

⚠ TWO LISTS, NOT TWO COPIES. The ledger owns the REGISTRY (what may be recorded,
how `complete` is computed, every threshold). gitRobot owns only the ADMISSION SET
— which type names gate which action. That is a deliberate, narrow reversal of
"no policy values in gitRobot": the argument is separation of duty, so lowering
the bar takes edits in two systems rather than one. gitRobot still never
re-derives completeness; it names the set and requires the ledger's answer.

⚠ Reached over loopback MCP with nothing but the standard library — same three
POSTs as the ZeroParadox checker client. No `mcp` dependency here either.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from core.errors import GitRobotError

URL = os.environ.get("GITROBOT_LEDGER_URL", "http://127.0.0.1:8011/mcp")
TIMEOUT = float(os.environ.get("GITROBOT_LEDGER_TIMEOUT", "60"))

_HEADERS = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}


class LedgerUnreachable(GitRobotError):
    """⚠ Its own error type, deliberately. A caller debugging at 2am must be able
    to tell "the ledger is down" from "policy said no" — and the remedy for the
    first is to start a server, not to argue with a gate."""

    error_type = "ledger_unreachable"


def _post(payload, session=None):
    headers = dict(_HEADERS)
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.headers.get("Mcp-Session-Id"), resp.read().decode("utf-8")


def _parse(body):
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(body) if body.strip() else None


def call(tool: str, arguments: dict) -> dict:
    """One MCP round trip. Raises LedgerUnreachable rather than returning a value
    that could be mistaken for an answer."""
    try:
        sid, body = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "gitRobot", "version": "1"}}})
        _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session=sid)
        _, body = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": tool, "arguments": arguments}}, session=sid)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise LedgerUnreachable(
            f"verdictLedger is not answering at {URL} ({exc}). This action is REFUSED — "
            f"never allowed on the old exit-code path, because that fallback is the "
            f"two-route design returning through the back door and the weaker route wins "
            f"exactly when you least want it to. Start the server."
        ) from exc

    res = _parse(body)
    if not res or "result" not in res:
        raise LedgerUnreachable(f"verdictLedger returned no usable payload for {tool!r}")
    content = res["result"].get("content") or []
    if not content:
        raise LedgerUnreachable(f"verdictLedger returned an empty result for {tool!r}")
    try:
        return json.loads(content[0].get("text", ""))
    except (ValueError, AttributeError) as exc:
        raise LedgerUnreachable(
            f"verdictLedger returned unparseable content for {tool!r}") from exc


# -- the admission set ---------------------------------------------------------

DEFAULT_ADMISSION = Path(__file__).resolve().parents[1] / "config" / "admission.v1.json"


def admission_for(action: str, path=None) -> list:
    """Which registered types must be green to let `action` through.

    ⚠ EXPLICIT, NEVER DEFAULTED. A type gates because it was NAMED here, not because
    it exists in the registry. Defaulting to "every registered type gates" would brick
    the push path with checks nobody chose.

    ⚠⚠ BUT AN EMPTY LIST IS NOT A RESTING STATE. `push` refuses outright when this
    returns [] for the main repo (see engine._require_inventory). Those two rules are
    not in tension: the first says WHICH types gate, the second says the list may not
    be empty. An empty set means the action would be certified against zero
    requirements, which is an unchecked push with a receipt.

    ⚠ The cost of an explicit list is that a finished gate nobody promotes never
    gates, silently. That is paid for by the ledger printing the
    registered-but-not-admitting count on every allow and every refusal, so a
    promotion gap is visible on every run rather than discovered a year later.
    """
    p = Path(path or os.environ.get("GITROBOT_ADMISSION") or DEFAULT_ADMISSION)
    if not p.exists():
        raise GitRobotError(
            f"admission set not found at {p}. gitRobot refuses rather than guessing "
            f"what should gate an action — an absent list is not an empty one.")
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GitRobotError(f"admission set unreadable at {p}: {exc}") from exc
    # ⚠ The `default` is validated, not merely read. A file that quietly declared a
    # permissive default would move the bar without anyone editing a list, which is
    # exactly the single-edit lowering that separation of duty exists to prevent.
    default = doc.get("default")
    if default != "NOT_ADMITTING":
        raise GitRobotError(
            f"admission set declares default={default!r}; the only accepted value is "
            f"'NOT_ADMITTING'. An unnamed action must never be treated as unrestricted.")

    actions = doc.get("admission")
    if not isinstance(actions, dict) or action not in actions:
        raise GitRobotError(
            f"admission set names no entry for action {action!r}; it has "
            f"{sorted(actions) if isinstance(actions, dict) else 'no admission map'}. "
            f"Refusing rather than treating an unnamed action as unrestricted.")
    entry = actions[action]
    if not isinstance(entry, list):
        raise GitRobotError(f"admission[{action!r}] must be a list of type names")
    if not all(isinstance(t, str) and t for t in entry):
        raise GitRobotError(f"admission[{action!r}] must contain only type names")
    # ⚠ Duplicates are refused rather than de-duplicated. A list with a repeat is a
    # list somebody edited carelessly, and silently accepting it hides the edit.
    if len(set(entry)) != len(entry):
        dupes = sorted({t for t in entry if entry.count(t) > 1})
        raise GitRobotError(f"admission[{action!r}] repeats {dupes}; refusing an "
                            f"ambiguous set rather than de-duplicating it silently")
    return list(entry)


def can_push(rev_range: str, admission: Optional[list] = None,
             action: str = "push") -> dict:
    """⭐⭐ THE ONE QUESTION. §12-0-alpha: "these are the keys needed, does commit xyz
    have them so we can push safely. There should be a substantial reduction in the
    amount of extra stuff to compute."

    gitRobot hands over a RANGE EXPRESSION and obeys the answer. It does not resolve
    the commits, does not assemble a file list, does not hash anything, and does not
    re-derive completeness. Every one of those would be a second implementation
    waiting to disagree with the first — which is the failure of 2026-08-23.
    """
    if admission is None:
        admission = admission_for(action)
    # ⚠ BOTH SETS, because the range holds two kinds of subject. The tip is what gets
    # published and carries the push bar; the commits under it are judged by the bar
    # that applied when they were made. Sending only the push set made every
    # intermediate commit owe three agent rounds -- unsatisfiable, not strict.
    return call("can_push", {"rev_range": rev_range, "action": action,
                             "admission": admission,
                             "commit_admission": admission_for("commit")})


def inventory(ref: str, action: str, admission: Optional[list] = None) -> dict:
    """Ask the ledger to evaluate `ref` against the admission set for `action`.

    ⚠ gitRobot does NOT compute completeness. It names the set, the ledger
    evaluates, and gitRobot requires the answer to be `complete`. A second
    completeness implementation would be the mirror defect at the highest-stakes
    site in the system.
    """
    if admission is None:
        admission = admission_for(action)
    return call("inventory", {"action": action, "ref": ref, "admission": admission})


def admission_doc(path=None) -> dict:
    """The whole admission document, including its `_`-prefixed rationale keys.

    ⚠ `admission_for` returns one list because that is all the gate needs. This returns the
    document so `requirements()` can quote WHY a registered type was excluded, in the words
    already written next to the exclusion, rather than a second explanation that drifts."""
    p = Path(path or os.environ.get("GITROBOT_ADMISSION") or DEFAULT_ADMISSION)
    if not p.exists():
        raise GitRobotError(f"admission set not found at {p}.")
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GitRobotError(f"admission set unreadable at {p}: {exc}") from exc
