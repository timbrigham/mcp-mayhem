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
import functools
from typing import Any, Optional

import anyio.to_thread

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


async def _guard(fn, *args, **kwargs) -> dict:
    """Run the operation OFF the event loop, and turn every failure into a result.

    ⚠ The offload is not an optimisation. FastMCP calls a synchronous tool
    function directly on the event loop (`func_metadata.call_fn_with_arg_validation`
    ends in a bare `return fn(...)`), so any blocking work here stalls the whole
    uvicorn server — including the health endpoint the process supervisor polls
    every 30s. Measured 2026-08-22: a ~155s gate run made the supervisor declare
    gitRobot Down and restart it, killing the run mid-flight and losing both the
    verdict and its audit trail. Every tool is therefore async and every
    operation runs on a worker thread; the loop stays free to answer probes.
    """
    try:
        return {"ok": True, **await anyio.to_thread.run_sync(
            functools.partial(fn, *args, **kwargs))}
    except RefusalError as exc:
        return {"ok": False, "error_type": "refusal", "error": str(exc),
                "alternative": exc.alternative, "refusal_id": exc.refusal_id}
    except GitRobotError as exc:
        return {"ok": False, "error_type": exc.error_type, "error": str(exc)}


# -- Tier 3: reads ------------------------------------------------------------

@mcp.tool()
async def read(op: str, args: Optional[list[str]] = None, repo_mode: str = "main") -> dict:
    """Run an allow-listed READ-ONLY git command. No gate, no audit, always available.

    Pass the subcommand and its arguments separately: read(op='log', args=['-5','--oneline']).
    Available: status, log, diff, show, ls-files, ls-remote, rev-parse, rev-list, cat-file,
    describe, blame, shortlog, and the read forms of config/branch/remote/worktree/stash/tag.

    Anything not on the list is REFUSED rather than passed through — that is what makes
    "not yet classified" safe by default. If you need a MUTATION use the dedicated tool.
    `repo_mode` is 'main' or '.claude-local' (a named nested repo). There is no repo path
    parameter: gitRobot acts on exactly one repository, fixed at startup."""
    return await _guard(_robot().read, op, args, repo_mode=repo_mode)


@mcp.tool()
async def status() -> dict:
    """Tree state, branch, unpushed commit count, and what would block a push right now.

    `would_block_push` is the useful field: it tells you before you try. Cheap; call freely."""
    return await _guard(_robot().status)


# -- Tier 2: mediated mutations -----------------------------------------------

@mcp.tool()
async def stage(paths: list[str], repo_mode: str = "main") -> dict:
    """Stage NAMED paths. There is no bulk form on the main repository.

    `-A`/`.`/`-u` are refused there because background agents write to this checkout
    concurrently, so a bulk add stages files this session never touched — a scratch probe
    reached permanent history exactly that way. List what you changed; read(op='status')
    shows the candidates. `.claude-local` is exempt (bulk add is its documented flow):
    stage(paths=['-A'], repo_mode='.claude-local')."""
    return await _guard(_robot().stage, paths, repo_mode=repo_mode)


@mcp.tool()
async def commit(message_file: str, reason: Optional[str] = None,
           repo_mode: str = "main") -> dict:
    """Commit the staged index. The message is read from a FILE, never passed as an argument.

    Prose contains newlines, quotes and non-ASCII; every one of those is a quoting hazard on
    the way to a subprocess, and a file has no such edge. Write the message with the Write
    tool, then pass its path.

    The project's pre-commit pipeline runs FIRST, so a failing gate costs you a report rather
    than a half-made commit; the installed hook then runs again during the commit as the
    backstop. There is no way to skip either — gitRobot never passes --no-verify and no
    parameter here reaches it."""
    return await _guard(_robot().commit, message_file, reason=reason, repo_mode=repo_mode)


@mcp.tool()
async def preflight(reason: Optional[str] = None) -> dict:
    """START the full pre-push pipeline WITHOUT pushing. Returns IMMEDIATELY.

    ⚠ Run this BEFORE push — push refuses without it. A gate that runs inside the push has a
    zero-length response window: the push completes in the same invocation, so the findings
    arrive after the irreversible act. This splits the verdict from the act.

    ⚠⚠ It does NOT wait. The pipeline takes ~155s on the real repo, which outlives both the
    call window and the process supervisor's 30s health poll — held open, it gets the server
    killed mid-run. So this returns a run_id straight away and the pipeline continues in the
    background; poll `preflight_status()` for the verdict. push stays refused until a run
    lands green for the CURRENT HEAD, so committing again invalidates it."""
    return await _guard(_robot().preflight, reason=reason)


@mcp.tool()
async def preflight_status() -> dict:
    """The state of the latest preflight for the current HEAD.

    'running' / 'passed' / 'failed' / 'died' / 'none'. 'died' means a run was interrupted
    (its process is gone) and never recorded a verdict — worth having as its own state,
    because "it failed" and "it never ran" are different facts and only one of them means
    the gate actually judged your tree."""
    return await _guard(_robot().preflight_status)


@mcp.tool()
async def push(branch: str, reason: str, repo_mode: str = "main") -> dict:
    """Push a branch. On the main repo: requires a passing preflight() for the CURRENT HEAD.

    repo_mode='.claude-local' pushes that nested repository to its OWN remote instead. It is a
    genuinely separate repo with its own history and no gate pipeline, so no preflight is
    required there — demanding a verdict from a pipeline that does not exist would make the
    operation permanently unreachable rather than safe. Reason and audit still apply.

    No force, no lease, no upstream override, no --no-verify: no parameter here reaches any of
    them, so the installed pre-push hook runs as the backstop on every push. private/* branches
    are refused outright. The reason is recorded in the audit log, which is the only durable
    record of why a publication happened."""
    return await _guard(_robot().push, branch, reason=reason, repo_mode=repo_mode)


