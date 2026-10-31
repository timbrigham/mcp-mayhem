"""FastMCP server exposing the DRAFTING half of publishRobot over streamable HTTP.

Run:
    PUBLISHROBOT_TRACKER=<outreach tracker.md> python -m publishrobot_server.server
    # optional: PUBLISHROBOT_DATA (queue + audit dir), PUBLISHROBOT_CONFIG (allow-list),
    #           PUBLISHROBOT_HOST (default 127.0.0.1), PUBLISHROBOT_PORT (default 8012),
    #           PUBLISHROBOT_ACTOR (default "mcp")

⛔ THERE IS NO `approve` HERE, AND A TEST FAILS IF ONE APPEARS. This server is registered
device-wide so drafting sessions can queue; approval lives on publishApprove
(`publishapprove_server`), registered only for the approving instance. Tim, 2026-10-31: a
device-wide approve fenced by a deny rule in every other session is a fence someone forgets.

⚠ THE MODULE PATH ``publishrobot_server`` IS LOAD-BEARING. The supervisor identifies a server
by process name plus a command-line substring and force-kills every match, so it must not share
a module path with sjv (``mcp_server``), gitRobot, verdictLedger or publishApprove.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcpcommon.calllog import serve as _serve_with_call_log  # noqa: E402
from mcpcommon.iserror import install as _install_is_error, install_resource_classification  # noqa: E402

from publishrobot_server.results import (  # noqa: E402
    HistoryResult, PendingResult, QueueResult, WithdrawResult)
from publishrobot_server.shared import HERE, guard as _guard  # noqa: E402

mcp = FastMCP(
    "publishRobot",
    instructions="""Queue public GitHub posts (issues, comments, labels, close-with-comment,
discussions) on allow-listed repositories. NOTHING HERE POSTS: an entry goes out only when a
human approves its exact bytes on a separate server that drafting sessions do not have.

THE FLOW: queue(...) stores the post and returns its id and every field. pending() lists what
is waiting. To change the text, withdraw the entry and queue the new text: an approval binds
the queued bytes, so an edit is always a new entry.

There are no repo-level writes here (commits, branches, PRs, merges, releases) and no route to
a repository off the allow-list. pending() and history() are plain reads.""",
    host=os.environ.get("PUBLISHROBOT_HOST", "127.0.0.1"),
    port=int(os.environ.get("PUBLISHROBOT_PORT", "8012")),
)

_install_is_error(mcp)
install_resource_classification(mcp)


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


@mcp.tool(title='Withdraw a queued post',
          annotations=ToolAnnotations(title='Withdraw a queued post', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
async def withdraw(id: str, reason: str) -> WithdrawResult:
    """Drop a queued entry so it can never be approved. Only a `queued` entry can be withdrawn."""
    return await _guard("withdraw", id, reason)


@mcp.tool(title='Posts awaiting approval',
          annotations=ToolAnnotations(title='Posts awaiting approval', readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
async def pending() -> PendingResult:
    """Every entry still `queued`, plus any stuck in `posting` (an approve that never resolved:
    check GitHub before doing anything with it). Full payloads."""
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
    description="What the server posts, how approval binds the bytes, and why approval lives on a separate server.",
    mime_type="text/markdown",
)
def _readme() -> str:
    path = HERE / "README.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        return "README could not be read at %s: %s" % (path, exc)


def main() -> None:
    _serve_with_call_log(mcp, "publishRobot")


if __name__ == "__main__":
    main()
