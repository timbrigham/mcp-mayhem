"""FastMCP server exposing publishRobot over streamable HTTP.

Run:
    PUBLISHROBOT_TRACKER=<outreach tracker.md> python -m publishrobot_server.server
    # optional: PUBLISHROBOT_DATA (queue + audit dir), PUBLISHROBOT_CONFIG (allow-list),
    #           PUBLISHROBOT_HOST (default 127.0.0.1), PUBLISHROBOT_PORT (default 8012),
    #           PUBLISHROBOT_ACTOR (default "mcp")

⚠ THE MODULE PATH ``publishrobot_server`` IS LOAD-BEARING. The supervisor identifies a server
by process name plus a command-line substring and force-kills every match, so it must not share
a module path with sjv (``mcp_server``), gitRobot or verdictLedger.

⛔ `approve` IS ONLY AS STRONG AS THE PERMISSION RULES AROUND IT, and those live in the CLIENTS'
settings, not here: an `ask` rule wherever Tim approves, a `deny` in every drafting session.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path
from typing import Optional

import anyio.to_thread

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcpcommon.calllog import serve as _serve_with_call_log  # noqa: E402
from mcpcommon.iserror import install as _install_is_error, install_resource_classification  # noqa: E402

from publishrobot_server.results import (  # noqa: E402
    ApproveResult, HistoryResult, PendingResult, QueueResult, WithdrawResult)
from publish_core.engine import Publisher  # noqa: E402
from publish_core.errors import PublishError, RefusalError  # noqa: E402

_HERE = Path(__file__).resolve().parents[1]
DATA = os.environ.get("PUBLISHROBOT_DATA", str(_HERE / "data"))
CONFIG = os.environ.get("PUBLISHROBOT_CONFIG", str(_HERE / "config" / "publish.v1.json"))
TRACKER = os.environ.get("PUBLISHROBOT_TRACKER") or None
ACTOR = os.environ.get("PUBLISHROBOT_ACTOR", "mcp")

mcp = FastMCP(
    "publishRobot",
    instructions="""Public GitHub posts (issues, comments, labels, close-with-comment,
discussions) on allow-listed repositories, sent only when a human approves the exact bytes.

THE FLOW: queue(...) stores the post and returns an id and every field. Nothing is posted.
approve(id, ...) must restate EVERY field exactly as queued: the permission prompt is where the
human reads what will be posted, and the server refuses any difference from the stored copy.

THE MISTAKE THAT WILL BITE YOU: editing the text and re-approving the old id. An approval binds
the queued bytes; changed text is a NEW queue entry. A refused approve is terminal for that
call - do not retry it with adjusted fields, re-read pending() and queue what you mean.

There are no repo-level writes here (commits, branches, PRs, merges, releases) and no route to
a repository off the allow-list. pending() and history() are plain reads.""",
    host=os.environ.get("PUBLISHROBOT_HOST", "127.0.0.1"),
    port=int(os.environ.get("PUBLISHROBOT_PORT", "8012")),
)

_install_is_error(mcp)
install_resource_classification(mcp)


def _publisher() -> Publisher:
    return Publisher(DATA, CONFIG, tracker_path=TRACKER, actor=ACTOR)


async def _guard(tool: str, *args, **kwargs) -> dict:
    """Off the event loop (a blocking `gh` call must not stall the supervisor's health probe),
    and every deliberate failure turned into a result with its success condition."""
    try:
        fn = getattr(_publisher(), tool)
        return {"ok": True, **await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))}
    except RefusalError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc),
                "satisfied_when": exc.satisfied_when, "refusal_class": exc.refusal_class}
    except PublishError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc),
                "satisfied_when": exc.satisfied_when}


@mcp.tool(title='Queue a public post',
          annotations=ToolAnnotations(title='Queue a public post', readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def queue(action: str, repo: str, reason: str, number: Optional[int] = None,
                title: Optional[str] = None, body: Optional[str] = None,
                body_file: Optional[str] = None, labels: Optional[list[str]] = None,
                remove_labels: Optional[list[str]] = None, category: Optional[str] = None,
                reply_to: Optional[str] = None,
                state_reason: Optional[str] = None) -> QueueResult:
    """Store a post for approval. POSTS NOTHING.

    action: issue_create (title, body, labels?) - issue_comment (number, body) -
    issue_close (number, body = the closing comment, state_reason? completed|not_planned) -
    issue_label (number, labels? to add, remove_labels? to remove) -
    discussion_create (title, body, category = the category NAME) -
    discussion_comment (number, body, reply_to? = the parent comment's node id).

    Give the text as `body` or as `body_file` (read as UTF-8, a BOM dropped), not both. The
    same payload queued twice returns the existing entry rather than a second one."""
    return await _guard("queue", action, repo, reason, number=number, title=title, body=body,
                        body_file=body_file, labels=labels, remove_labels=remove_labels,
                        category=category, reply_to=reply_to, state_reason=state_reason)


@mcp.tool(title='Approve and post a queued post',
          annotations=ToolAnnotations(title='Approve and post a queued post', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
async def approve(id: str, action: str, repo: str, number: Optional[int] = None,
                  title: Optional[str] = None, body: Optional[str] = None,
                  labels: Optional[list[str]] = None, remove_labels: Optional[list[str]] = None,
                  category: Optional[str] = None, reply_to: Optional[str] = None,
                  state_reason: Optional[str] = None) -> ApproveResult:
    """POST a queued entry PUBLICLY. Restate every field exactly as pending() shows it.

    The arguments are what the approving human reads in the permission prompt; the server
    compares each with the queued copy and refuses on any difference, so what is shown is
    what is posted. An entry posts once. Returns the URL, and the tracker line it appended."""
    return await _guard("approve", id, action, repo, number=number, title=title, body=body,
                        labels=labels, remove_labels=remove_labels, category=category,
                        reply_to=reply_to, state_reason=state_reason)


@mcp.tool(title='Withdraw a queued post',
          annotations=ToolAnnotations(title='Withdraw a queued post', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def withdraw(id: str, reason: str) -> WithdrawResult:
    """Drop a queued entry so it can never be approved. Only a `queued` entry can be withdrawn."""
    return await _guard("withdraw", id, reason)


@mcp.tool(title='Posts awaiting approval',
          annotations=ToolAnnotations(title='Posts awaiting approval', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def pending() -> PendingResult:
    """Every entry still `queued`, plus any stuck in `posting` (an approve that never resolved:
    check GitHub before doing anything with it). Full payloads, so approve can be built from
    this alone."""
    return await _guard("pending")


@mcp.tool(title='Audit history',
          annotations=ToolAnnotations(title='Audit history', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def history(limit: int = 20) -> HistoryResult:
    """The last `limit` audit rows (0 for all): one per queue, approve and withdraw attempt,
    allowed or refused, with the reason."""
    return await _guard("history", limit)


@mcp.resource(
    "docs://publishrobot/readme",
    name="publishRobot README",
    title="publishRobot - public posts sent only on approval of the exact bytes",
    description="What the server posts, how approval binds the bytes, and where the permission rules that make it hold must live.",
    mime_type="text/markdown",
)
def _readme() -> str:
    path = _HERE / "README.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        return "README could not be read at %s: %s" % (path, exc)


def main() -> None:
    _serve_with_call_log(mcp, "publishRobot")


if __name__ == "__main__":
    main()
