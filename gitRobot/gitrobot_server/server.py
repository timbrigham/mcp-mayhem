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
async def read(op: str, args: Optional[list[str]] = None, repo_mode: str = "main",
               worktree: Optional[str] = None) -> dict:
    """Run an allow-listed READ-ONLY git command. No gate, no audit, always available.

    Pass the subcommand and its arguments separately: read(op='log', args=['-5','--oneline']).
    Available: status, log, diff, show, ls-files, ls-remote, rev-parse, rev-list, cat-file,
    describe, blame, shortlog, and the read forms of config/branch/remote/worktree/stash/tag.

    Anything not on the list is REFUSED rather than passed through — that is what makes
    "not yet classified" safe by default. If you need a MUTATION use the dedicated tool.
    `repo_mode` is 'main' or '.claude-local' (a named nested repo). There is no repo path
    parameter: gitRobot acts on exactly one repository, fixed at startup.

    `worktree=<path>` reads a REGISTERED worktree instead of the main checkout — the same
    target `stage`, `unstage` and `commit` take, validated against the registered set. Use it
    to inspect the tree you are working in: an agent that can WRITE to a worktree but cannot
    READ it is pushed toward raw git, which is the one outcome this surface exists to prevent."""
    return await _guard(_robot().read, op, args, repo_mode=repo_mode, worktree=worktree)


@mcp.tool()
async def status() -> dict:
    """Tree state, branch, unpushed commit count, and what would block a push right now.

    `would_block_push` is TIP-SCOPED and cheap. It answers "would a push of THIS COMMIT be
    refused" — it does NOT walk the range, and a push publishes a range. When more than one
    commit is unpushed, `range_question` carries the exact `can_push` call that does answer it.

    ⚠ Read `would_block_push: []` as "the tip is clear", never as "the push will go". Measured
    2026-09-05: a caller healed the single item this named, ran a 27-minute preflight, got it
    green, and was refused on eleven intermediate commits this field had never mentioned."""
    return await _guard(_robot().status)


# -- Tier 2: mediated mutations -----------------------------------------------

@mcp.tool()
async def stage(paths: list[str], repo_mode: str = "main",
                worktree: Optional[str] = None) -> dict:
    """Stage NAMED paths. There is no bulk form on the main repository.

    `-A`/`.`/`-u` are refused there because background agents write to this checkout
    concurrently, so a bulk add stages files this session never touched — a scratch probe
    reached permanent history exactly that way. List what you changed; read(op='status')
    shows the candidates. `.claude-local` is exempt (bulk add is its documented flow):
    stage(paths=['-A'], repo_mode='.claude-local')."""
    return await _guard(_robot().stage, paths, repo_mode=repo_mode, worktree=worktree)


@mcp.tool()
async def unstage(paths: list[str], reason: Optional[str] = None,
                  repo_mode: str = "main", worktree: Optional[str] = None) -> dict:
    """Remove NAMED paths from the index. The WORKING TREE IS UNTOUCHED.

    The inverse of , and it exists because on this pipeline staging is a
    VERIFICATION step rather than a statement of commit intent: checkers record against
    the STAGED content, so a file must be staged to be verified — and until now there
    was no way back out. A session that verified more than it was ready to commit had
    an index it could not narrow.

    This is NOT in the Tier 1 class with reset --hard, checkout -- . and clean. Those
    are refused because they destroy uncommitted WORKING-TREE state that exists nowhere
    else. This cannot touch the working tree at all; it clears index entries and the
    files on disk are exactly as they were. What it can discard is a staged
    INTERMEDIATE that differs from the worktree — a way-point, not the work.

    Named paths only, no bulk form: background agents write to this checkout
    concurrently, so 'unstage everything' would clear entries this session never made."""
    return await _guard(_robot().unstage, paths, reason=reason, repo_mode=repo_mode,
                        worktree=worktree)