@mcp.tool()
async def fetch(prune: bool = False, reason: Optional[str] = None,
                repo_mode: str = "main") -> dict:
    """Update remote-tracking refs from origin. Touches no working file, no local branch.

    Run it before pushing so you know whether the remote moved. It cannot destroy anything
    — it is mediated rather than a plain read only because it goes to the network and
    writes refs, and those get an audit row."""
    return await _guard(_robot().fetch, prune=prune, reason=reason, repo_mode=repo_mode)


@mcp.tool()
async def switch(branch: str, create: bool = False, reason: Optional[str] = None) -> dict:
    """Move HEAD to another branch (create=True makes it). REFUSED while the tree is dirty.

    Git already blocks a switch that would overwrite a file. What this catches is the
    quieter case: carrying uncommitted work across a branch change so it later gets
    committed on a branch it was never written for. There is no acknowledgement flag —
    commit the work, or take a worktree. Both leave it somewhere a person can find it."""
    return await _guard(_robot().switch, branch, create=create, reason=reason)


@mcp.tool()
async def merge(branch: str, reason: str) -> dict:
    """Merge a branch into HEAD (--no-ff). REFUSED while the tree is dirty; reason required.

    No squash, no strategy overrides, no --no-verify: a merge needing those is a decision,
    not a mechanical step."""
    return await _guard(_robot().merge, branch, reason=reason)


@mcp.tool()
async def rebase(onto: str, reason: str) -> dict:
    """Rebase HEAD onto a ref. REFUSED while dirty, and refused if it would rewrite commits
    that are ALREADY on the remote.

    That second guard is the important one: rewriting published history breaks every
    checkout that already has it, and the damage only surfaces when someone else pulls.
    gitRobot cannot make that safe, so it declines to be what made it easy — use merge."""
    return await _guard(_robot().rebase, onto, reason=reason)


@mcp.tool()
async def branch_delete(name: str, reason: str) -> dict:
    """Delete a branch — SAFE delete only. Reason required.

    A branch whose commits are not merged anywhere is REFUSED rather than force-deleted:
    those commits would survive only in the reflog, which expires. Merge or tag them first.
    There is no force-delete here and no parameter that reaches one."""
    return await _guard(_robot().branch_delete, name, reason=reason)


@mcp.tool()
async def tag_create(name: str, reason: str, message_file: Optional[str] = None) -> dict:
    """Create an annotated tag. There is deliberately NO tag deletion.

    A pushed tag is a public marker other things reference — here, releases mint permanent
    DOIs. Removing one is not an agent decision, so the verb does not exist; supersede a
    wrong tag with a corrected one."""
    return await _guard(_robot().tag_create, name, reason=reason, message_file=message_file)


@mcp.tool()
async def remove_files(paths: list[str], reason: str, cached: bool = False,
                       repo_mode: str = "main") -> dict:
    """`git rm` on NAMED paths. No bulk form, reason required.

    cached=True untracks the file but leaves it on disk. Without it the file is deleted, so
    a path carrying uncommitted modifications is REFUSED — git would need -f to discard
    them, and -f is not available here."""
    return await _guard(_robot().remove_files, paths, reason=reason, cached=cached,
                        repo_mode=repo_mode)


@mcp.tool()
async def worktree(action: str, ref: Optional[str] = None, name: Optional[str] = None) -> dict:
    """Private throwaway checkouts — the sanctioned alternative to every refused operation.

    action='add' (ref defaults to HEAD) creates a detached worktree under a scratch area
    OUTSIDE the repository, with its own HEAD, index and working tree: nothing done there can
    reach the caller's files. action='list' shows them; action='remove' with the path from
    add tears one down. This is the answer whenever you want a clean slate — it is why
    reset --hard, checkout -- ., clean and stash are refused rather than merely discouraged.

    action='remove' also accepts any path git itself lists as a worktree of this repo (never
    the main checkout), so leftovers from other sessions can be cleaned up. action='prune'
    drops the administrative records of worktrees whose directories are already gone."""
    return await _guard(_robot().worktree, action, ref=ref, name=name)


# -- Explanation + the log ----------------------------------------------------

@mcp.tool()
async def explain(refusal_id: str) -> dict:
    """Why an operation was refused, and exactly what discharges it.

    Every refusal returns a `refusal_id`; pass it here for the long form."""
    return await _guard(_robot().explain, refusal_id)


@mcp.tool()
async def history(limit: int = 20, full: bool = False, op: Optional[str] = None,
                  decision: Optional[str] = None) -> dict:
    """The append-only operation log: every mutating call, ALLOWED OR REFUSED.

    The refused half matters as much as the allowed half - a log that only records successes
    cannot answer "did this guard ever fire?", which is the question that matters after an
    incident. Tier 3 reads are not logged; they change nothing.

    SUMMARY BY DEFAULT: ts, op, decision, head, branch, actor, reason - one line per
    operation. GRB-4 measured limit=30 returning 194,296 characters across 818 lines,
    which had to be dumped to a file and grepped; a tool that must be post-processed
    to be used has the wrong default. `full=True` returns the whole record, and the
    count of anything omitted is always reported.

    Filter with `op=` ("push", "commit", ...) or `decision=` ("refused", "allowed")
    to answer the incident question directly rather than by reading everything."""
    return await _guard(_robot().history, limit=limit, full=full, op=op,
                        decision=decision)


def main() -> None:
    # Fail loudly at startup if the configured repository is not there, rather
    # than mysteriously on the first call.
    GitRobot(REPO, data_path=DATA, actor=ACTOR).git.require_repo()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
