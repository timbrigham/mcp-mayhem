"""FastMCP server exposing gitRobot over streamable HTTP.

Run:
    GITROBOT_REPO=C:\\Workspace\\ZeroParadox python -m gitrobot_server.server
    # optional: GITROBOT_DATA, GITROBOT_HOST (default 127.0.0.1),
    #           GITROBOT_PORT (default 8010), GITROBOT_ACTOR (default "mcp")

⚠ THE MODULE PATH ``gitrobot_server`` IS LOAD-BEARING — never ``mcp_server``.
The process supervisor identifies a running server by process name plus a
command-line substring, with no working-directory or port filter. The sibling
registry already runs ``python -m mcp_server.server``; a second server on that
module path would be indistinguishable from it, and a gitRobot repair would have
targeted and killed the registry instead.

⚠ It enforces nothing itself. Every tool call delegates to ``core``, which owns
tier classification, the gate pipeline, git invocation and the audit log. If this
server is down the rules still exist and ``python -m core.cli`` still applies
them — the availability cost is that agent git is unavailable, which is why Tier 3
reads depend on nothing but a subprocess call.

Absent by design, and asserted absent by a test: no force, no no_verify, no
skip_gates, no allow_dirty, no repo, no raw passthrough. A control nobody has
seen fail is a hypothesis.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from core.engine import GitRobot
from core.errors import GitRobotError, RefusalError

REPO = os.environ.get("GITROBOT_REPO", r"C:\Workspace\ZeroParadox")
DATA = os.environ.get("GITROBOT_DATA", "data/git_ops.jsonl")
ACTOR = os.environ.get("GITROBOT_ACTOR", "mcp")

mcp = FastMCP(
    "gitRobot",
    host=os.environ.get("GITROBOT_HOST", "127.0.0.1"),
    port=int(os.environ.get("GITROBOT_PORT", "8010")),
)


def _robot() -> GitRobot:
    # Fresh per call so it always reflects the tree as it is now.
    return GitRobot(REPO, data_path=DATA, actor=ACTOR)


def _guard(fn, *args, **kwargs) -> dict:
    """Every failure becomes a structured result, never a transport crash."""
    try:
        return {"ok": True, **fn(*args, **kwargs)}
    except RefusalError as exc:
        return {"ok": False, "error_type": "refusal", "error": str(exc),
                "alternative": exc.alternative, "refusal_id": exc.refusal_id}
    except GitRobotError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc)}


# -- Tier 3: reads ------------------------------------------------------------

@mcp.tool()
def read(op: str, args: Optional[list[str]] = None, repo_mode: str = "main") -> dict:
    """Run an allow-listed READ-ONLY git command. No gate, no audit, always available.

    Pass the subcommand and its arguments separately: read(op='log', args=['-5','--oneline']).
    Available: status, log, diff, show, ls-files, ls-remote, rev-parse, rev-list, cat-file,
    describe, blame, shortlog, and the read forms of config/branch/remote/worktree/stash/tag.

    Anything not on the list is REFUSED rather than passed through — that is what makes
    "not yet classified" safe by default. If you need a MUTATION use the dedicated tool.
    `repo_mode` is 'main' or '.claude-local' (a named nested repo). There is no repo path
    parameter: gitRobot acts on exactly one repository, fixed at startup."""
    return _guard(_robot().read, op, args, repo_mode=repo_mode)


@mcp.tool()
def status() -> dict:
    """Tree state, branch, unpushed commit count, and what would block a push right now.

    `would_block_push` is the useful field: it tells you before you try. Cheap; call freely."""
    return _guard(_robot().status)


# -- Tier 2: mediated mutations -----------------------------------------------

@mcp.tool()
def stage(paths: list[str], repo_mode: str = "main") -> dict:
    """Stage NAMED paths. There is no bulk form on the main repository.

    `-A`/`.`/`-u` are refused there because background agents write to this checkout
    concurrently, so a bulk add stages files this session never touched — a scratch probe
    reached permanent history exactly that way. List what you changed; read(op='status')
    shows the candidates. `.claude-local` is exempt (bulk add is its documented flow):
    stage(paths=['-A'], repo_mode='.claude-local')."""
    return _guard(_robot().stage, paths, repo_mode=repo_mode)


@mcp.tool()
def commit(message_file: str, reason: Optional[str] = None,
           repo_mode: str = "main") -> dict:
    """Commit the staged index. The message is read from a FILE, never passed as an argument.

    Prose contains newlines, quotes and non-ASCII; every one of those is a quoting hazard on
    the way to a subprocess, and a file has no such edge. Write the message with the Write
    tool, then pass its path.

    The project's pre-commit pipeline runs FIRST, so a failing gate costs you a report rather
    than a half-made commit; the installed hook then runs again during the commit as the
    backstop. There is no way to skip either — gitRobot never passes --no-verify and no
    parameter here reaches it."""
    return _guard(_robot().commit, message_file, reason=reason, repo_mode=repo_mode)


@mcp.tool()
def preflight(reason: Optional[str] = None) -> dict:
    """Run the full pre-push pipeline WITHOUT pushing, and record the verdict.

    ⚠ Run this BEFORE push — push refuses without it. That is deliberate: a gate that runs
    inside the push has a zero-length response window, because the push completes in the same
    invocation and the findings arrive after the irreversible act. This splits the verdict
    from the act so you can still do something about it.

    The result is bound to the HEAD it ran against, so committing again invalidates it. Slow
    by nature — it is the real pipeline, not a summary of it."""
    return _guard(_robot().preflight, reason=reason)


@mcp.tool()
def push(branch: str, reason: str) -> dict:
    """Push a branch. Requires a passing preflight() for the CURRENT HEAD, and a reason.

    No force, no lease, no upstream override, no --no-verify: no parameter here reaches any
    of them, so the installed pre-push hook runs as the backstop on every push. private/*
    branches are refused outright. The reason is recorded in the audit log, which is the only
    durable record of why a publication happened."""
    return _guard(_robot().push, branch, reason=reason)


@mcp.tool()
def worktree(action: str, ref: Optional[str] = None, name: Optional[str] = None) -> dict:
    """Private throwaway checkouts — the sanctioned alternative to every refused operation.

    action='add' (ref defaults to HEAD) creates a detached worktree under a scratch area
    OUTSIDE the repository, with its own HEAD, index and working tree: nothing done there can
    reach the caller's files. action='list' shows them; action='remove' with the path from
    add tears one down. This is the answer whenever you want a clean slate — it is why
    reset --hard, checkout -- ., clean and stash are refused rather than merely discouraged."""
    return _guard(_robot().worktree, action, ref=ref, name=name)


# -- Explanation + the log ----------------------------------------------------

@mcp.tool()
def explain(refusal_id: str) -> dict:
    """Why an operation was refused, and exactly what discharges it.

    Every refusal returns a `refusal_id`; pass it here for the long form."""
    return _guard(_robot().explain, refusal_id)


@mcp.tool()
def history(limit: int = 20) -> dict:
    """The append-only operation log: every mutating call, ALLOWED OR REFUSED.

    The refused half matters as much as the allowed half — a log that only records successes
    cannot answer "did this guard ever fire?", which is the question that matters after an
    incident. Tier 3 reads are not logged; they change nothing."""
    return _guard(_robot().history, limit=limit)


def main() -> None:
    # Fail loudly at startup if the configured repository is not there, rather
    # than mysteriously on the first call.
    GitRobot(REPO, data_path=DATA, actor=ACTOR).git.require_repo()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
