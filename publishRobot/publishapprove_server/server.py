"""FastMCP server exposing ONE tool, `approve`, over streamable HTTP.

Run (same PUBLISHROBOT_* environment as publishRobot, so both read one queue):
    PUBLISHROBOT_TRACKER=<outreach tracker.md> python -m publishapprove_server.server
    # optional: PUBLISHAPPROVE_HOST (default 127.0.0.1), PUBLISHAPPROVE_PORT (default 8013)

⛔⛔ THE FENCE IS WHO HAS THIS SERVER REGISTERED, NOT ANYTHING IN THIS FILE. Register it with
`claude mcp add --scope local` from the approving instance's project only, and put an `ask` rule
on `mcp__publishApprove__approve` there, so every call prompts the human. A drafting session
never has the tool, which is a stronger fence than a deny rule it would need to remember.
⚠ HTTP, not stdio, by Tim's standing preference (stdio has been unreliable). The port is
reachable by local processes; the fleet's threat model does not defend localhost ports.

⚠ The module path ``publishapprove_server`` must stay unique across the supervisor's servers.
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

from publishrobot_server.results import ApproveResult  # noqa: E402
from publishrobot_server.shared import guard as _guard  # noqa: E402

mcp = FastMCP(
    "publishApprove",
    instructions="""Approve and send a post queued on publishRobot. ONE tool: approve.

Restate EVERY field exactly as publishRobot's pending() shows it. The arguments are what the
approving human reads in the permission prompt, and the server refuses any difference from the
queued copy, so what is shown is what is posted. An entry posts once. A refused approve is
terminal: re-read pending(), and queue changed text as a new entry.""",
    host=os.environ.get("PUBLISHAPPROVE_HOST", "127.0.0.1"),
    port=int(os.environ.get("PUBLISHAPPROVE_PORT", "8013")),
)

_install_is_error(mcp)
install_resource_classification(mcp)


@mcp.tool(title='Approve and post a queued post',
          annotations=ToolAnnotations(title='Approve and post a queued post', readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
async def approve(id: str, action: str, repo: str, number: Optional[int] = None,
                  title: Optional[str] = None, body: Optional[str] = None,
                  labels: Optional[list[str]] = None, remove_labels: Optional[list[str]] = None,
                  category: Optional[str] = None, reply_to: Optional[str] = None,
                  state_reason: Optional[str] = None) -> ApproveResult:
    """POST a queued entry PUBLICLY. Restate every field exactly as pending() shows it.

    The server compares each argument with the queued copy and refuses on any difference, then
    posts the stored bytes once. Returns the URL, and the tracker line it appended."""
    return await _guard("approve", id, action, repo, number=number, title=title, body=body,
                        labels=labels, remove_labels=remove_labels, category=category,
                        reply_to=reply_to, state_reason=state_reason)


def main() -> None:
    _serve_with_call_log(mcp, "publishApprove")


if __name__ == "__main__":
    main()