@mcp.tool()
async def commit(message_file: str, reason: Optional[str] = None,
           repo_mode: str = "main", worktree: Optional[str] = None) -> dict:
    """Commit the staged index. The message is read from a FILE, never passed as an argument.

    Prose contains newlines, quotes and non-ASCII; every one of those is a quoting hazard on
    the way to a subprocess, and a file has no such edge. Write the message with the Write
    tool, then pass its path.

    The project's pre-commit pipeline runs FIRST, so a failing gate costs you a report rather
    than a half-made commit; the installed hook then runs again during the commit as the
    backstop. There is no way to skip either — gitRobot never passes --no-verify and no
    parameter here reaches it.

    ⭐ `worktree=<path>` COMMITS FROM A WORKTREE instead of the main checkout — the basis of
    concurrent editing, since a worktree has its own HEAD, index and working tree. The path must
    be one `git worktree list` reports for this repository; anything else is refused, because the
    caller does not get to invent a path. Get one from worktree(action='add'), which also links
    the shared `.lake` so the tree can actually build.

    ⚠ THE GATE RUNS IN THE TREE BEING COMMITTED, not the main one. A worktree whose pipeline
    fails is refused even if the main checkout would pass — verifying one tree while committing
    another is exactly the mistake this project keeps finding."""
    return await _guard(_robot().commit, message_file, reason=reason, repo_mode=repo_mode,
                        worktree=worktree)


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

    RETURNS IMMEDIATELY WITH A run_id — POLL push_status(). The pre-push hook re-runs the full
    pipeline as the backstop and that takes ~25 minutes, which is ~5x the client's 300s call
    window. Held open, the call is abandoned mid-push and the audit records nothing. Same split
    preflight() has had since 2026-08-22, for the same reason.

    Every REFUSAL is still immediate and synchronous — branch shape, missing reason, and the
    ledger inventory. Only the irreversible act is backgrounded, so "not allowed" always comes
    back from the call you made.

    No force, no lease, no upstream override, no --no-verify: no parameter here reaches any of
    them, so the installed pre-push hook runs as the backstop on every push. private/* branches
    are refused outright. The reason is recorded in the audit log, which is the only durable
    record of why a publication happened."""
    return await _guard(_robot().push, branch, reason=reason, repo_mode=repo_mode,
                        wait=False)


@mcp.tool()
async def requirements(action: str = "push") -> dict:
    """⭐⭐ THE SUCCESS CONDITIONS FOR AN ACTION — what must be green, what must NOT block you,
    the preconditions, the order to do them in, and which tool answers which question.

    ⚠⚠ THE ADMISSION SET LIVES HERE, NOT IN THE LEDGER, AND ASKING THE WRONG ONE HAS A
    MEASURED COST. verdictLedger's `requirements()` returns the type REGISTRY — what may be
    RECORDED. This returns the ADMISSION SET — what must be GREEN. They are deliberately
    different and they are deliberately owned by different systems (separation of duty: if the
    ledger both recorded verdicts and decided sufficiency, one edit could lower the bar).

    Measured 2026-08-30, and it is why this tool exists: for `push` both lists are 20 entries
    and they DIFFER — the ledger marks `rely` required, gitRobot admits `build` instead. Same
    count, 19 shared, so a reader comparing sizes concludes they agree. A caller following the
    ledger's list burns rounds converging `rely`, which is excluded precisely because it is
    unsatisfiable by construction.

    Ask this before deciding what blocks you."""
    return await _guard(_robot().requirements, action)


@mcp.tool()
async def push_status() -> dict:
    """Where the last started push got to: none / running / allowed / failed / died.

    ⚠ `died` DOES NOT MEAN NOTHING WAS PUSHED. The worker is gone and no receipt was written —
    usually a server restart mid-push — but git can be killed AFTER the remote accepted the ref.
    The remote is the only authority: check read(op='ls-remote') or compare origin/<branch>
    against local BEFORE retrying. This differs from preflight_status, where a died run
    provably changed nothing."""
    return await _guard(_robot().push_status)


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
async def squash(onto: str, message_file: str, reason: str) -> dict:
    """Replace onto..HEAD with ONE commit carrying HEAD's EXISTING tree.

    ⛔ REMEDIATION ONLY — NOT A STANDARD STEP BEFORE A PUSH, and that holds regardless of
    anything below. Squashing routinely would rewrite history on every push to satisfy a rule
    that exists BECAUSE intermediate commits are fetchable, bisectable and citable forever —
    destroying the thing the gate protects — and it pushes you toward one fat commit per push,
    which is worse for review.

    ⚠⚠ THE NUMBERS HERE HAVE BEEN WRONG TWICE, SO THEY ARE STATED CAREFULLY. Measured
    2026-08-30 AFTER the six mechanical checkers moved into the pre-commit HOOK (`1da78b9`):

        pre-fix commits   11/17   stale on check_figures/invariants/moved/negatives/paths/decls
        post-fix commits  17/17   COMPLETE — the full commit admission set
        the tip           17/19   the two REVIEWS, which are never earned at commit time

    ⭐ SO AN INTERMEDIATE COMMIT NOW CARRIES ITS OWN FULL MECHANICAL SET AND HAS STOPPED BEING
    UNSATISFIABLE BY CONSTRUCTION. That is the honest claim. It is NOT "19/19": the two reviews
    are review-family by nature and correctly never recorded at commit time. Earlier versions of
    this docstring said 19/19 (generalising from `62b5b619`, a post-squash SINGLE commit that had
    received a full gate run at preflight — true of it, not of commits) and then 11/19 (true only
    before the fix). Both were corrected by ZeroParadox measuring its own tree.

    ⚠ NOTE the hook, not `batch.py precommit`: that entry point is MANUAL, and wiring recording
    there is how records end up keyed to a tree no commit ever had.

    ⚠ COMMITS MADE BEFORE THAT FIX DO NOT HEAL THEMSELVES — re-running records against CURRENT
    content, not against their trees. Two honest routes, and **prefer the first: it VERIFIES
    those commits instead of erasing them.**

    ROUTE 1 — RECORD AT EACH OLD BASIS. Run 2026-08-30 on four commits, all reaching 17/17:
    worktree(action='add', ref=<sha>), run the six there with ZPLEDGER_BASIS=INDEX and a
    per-commit ZPLEDGER_RUN, then tear down. In a clean detached worktree the index IS that
    commit's tree, so the records key to it — verified landing at four DISTINCT bases.
      ⚠ A FRESH WORKTREE HAS NO `.lake`, so check_paths WITHHOLDS (exit 3, "it skipped a class")
        rather than recording a partial PASS. Correct behaviour, and it leaves the commit at
        16/17 still blocking while five green lines suggest success. Bridge it with a directory
        JUNCTION from the worktree's `.lake` to the main checkout's.
      ⛔⛔ REMOVE THE JUNCTION BEFORE THE WORKTREE, NON-RECURSIVELY. **`git worktree remove`
        FOLLOWS JUNCTIONS AND DELETES WHAT THEY POINT AT, RETURNING 0** — measured 2026-08-30,
        target destroyed while git reported success. If it targets the pinned Mathlib, removing
        the worktree destroys the dependency. `worktree(action='remove')` now REFUSES when it
        finds a reparse point inside and names it, so the hazard is guarded rather than only
        documented — but clear the link yourself first: PowerShell
        `[System.IO.Directory]::Delete($p, $false)`, then verify the target still exists.
        ⚠ An earlier version of this note said `shutil.rmtree` made it safe. That is TRUE and
        IRRELEVANT: rmtree is the ORPHAN path; a registered worktree is removed by git. The
        safety argument was about a different code path than the one that runs — and
        `os.path.islink()` returns FALSE for a junction, so the obvious guard never fires.
      ⚠ CHECK THE RECORD LINE, NOT THE EXIT CODE. Exit 0 is not proof anything was recorded —
        this procedure demonstrated that on its own first attempt.

    ROUTE 2 — SQUASH. Genuinely the backlog case this tool is for, but it erases rather than
    answers, and it destroys any already-complete commits in the range along with the rest.

    THE MESSAGE IS READ FROM A FILE, never passed as an argument — same as commit.
    A squash message summarises N commits, so it is longer and likelier to carry prose,
    quotes and non-ASCII than an ordinary one; argv breaks on length, quoting and
    encoding. Write it to a file and pass the path.

    WHY IT EXISTS: can_push walks EVERY commit in the range, not the tip. Intermediate
    commits from a long remediation typically recorded nothing, so a push of 31 commits
    is refused 31/31 even when the tip is fully green. Measured: squashing turned
    `short 31/31` into `short 1/1`. It RELAXES NO GATE — it makes the published history
    equal to the tree that actually passed, so nothing rides along unexamined.

    VERDICTS SURVIVE IT. Coverage is content-keyed on (step, path, blob), and this
    reuses HEAD's tree OBJECT by id rather than rebuilding it, so an identical tree
    inherits every recorded verdict. Measured against a probe commit of this exact
    shape: inventory was byte-identical to HEAD's. You do NOT re-run the sweep.

    Built on commit-tree, not `reset --soft` + commit: nothing reads or writes the
    index or the working tree. REFUSED while dirty, on a detached HEAD, on an empty
    range, and — the one that matters — if any commit in the range is already on the
    remote. Confirm that yourself first with
    read(op='branch', args=['-r','--contains','<oldest sha>']); empty means unpublished.

    The receipt names old_tip. The replaced commits become unreferenced, not deleted —
    that sha is how you get them back before gc."""
    return await _guard(_robot().squash, onto, message_file, reason=reason)


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
async def ledger_subjects(observed: dict, ref: str = "INDEX") -> dict:
    """{basis, subjects, skipped} — the identity of what a gate is about to certify.

    `observed` is REQUIRED: {path: the git blob id YOU ACTUALLY READ}. This tool
    VERIFIES your reading against `ref`; it will NOT derive one for you.

    That inversion is the whole point. A deriving implementation reads the index at
    RECORD time, which for a checker is milliseconds after the read and fine — but for
    a review agent it is minutes, and the silent case is: you read blob X, the file
    changes to Y and is STAGED, and at record time index == worktree == Y so no fence
    fires and the record names Y. The verdict then certifies content nobody examined.
    Supplying what you saw makes that unrepresentable.

    `ref="INDEX"` (the default) is the case that matters — a gate reviews what is
    STAGED, before the commit exists — and it is why this is Tier 2 rather than a
    read: it runs `write-tree`, which materialises the index into tree objects. That
    touches no ref, no index and no working tree, and is idempotent for an unchanged
    index. HEAD and any tree-ish also work, for post-commit recording.

    ⚠ `skipped` is never silent. Every fenced path returns with its reason and BOTH
    blob ids — untracked, not repo-relative, or drifted since you read it. A caller
    that hands over eight paths and records four subjects without noticing has
    recorded a narrower verdict than it believes."""
    return await _guard(_robot().ledger_subjects, observed, ref=ref)


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
