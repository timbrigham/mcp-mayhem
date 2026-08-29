"""The mediated git operations. This module owns the policy; the MCP server is transport.

Everything enforceable lives here, so ``core`` is a working library and CLI with
no MCP installed — same separation as the sibling registry, and for the same
reason: if the server is down, the rules still exist and can still be run.

What gitRobot actually buys, stated plainly so nobody over-reads it:

  * Tier 1 operations become unreachable rather than merely discouraged.
  * Tier 2 operations cannot be run with the flags that disable their gates,
    because no parameter reaches those flags.
  * Every mutating call leaves a record, INCLUDING the refused and the clean
    ones.

It does not bind an actor who controls the machine, and must not claim to. The
only sound layer is remote — branch protection plus required status checks. This
is defence in depth.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional, Sequence

from core import ledger as ledger_client
from core import tiers
from core.audit import AuditLog
from core.errors import GitRobotError, RefusalError, RepoError, UsageError
from core.gates import Gates
from core.gitio import Git

# Where `worktree(action='add')` puts throwaway checkouts. Deliberately OUTSIDE
# the repository: a worktree inside the tree shows up as untracked content and
# invites exactly the `clean`/`reset` reflex Tier 1 refuses.
DEFAULT_SCRATCH = Path(os.environ.get("TEMP", "/tmp")) / "gitrobot-worktrees"

# `add -A` stages whatever is in the tree, including files this session never
# touched — and background agents write to the shared checkout concurrently.
# One scratch probe reached permanent history that way. Named paths only, with
# ONE named exception whose documented flow is add -A.
BULK_ADD_TOKENS = ("-A", "--all", ".", "-u", "--update", ":/", "*")
BULK_ADD_EXEMPT_REPO = ".claude-local"


def _refusal_id(op: str, detail: str) -> str:
    return hashlib.sha256(f"{op}|{detail}".encode("utf-8")).hexdigest()[:12]


def _first_segment(path: str) -> str:
    """The first path component, separator- and ``./``-normalised.

    Compared against a directory NAME, so it must be a segment match, not a prefix
    match. ``str.strip('./')`` looks right and is not: it strips a character SET,
    so it eats the leading dot of ``.claude-local`` and the comparison silently
    stops matching — which is exactly how the guard failed the first time.
    """
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.split("/", 1)[0]


class GitRobot:
    def __init__(self, repo: str | os.PathLike, *, data_path: str | os.PathLike,
                 actor: str = "cli", scratch: Optional[Path] = None):
        self.git = Git(repo)
        self.repo = self.git.repo
        self.audit = AuditLog(data_path)
        self.gates = Gates(self.repo)
        self.actor = actor
        self.scratch = Path(scratch) if scratch else DEFAULT_SCRATCH
        # Long-form refusals, keyed by id, for `explain`. In-process only: the
        # durable copy is the audit record, which `explain` falls back to.
        self._refusals: dict[str, dict] = {}

    # -- helpers ---------------------------------------------------------------

    def _target(self, repo_mode: str) -> Git:
        """The main tree, or the ONE named nested repository. Never a free path."""
        if repo_mode in ("", "main", None):
            return self.git
        if repo_mode == BULK_ADD_EXEMPT_REPO:
            return self.git.sub_repo(BULK_ADD_EXEMPT_REPO)
        raise UsageError(
            f"unknown repo mode {repo_mode!r}; expected 'main' or "
            f"{BULK_ADD_EXEMPT_REPO!r}. gitRobot does not accept repository paths."
        )

    def _refuse(self, op: str, args: Any, what: str, alternative: str, *,
                reason: Optional[str] = None, target: Optional[Git] = None) -> RefusalError:
        """Record the refusal, then return the error for the caller to raise.

        Refusals are audited exactly like allowed operations. A guard that only
        writes a record when it lets something through cannot answer "did this
        ever fire?", which is the question that matters after an incident.
        """
        rid = _refusal_id(op, what)
        self._refusals[rid] = {"op": op, "args": args, "what": what,
                               "alternative": alternative}
        git = target or self.git
        self.audit.append(
            actor=self.actor, op=op, args=args, decision="refused",
            head=git.head(), branch=git.branch(), tree=git.tree_state(),
            reason=reason, detail=f"[{rid}] {what}", alternative=alternative,
        )
        return RefusalError(f"{what}\n\nINSTEAD: {alternative}",
                            alternative=alternative, refusal_id=rid)

    def _receipt(self, op: str, args: Any, decision: str, *, gates=None,
                 reason=None, detail=None, extra: Optional[dict] = None,
                 target: Optional[Git] = None) -> dict:
        # The audit must name the tree the operation actually touched. Recording the
        # main repo's HEAD for a `.claude-local` write would be a log that lies.
        git = target or self.git
        record = self.audit.append(
            actor=self.actor, op=op, args=args, decision=decision,
            head=git.head(), branch=git.branch(), tree=git.tree_state(),
            gates=gates, reason=reason, detail=detail,
        )
        out = {"op": op, "decision": decision, "head": record["head"],
               "branch": record["branch"], "tree": record["tree"]}
        if gates:
            out["gates"] = [{k: g[k] for k in ("phase", "ran", "passed", "exit_code")}
                            for g in gates]
        out.update(extra or {})
        return out

    # =========================================================================
    # Tier 3 — reads. No gates, no audit, always available.
    # =========================================================================

    def read(self, op: str, args: Optional[Sequence[str]] = None,
             repo_mode: str = "main") -> dict:
        """Run an allow-listed read-only git command.

        Unrecognised operations are REFUSED, not passed through: the allow-list
        is what makes "everything not yet classified" safe by default.
        """
        args = list(args or [])
        if not op or not isinstance(op, str):
            raise UsageError("read requires a git subcommand, e.g. op='status'")
        if " " in op.strip():
            # A caller passing "status --porcelain" as one string is a common slip
            # and would silently miss the allow-list check on the flags.
            raise UsageError(
                f"pass the subcommand and its arguments separately: "
                f"read(op={op.split()[0]!r}, args={op.split()[1:]!r})"
            )
        bad = tiers.forbidden_token(args)
        if bad:
            raise self._refuse(
                "read", {"op": op, "args": args},
                f"{bad!r} redirects git to a different repository, work tree, hook path or "
                f"exec path, so the result would not describe the tree gitRobot guards.",
                "Drop the flag. gitRobot reads exactly one repository, configured at startup.",
            )
        if not tiers.is_read(op, args):
            allowed = ", ".join(sorted(tiers.READ_OPS))
            elsewhere = tiers.MEDIATED_ELSEWHERE.get(op)
            if elsewhere:
                # It is available, just not here. Say which door, or the caller
                # goes looking for a way around the wall instead.
                alternative = (f"That operation is mediated, not forbidden — use "
                               f"{elsewhere}. `read` is the read-only surface.")
            else:
                alternative = (
                    f"Read operations available: {allowed}. If this is a MUTATION use the "
                    f"dedicated tool. If it is genuinely a read that belongs on the list, "
                    f"say so — the list is meant to grow deliberately, which is why an "
                    f"unclassified operation is refused rather than assumed safe.")
            raise self._refuse(
                "read", {"op": op, "args": args},
                f"{('git ' + op + ' ' + ' '.join(args)).strip()!r} is not an "
                f"allow-listed read.",
                alternative,
            )
        target = self._target(repo_mode)
        result = target.run([op, *args])
        return {"op": op, "args": args, "exit_code": result.exit_code,
                "output": result.output, "ok": result.ok}

    def status(self) -> dict:
        """Tree, branch, unpushed count, and what would block a push right now."""
        blockers: list[str] = []
        tree = self.git.tree_state()
        branch = self.git.branch()
        unpushed = self.git.unpushed_count()
        if not self.gates.available():
            blockers.append("the gate pipeline is missing from this repo")

        # ⚠ `would_block_push` must be answered by THE THING THAT BLOCKS. It used to
        # report a preflight bit while push refused on something else entirely —
        # a status that says "clear" over a push that refuses is worse than no
        # status, because it sends the caller looking for a bug in the wrong system.
        inventory = None
        try:
            inventory = ledger_client.inventory(self.git.head(), "push",
                                                ledger_client.admission_for("push"))
            if inventory.get("admission_state") in ("EMPTY", "UNSET"):
                blockers.append("nothing gates a push: the admission set for 'push' is "
                                "empty, so promote a verdict type in config/admission.v1.json")
            elif not inventory.get("complete"):
                blockers.append(f"verdictLedger: {inventory.get('satisfied')}/"
                                f"{inventory.get('required')} admission keys satisfied "
                                f"for {self.git.head()[:12]}")
        except ledger_client.LedgerUnreachable as exc:
            # Reporting "clear" here would be the fail-open shape this system exists
            # to end — status must say it does not know.
            blockers.append(f"verdictLedger unreachable, so push WILL refuse: {exc}")
        except GitRobotError as exc:
            blockers.append(f"admission set unreadable, so push WILL refuse: {exc}")

        return {
            "repo": str(self.repo), "branch": branch, "head": self.git.head(),
            "tree": tree, "unpushed": unpushed,
            "gates_available": self.gates.available(),
            "inventory": inventory,
            "would_block_push": blockers,
        }

    # =========================================================================
    # Tier 1 — refused outright.
    # =========================================================================

    def guard_tier1(self, op: str, args: Sequence[str]) -> None:
        """Raise if (op, args) destroys uncommitted work in the shared tree."""
        refusal = tiers.tier1_refusal(op, list(args))
        if refusal:
            what, alternative = refusal
            raise self._refuse(op, {"args": list(args)}, what, alternative)

    # =========================================================================
    # Tier 2 — mediated.
    # =========================================================================

    def stage(self, paths: Sequence[str], repo_mode: str = "main") -> dict:
        """Stage NAMED paths. Bulk forms are refused on the main repository."""
        paths = [str(p) for p in (paths or [])]
        if not paths:
            raise UsageError("stage requires at least one path; there is no bulk form")
        target = self._target(repo_mode)
        nested = [p for p in paths if _first_segment(p) == BULK_ADD_EXEMPT_REPO]
        if nested and repo_mode == "main":
            raise self._refuse(
                "stage", {"paths": paths, "repo": repo_mode},
                f"{nested[0]!r} is inside {BULK_ADD_EXEMPT_REPO}, which is a SEPARATE "
                f"repository with its own remote. It must never become part of the "
                f"production repo — the two histories are deliberately disjoint.",
                f"Commit it in its own repo instead: "
                f"stage(paths=[…], repo_mode='{BULK_ADD_EXEMPT_REPO}') then "
                f"commit(..., repo_mode='{BULK_ADD_EXEMPT_REPO}') then "
                f"push(..., repo_mode='{BULK_ADD_EXEMPT_REPO}').",
            )
        bulk = [p for p in paths if p in BULK_ADD_TOKENS]
        if bulk and repo_mode != BULK_ADD_EXEMPT_REPO:
            raise self._refuse(
                "stage", {"paths": paths, "repo": repo_mode},
                f"{bulk[0]!r} stages everything in the tree, including files this session "
                f"never touched. Background agents write to this checkout concurrently, and a "
                f"scratch probe reached permanent history exactly this way.",
                f"List the paths you actually changed: stage(paths=['a.lean','b.md']). "
                f"Use read(op='status') to see what is outstanding. (The {BULK_ADD_EXEMPT_REPO} "
                f"repository is exempt — bulk add is its documented flow — via "
                f"repo_mode='{BULK_ADD_EXEMPT_REPO}'.)",
            )
        if bulk:
            # Only reachable for the exempt nested repo (guarded above). Normalised
            # to a single form so the audit records one thing, not six spellings.
            result = target.run(["add", "-A"])
        else:
            escaped = [p for p in paths if p.startswith("-")]
            if escaped:
                raise UsageError(
                    f"path {escaped[0]!r} looks like a flag; gitRobot passes paths only, "
                    f"never options, to git add")
            # `--` terminates options, so a file legitimately named like a flag is
            # still staged as a path and never re-read as one.
            result = target.run(["add", "--", *paths])
        if not result.ok:
            return self._receipt("stage", {"paths": paths, "repo": repo_mode}, "failed",
                                 detail=result.output, extra={"error": result.output},
                                 target=target)
        return self._receipt("stage", {"paths": paths, "repo": repo_mode}, "allowed",
                             extra={"staged": paths}, target=target)

    def unstage(self, paths, reason=None, repo_mode: str = "main") -> dict:
        """Remove NAMED paths from the index. The working tree is untouched.

        ⭐⭐ THE MISSING INVERSE OF A `stage` THAT WAS NEVER ONLY ABOUT INTENT.
        Raised by ZeroParadox 2026-08-29 and it is not a corner case: `batch.py
        precommit` records verdicts against the STAGED content, so three checkers
        exited 2 with "differs from HEAD in the worktree or index" until the files were
        staged, and the identical run then passed. **On this pipeline staging is a
        VERIFICATION step, not a statement of commit intent** — and until now there was
        no way back out of it. Any session that verifies more than it is ready to
        commit ended up with an index it could not narrow: a gate-exempt tooling change
        and a gated document could only be committed together or not at all.

        ⚠⚠ WHY NOT A `paths` PARAMETER ON `commit`, WHICH WAS THE OTHER CANDIDATE AND
        THE ONE ZeroParadox LEANED TOWARD. Measured before choosing:

            index tree (what the gate verified) : b6293d90
            commit tree (what a pathspec commit lands) : 2a1c180d

        `git commit -- <paths>` builds a TEMPORARY tree: staged content for the named
        paths, HEAD's content for everything else. So the commit does NOT carry the
        index tree, and verdictLedger records against `write-tree`. It would name a
        tree that never became a commit — §12-0-alpha's exact defect ("attesting to
        bytes that are not the ones being committed") returning through a new door, and
        it would destroy the property that a record made at the index basis SURVIVES
        the commit of that index. Clean-looking in the abstract, wrong for this system.

        ⚠ THE RISK CLASS IS GENUINELY DIFFERENT FROM TIER 1, and that is why this is
        allowed where `reset --hard` is not. Those are refused because they destroy
        UNCOMMITTED WORKING-TREE state that exists nowhere else. This cannot: measured,
        `index=v0 worktree=v2-WORKTREE` after unstaging a file staged at v1 and then
        edited. What it CAN discard is a staged INTERMEDIATE that differs from the
        worktree — above, `v1-STAGED` survives only as a dangling blob. A way-point,
        not the work, and git treats it the same way.

        ⚠ Named paths only, no bulk form, for the same reason `stage` refuses one:
        background agents write to this checkout concurrently, so "unstage everything"
        would clear entries this session never made.
        """
        paths = [str(p) for p in (paths or [])]
        if not paths:
            raise UsageError(
                "unstage requires at least one path; there is no bulk form. Naming "
                "them is the point — a bulk unstage would clear index entries this "
                "session never made, and background agents write to this checkout "
                "concurrently.")
        target = self._target(repo_mode)
        bulk = [p for p in paths if p in BULK_ADD_TOKENS]
        if bulk:
            raise self._refuse(
                "unstage", {"paths": paths, "repo": repo_mode},
                f"{bulk[0]!r} would clear the whole index, including entries this "
                f"session never staged. Background agents write to this checkout "
                f"concurrently.",
                "Name the paths you actually want out of the index: "
                "unstage(paths=['a.md'], reason='…'). read(op='status') shows what is "
                "staged.",
            )
        escaped = [p for p in paths if p.startswith("-")]
        if escaped:
            raise UsageError(
                f"path {escaped[0]!r} looks like a flag; gitRobot passes paths only, "
                f"never options, to git restore")
        # `--staged` touches the INDEX ONLY. Without it this would be `git restore`,
        # which overwrites the working tree from the index and IS a Tier 1 destroy.
        # The flag is the whole difference and it is not a caller parameter.
        result = target.run(["restore", "--staged", "--", *paths], timeout=120)
        decision = "allowed" if result.ok else "failed"
        return self._receipt(
            "unstage", {"paths": paths, "repo": repo_mode}, decision,
            reason=reason, detail=result.output,
            extra={"paths": paths, "output": result.output, "ok": result.ok},
            target=target)

    def commit(self, message_file: str, *, reason: Optional[str] = None,
               repo_mode: str = "main", run_gate: bool = True) -> dict:
        """Commit the staged index, with the message read from a FILE.

        The message never travels as an argument. A commit message is prose: it
        contains newlines, quotes, backticks and non-ASCII, and every one of those
        is a quoting hazard on the way to a subprocess. A file has no such edge.

        The project's pre-commit pipeline is run FIRST, so a failing gate costs a
        report instead of a half-made commit. The installed hook then runs again
        during ``git commit`` as the backstop — gitRobot never passes
        ``--no-verify``, and there is no parameter that could.
        """
        path = Path(message_file)
        if not path.is_absolute():
            path = self.repo / path
        if not path.exists():
            raise UsageError(f"message file not found: {path}")
        message = path.read_text(encoding="utf-8").strip()
        if not message:
            raise UsageError(f"message file is empty: {path}")

        target = self._target(repo_mode)
        if not target.run(["diff", "--cached", "--quiet"]).exit_code:
            raise self._refuse(
                "commit", {"message_file": str(path), "repo": repo_mode},
                "nothing is staged, so this commit would be empty.",
                "stage(paths=[…]) the files you changed first; read(op='status') shows them.",
                reason=reason, target=target,
            )

        gate_records = []
        if run_gate and repo_mode == "main":
            gate = self.gates.run("pre-commit")
            gate_records = [gate.record()]
            if not gate.passed:
                self.audit.append(
                    actor=self.actor, op="commit",
                    args={"message_file": str(path), "repo": repo_mode},
                    decision="refused", head=self.git.head(), branch=self.git.branch(),
                    tree=self.git.tree_state(), gates=gate_records, reason=reason,
                    detail="pre-commit gate did not pass",
                )
                raise RefusalError(
                    f"the pre-commit gate did not pass, so nothing was committed.\n\n"
                    f"{gate.note or ''}\n{gate.output[-4000:]}",
                    alternative="Fix the findings above and call commit again. The gate is the "
                                "project's own pipeline; gitRobot does not have a way to skip it "
                                "and neither do you.",
                )

        result = target.run(["commit", "--file", str(path)], timeout=600)
        decision = "allowed" if result.ok else "failed"
        return self._receipt(
            "commit", {"message_file": str(path), "repo": repo_mode}, decision,
            gates=gate_records, reason=reason, detail=result.output,
            extra={"output": result.output, "ok": result.ok}, target=target,
        )

    # -- push, and the response window ----------------------------------------

    def preflight(self, *, reason: Optional[str] = None, wait: bool = False) -> dict:
        """Start the pre-push pipeline WITHOUT pushing, and record the verdict.

        ⚠ This exists because a gate that runs during the push has a zero-length
        response window: the push completes in the same invocation, so the advice
        arrives after the irreversible act. Splitting the verdict from the act is
        the whole point — you get the findings while you can still act on them.

        ⚠⚠ IT RETURNS IMMEDIATELY AND RUNS IN THE BACKGROUND, and that is not a
        convenience. Measured 2026-08-22: this pipeline takes ~155s on the real
        repository. Held open, it outlives BOTH limits above it — the caller's
        ~120s call window, and (the one that actually bit) the process
        supervisor's 30s health poll, which saw the server unresponsive, declared
        it Down, and killed the run mid-flight. A long synchronous call here is
        not slow, it is self-destroying.

        So: a ``started`` row is written first, the pipeline runs on a worker
        thread, and the verdict is appended when it lands. Poll with
        ``preflight_status()``. ``wait=True`` blocks to completion — for the CLI,
        which has neither of those limits.

        A passing preflight is bound to the HEAD it ran against, so it cannot be
        reused across a later commit. Same idea as the project's existing
        clearance-lock-keyed-to-HEAD pattern.
        """
        head = self.git.head()
        running = self.preflight_status()
        if running.get("state") == "running":
            raise self._refuse(
                "preflight", {}, "a preflight is already running for this store.",
                "Wait for it and poll preflight_status(). Starting a second run would "
                "spend the pipeline twice and leave two verdicts racing for the same HEAD.",
                reason=reason,
            )

        run_id = _refusal_id("preflight", f"{head}|{self.audit.path}|{len(self.audit.read())}")
        self.audit.append(
            actor=self.actor, op="preflight", args={}, decision="started",
            head=head, branch=self.git.branch(), tree=self.git.tree_state(),
            reason=reason, detail="pre-push preflight started", run_id=run_id,
        )

        def _run() -> dict:
            gate = self.gates.run("pre-push")
            self.audit.append(
                actor=self.actor, op="preflight", args={},
                decision="allowed" if gate.passed else "failed",
                head=head, branch=self.git.branch(), tree=self.git.tree_state(),
                gates=[gate.record()], reason=reason,
                detail="pre-push preflight finished", run_id=run_id,
            )
            return {"op": "preflight", "run_id": run_id, "head": head,
                    "passed": gate.passed, "exit_code": gate.exit_code,
                    "note": gate.note, "output": gate.output[-8000:]}

        if wait:
            return _run()
        thread = threading.Thread(target=_run, name=f"preflight-{run_id}", daemon=True)
        thread.start()
        return {"op": "preflight", "run_id": run_id, "head": head, "state": "running",
                "note": "the pipeline runs in the background; poll preflight_status(). "
                        "push stays refused until it lands green for this HEAD."}

    def preflight_status(self) -> dict:
        """The state of the latest preflight for the current HEAD.

        ``running`` / ``passed`` / ``failed`` / ``died`` / ``none``. ``died`` is
        the one worth having: a ``started`` row whose run never wrote an outcome
        and whose pid is no longer this process is an interrupted run, and saying
        so is the difference between "it failed" and "it never ran".
        """
        head = self.git.head()
        started = self.audit.last_where(op="preflight", head=head, decision="started")
        if started is None:
            return {"state": "none", "head": head}
        run_id = started.get("run_id")
        for record in reversed(self.audit.read()):
            if record.get("run_id") == run_id and record.get("decision") in ("allowed", "failed"):
                return {"state": "passed" if record["decision"] == "allowed" else "failed",
                        "head": head, "run_id": run_id, "ts": record["ts"],
                        "gates": record.get("gates")}
        alive = any(t.name == f"preflight-{run_id}" and t.is_alive()
                    for t in threading.enumerate())
        if alive or started.get("pid") == os.getpid():
            return {"state": "running", "head": head, "run_id": run_id,
                    "started_at": started["ts"]}
        return {"state": "died", "head": head, "run_id": run_id,
                "started_at": started["ts"],
                "note": "the run was interrupted (its process is gone) and never recorded a "
                        "verdict — most likely killed mid-flight. Re-run preflight()."}

    def push(self, branch: str, *, reason: Optional[str] = None,
             repo_mode: str = "main") -> dict:
        """Push a branch. On the main repo, only if verdictLedger says so.

        THE ONLY PRECONDITION IS THE LEDGER'S INVENTORY FOR THE EXACT HASH BEING
        PUSHED. There is deliberately no second route. A preflight bit used to sit
        here too, and on 2026-08-23 the bit said pass while the ledger said 0/19 —
        when two mechanisms answer one question, the weaker one is the one that
        lets things through. `preflight` still runs the pipeline, but running the
        checks and deciding whether they passed are different jobs, and only the
        ledger does the second.

        ``repo_mode='.claude-local'`` pushes that nested repository to its own
        remote instead. It is a genuinely separate repo with a separate history, no
        gate pipeline and no verdicts, so no inventory is required there — demanding
        one would make the operation permanently unreachable rather than safe. The
        reason and the audit row still apply: those are about accountability, not
        about the gate.

        There is no force, no lease, no upstream override and no ``--no-verify``:
        the tool surface has no parameter that reaches any of them, so the
        installed pre-push hook runs as the backstop on every push gitRobot makes.
        """
        target = self._target(repo_mode)
        if not branch or not isinstance(branch, str):
            raise UsageError("push requires a branch name")
        args = {"branch": branch, "repo": repo_mode}
        if branch.startswith("-") or branch.startswith("private/"):
            raise self._refuse(
                "push", args,
                f"{branch!r} is not a pushable branch name here "
                f"(private/* never reaches a remote; a leading '-' is a flag, not a branch).",
                "Push the working branch by name, e.g. push(branch='illustrated').",
                reason=reason, target=target,
            )
        if not reason:
            raise self._refuse(
                "push", args,
                "push requires a reason.",
                "Say what this push is for in one line: push(branch=…, reason='…'). It goes "
                "in the audit log, which is the only durable record of why a publication "
                "happened.",
                target=target,
            )

        gates = None
        # ⚠⚠ THERE IS NO PREFLIGHT PRECONDITION, AND ITS REMOVAL IS THE POINT.
        # `preflight` ran the pipeline and stored ONE BIT — "passed at HEAD X" — in
        # gitRobot's own log. The ledger holds the same fact properly: every
        # requirement, per type, bound to that hash, with what it examined. Two
        # sources of truth for one question, and on 55f2d6a the bit said yes while
        # the ledger said 0/19. The weaker one is always the one that passes.
        #
        # It was also gitRobot WRITING A VERDICT, which §12d forbids. Keeping it out
        # of the ledger and putting it in git_ops.jsonl was the same defect wearing
        # a different hat.
        #
        # The response window §9 Q2 wanted is not lost: `inventory(hash)` is an
        # instant read a caller can make at any time. Re-running a 155s pipeline to
        # manufacture a bit was never what provided it.
        # The nested repo has no gate pipeline of its own, so there is no verdict to
        # demand — requiring one would make its push permanently unreachable rather
        # than safe. Reason and audit still apply: those are accountability, not gate.

        inv = None
        if repo_mode == "main":
            inv = self._require_inventory(branch, args, reason=reason, target=target)

        result = target.run(["push", "origin", branch], timeout=900)
        decision = "allowed" if result.ok else "failed"
        if inv is not None:
            # ⚠ The audit row NAMES the inventory that authorised this push and the
            # policy it was judged under, so a bar that moved later cannot
            # re-interpret a past action.
            args = {**args, "inventory_ref": inv.get("tip") or inv.get("ref"),
                    "inventory_range": inv.get("range"),
                    "commits_gated": inv.get("commits_in_range"),
                    # ⚠ RENAMED 2026-08-25: the ledger key is config_sha, because it
                    # covers the policy AND the registry. Reading the old key here
                    # would have silently written null into every push audit row --
                    # the audit still LOOKS complete, which is the shape that hides.
                    "config_sha": inv.get("config_sha"),
                    "admission": inv.get("admitted")}
        return self._receipt(
            "push", args, decision, gates=gates, reason=reason, detail=result.output,
            extra={"output": result.output, "ok": result.ok,
                   "inventory": None if inv is None else inv.get("line")},
            target=target,
        )

    def _push_range(self, branch: str, target) -> str:
        """What this push will PUBLISH, as a git range expression.

        ⚠⚠ THE RANGE, NOT HEAD, and the difference is the whole point of this method.
        A push publishes every commit the remote does not have. Measured 2026-08-23:
        a push logged `scope 1 ref(s) — range 5892cbc..55f2d6a`, 43 commits, while the
        gate asked only about HEAD. Gating the tip certifies the content that will
        EXIST while intermediate commits ride along unexamined — and they are just as
        published: fetchable, bisectable and citable forever. `crossref` measured eight
        of them NOT_RUN.

        ⚠ A BRANCH WITH NO REMOTE COUNTERPART PUBLISHES EVERYTHING NOT ALREADY ON A
        REMOTE. `origin/<branch>..<branch>` would fail to resolve, and the tempting
        fallback — "just check HEAD" — is the quiet fail-open: a brand-new branch is
        exactly when the most unexamined history lands at once.
        """
        remote = f"origin/{branch}"
        known = target.run(["rev-parse", "--verify", "--quiet", remote])
        if known.ok and known.output.strip():
            return f"{remote}..{branch}"
        return f"{branch} --not --remotes=origin"

    def _require_inventory(self, branch: str, args: Any, *, reason, target) -> dict:
        """THE HARD CONTRACT: refuse unless the ledger says every admission key is
        green for the EXACT hash being pushed.

        ⚠⚠ AT PUSH, NOT AT PREFLIGHT, and this is a trap worth naming. Measured
        2026-08-23: `preflight` logged `scope 0 ref(s)` while the push that followed
        logged `scope 1 ref(s) — range 5892cbc..55f2d6a`. **preflight validates the
        TREE; only push knows what is actually being published.** An inventory
        bolted onto preflight would certify the wrong subject — SCOPE-1 reborn
        inside the fix for it.

        ⚠ EVERY ATTEMPT, no caching. The hash is the key; if the hash moved the
        answer is recomputed. A commit between preflight and push already
        invalidates preflight, so the inventory must be at least as strict.
        """
        head = target.head()
        if not head:
            raise self._refuse(
                "push", args, "cannot resolve HEAD, so there is no hash to evaluate.",
                "Commit something first.", reason=reason, target=target)

        rev_range = self._push_range(branch, target)
        try:
            inv = ledger_client.can_push(rev_range)
        except ledger_client.LedgerUnreachable:
            raise
        except GitRobotError as exc:
            raise self._refuse(
                "push", args, f"the admission set could not be read: {exc}",
                "gitRobot refuses rather than guessing what should gate a push — an "
                "absent list is not an empty one. Fix config/admission.v1.json.",
                reason=reason, target=target)

        # ⚠⚠ AN EMPTY ADMISSION SET REFUSES. It does NOT allow-with-a-warning.
        #
        # Tim, 2026-08-23: "It should have been impossible to push without having the
        # preset of requirements from verdictLedger created." An empty set IS that
        # preset not existing. The first build of this gate rendered EMPTY as ALLOWED
        # with a loud capitalised warning, which is fail-OPEN wearing the costume of
        # fail-closed — a warning nobody is obliged to act on gates nothing.
        #
        # This blocks main-repo pushes until at least one type is promoted in
        # config/admission.v1.json AND a checker records verdicts. That is the point:
        # the system should be unusable in exactly the state where it cannot tell
        # you whether anything was checked. `.claude-local` is unaffected — it never
        # reaches here.
        state = inv.get("admission_state")
        if state in ("EMPTY", "UNSET"):
            not_gating = (inv.get("not_gating")
                          or inv.get("registered_not_admitting") or [])
            named = ", ".join(sorted(not_gating)[:8]) or "none registered"
            raise self._refuse(
                "push", args,
                f"NOTHING GATES THIS PUSH. The admission set for `push` is "
                f"{'empty' if state == 'EMPTY' else 'not set'}, so verdictLedger was "
                f"asked to certify {head[:12]} against zero requirements. A push "
                f"admitted against zero requirements is not a checked push; it is an "
                f"unchecked one with a receipt.",
                f"Promote at least one verdict type into config/admission.v1.json under "
                f"'push', and make sure a checker actually records that type against "
                f"the hash being pushed. The ledger has {len(not_gating)} registered "
                f"type(s) available to promote: {named}. Registering a type is free; "
                f"gating on one is the deliberate act — which is why the empty set "
                f"cannot be treated as 'nothing required'.",
                reason=reason, target=target)

        if not inv.get("ok", True) or not inv.get("allowed"):
            # ⚠ Print the ROWS, not a count. The ledger already renders this and it
            # is genuinely actionable; summarising it here would throw away the
            # remedy per group, and the remedies differ by an order of magnitude.
            rendered = inv.get("line") or json.dumps(inv, indent=2)[:2000]
            short = (f"{inv.get('blocking_count')}/{inv.get('commits_in_range')} "
                     f"commit(s) in {rev_range}"
                     if inv.get("commits_in_range") else head[:12])
            raise self._refuse(
                "push", args,
                f"verdictLedger reports the admission set is not satisfied for "
                f"{short}.\n\n{rendered}",
                "Every required verdict must be recorded and passing for the EXACT hash "
                "being pushed. This is not advisory and there is no flag that skips it — "
                "a push allowed while the ledger said 0/19 is the failure this gate "
                "exists to prevent.",
                reason=reason, target=target)
        return inv

    # -- branch movement: refused while the tree is dirty ----------------------

    def _require_clean(self, op: str, args: Any, what: str, *,
                       reason: Optional[str] = None) -> None:
        """Refuse a branch-moving operation while uncommitted work is present.

        ⚠ NOTE A DELIBERATE DIVERGENCE FROM THE SPEC. §3 says these refuse "unless
        explicitly acknowledged". No acknowledgement parameter was built, because
        an acknowledgement flag is shaped exactly like the `force` / `allow_dirty`
        parameters §6 requires to stay ABSENT — and absence is the property that
        makes the whole design hold. The escape is not a flag, it is an action:
        commit the work, or take a worktree. Both leave the uncommitted work
        somewhere a person can still find it, which an acknowledged switch does
        not.

        Git already refuses the cases that would *overwrite* a file. What this
        catches is the quieter one: carrying uncommitted work across a branch
        change, so it ends up committed on a branch it was never written for.
        """
        if not self.git.is_dirty():
            return
        tree = self.git.tree_state()
        raise self._refuse(
            op, args,
            f"{what} while the tree is dirty ({tree['staged']} staged, "
            f"{tree['unstaged']} unstaged, {tree['untracked']} untracked). Uncommitted "
            f"work would either block the operation or be carried onto another branch "
            f"and later committed where it was never written.",
            "Either commit the work first (stage(paths=[…]) then commit(...)), or do this "
            "on a private checkout: worktree(action='add', ref=<ref>). There is no "
            "acknowledgement flag — the escape is an action that keeps your work "
            "findable, not a parameter that waves it through.",
            reason=reason,
        )

    def switch(self, branch: str, *, create: bool = False,
               reason: Optional[str] = None) -> dict:
        """Move HEAD to another branch. Refused while the tree is dirty."""
        if not branch or branch.startswith("-"):
            raise UsageError(f"{branch!r} is not a branch name")
        args = {"branch": branch, "create": create}
        self._require_clean("switch", args, f"switching to {branch!r}", reason=reason)
        argv = ["switch", "-c", branch] if create else ["switch", branch]
        result = self.git.run(argv, timeout=300)
        return self._receipt("switch", args, "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok})

    def merge(self, branch: str, *, reason: str) -> dict:
        """Merge another branch into HEAD. Refused while the tree is dirty.

        No `--no-verify`, no `--squash`, no strategy overrides: a merge that needs
        those is a decision, not a mechanical step.
        """
        if not branch or branch.startswith("-"):
            raise UsageError(f"{branch!r} is not a branch name")
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("merge requires a non-empty reason")
        args = {"branch": branch}
        self._require_clean("merge", args, f"merging {branch!r}", reason=reason)
        result = self.git.run(["merge", "--no-ff", branch], timeout=600)
        return self._receipt("merge", args, "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok})

    def rebase(self, onto: str, *, reason: str) -> dict:
        """Rebase HEAD onto another ref. Refused while dirty, AND refused when it
        would rewrite commits that are already on the remote.

        ⚠ The second guard is the one that matters. Rebasing published commits
        rewrites history other checkouts already have; the recovery is manual and
        the damage is invisible until someone else pulls. gitRobot cannot make
        that safe, so it declines to be the thing that made it easy.
        """
        if not onto or onto.startswith("-"):
            raise UsageError(f"{onto!r} is not a ref")
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("rebase requires a non-empty reason")
        args = {"onto": onto}
        self._require_clean("rebase", args, f"rebasing onto {onto!r}", reason=reason)

        published = self._published_commits_rewritten_by(onto)
        if published:
            raise self._refuse(
                "rebase", args,
                f"this would rewrite {published} commit(s) that are already on the remote. "
                f"Rewriting published history breaks every checkout that already has it, "
                f"and the damage only surfaces when someone else pulls.",
                "Merge instead: merge(branch=…, reason=…). If the history really must be "
                "rewritten, that is a deliberate human operation, not an agent one.",
                reason=reason,
            )
        result = self.git.run(["rebase", onto], timeout=900)
        return self._receipt("rebase", args, "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok})

    def _published_commits_rewritten_by(self, onto: str) -> int:
        """How many commits a rebase onto ``onto`` would rewrite that are ALREADY upstream.

        The set a rebase rewrites is ``onto..HEAD``. Of those, the ones the remote
        has not seen are ``onto..HEAD --not @{upstream}``. The difference is what
        would be rewritten out from under anyone who already pulled.

        Returns 0 when there is no upstream to compare against: nothing has been
        published, so nothing can be republished. Counting conservatively the other
        way would refuse every rebase on a fresh branch.
        """
        def _count(argv: list[str]) -> Optional[int]:
            res = self.git.run(argv)
            token = res.stdout.strip()
            return int(token) if res.ok and token.isdigit() else None

        total = _count(["rev-list", "--count", f"{onto}..HEAD"])
        unpublished = _count(["rev-list", "--count", f"{onto}..HEAD", "--not", "@{upstream}"])
        if total is None or unpublished is None:
            return 0
        return max(0, total - unpublished)

    # -- remote state ----------------------------------------------------------

    def fetch(self, *, prune: bool = False, reason: Optional[str] = None,
              repo_mode: str = "main") -> dict:
        """Update remote-tracking refs. Touches no working file and no local branch.

        Mediated rather than a Tier 3 read only because it goes to the network and
        writes refs; it cannot destroy anything. It exists because an agent that
        cannot see that the remote moved will push into a surprise.
        """
        target = self._target(repo_mode)
        argv = ["fetch", "--prune", "origin"] if prune else ["fetch", "origin"]
        result = target.run(argv, timeout=300)
        return self._receipt("fetch", {"prune": prune, "repo": repo_mode},
                             "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok}, target=target)

    # -- deletion: mediated and audited ---------------------------------------

    def branch_delete(self, name: str, *, reason: str) -> dict:
        """Delete a branch — SAFE delete only (`-d`), never `-D`.

        `-d` refuses a branch whose commits are not merged anywhere; `-D` discards
        them. gitRobot does not offer the second: the commits are only recoverable
        from the reflog, which expires, and nothing else here is willing to make a
        silent loss one flag away.
        """
        if not name or name.startswith("-"):
            raise UsageError(f"{name!r} is not a branch name")
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("branch_delete requires a non-empty reason")
        if name == self.git.branch():
            raise self._refuse(
                "branch_delete", {"name": name},
                f"{name!r} is the branch currently checked out.",
                "switch(branch=<other>) first, then delete it.", reason=reason,
            )
        result = self.git.run(["branch", "-d", name])
        if not result.ok and "not fully merged" in result.output:
            raise self._refuse(
                "branch_delete", {"name": name},
                f"{name!r} has commits that are not merged anywhere, so deleting it "
                f"would strand them.",
                "If the work matters, merge it or tag it first (tag_create) — a tag keeps "
                "the commits reachable. gitRobot has no force-delete: recovering from one "
                "depends on the reflog, which expires.",
                reason=reason,
            )
        return self._receipt("branch_delete", {"name": name},
                             "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok})

    def tag_create(self, name: str, *, reason: str,
                   message_file: Optional[str] = None) -> dict:
        """Create an annotated tag. There is no tag deletion here.

        A tag that has been pushed is a public marker other things reference — in
        this project, releases mint permanent DOIs. Deleting one is not an agent
        decision, so the verb simply does not exist; a wrong tag is superseded by
        a corrected one.
        """
        if not name or name.startswith("-"):
            raise UsageError(f"{name!r} is not a tag name")
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("tag_create requires a non-empty reason")
        if message_file:
            path = Path(message_file)
            if not path.is_absolute():
                path = self.repo / path
            if not path.exists():
                raise UsageError(f"message file not found: {path}")
            argv = ["tag", "-a", name, "--file", str(path)]
        else:
            argv = ["tag", "-a", name, "-m", reason]
        result = self.git.run(argv)
        return self._receipt("tag_create", {"name": name},
                             "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok})

    def remove_files(self, paths: Sequence[str], *, reason: str,
                     cached: bool = False, repo_mode: str = "main") -> dict:
        """`git rm` on NAMED paths — same discipline as `stage`, no bulk form.

        ``cached=True`` untracks the file but leaves it on disk. Without it the
        file is deleted, so a path that has uncommitted modifications is refused:
        git would need `-f` to discard them, and `-f` is not available here.
        """
        paths = [str(p) for p in (paths or [])]
        if not paths:
            raise UsageError("remove_files requires at least one path")
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("remove_files requires a non-empty reason")
        bulk = [p for p in paths if p in BULK_ADD_TOKENS]
        if bulk:
            raise self._refuse(
                "remove_files", {"paths": paths},
                f"{bulk[0]!r} would delete everything matching it from the tree.",
                "Name the files: remove_files(paths=['a.lean'], reason='…'). "
                "read(op='status') shows what is there.", reason=reason,
            )
        escaped = [p for p in paths if p.startswith("-")]
        if escaped:
            raise UsageError(f"path {escaped[0]!r} looks like a flag; gitRobot passes "
                             f"paths only, never options, to git rm")
        target = self._target(repo_mode)
        argv = ["rm", "--cached", "--"] if cached else ["rm", "--"]
        result = target.run([*argv, *paths])
        if not result.ok and "local modifications" in result.output:
            raise self._refuse(
                "remove_files", {"paths": paths},
                "one of those files has uncommitted modifications, so deleting it "
                "would discard work that exists nowhere else.",
                "Commit or discard the modification deliberately first, or pass "
                "cached=True to untrack the file while leaving it on disk. gitRobot has "
                "no force flag for this.", reason=reason,
            )
        return self._receipt("remove_files",
                             {"paths": paths, "cached": cached, "repo": repo_mode},
                             "allowed" if result.ok else "failed",
                             reason=reason, detail=result.output,
                             extra={"output": result.output, "ok": result.ok}, target=target)

    # -- §12j: the identity of what a caller is about to certify ---------------

    def ledger_subjects(self, observed: dict, ref: str = "INDEX") -> dict:
        """`{basis, subjects, skipped}` — what a gate may honestly claim it examined.

        ⚠⚠ IT VERIFIES; IT DOES NOT DERIVE, AND THAT INVERSION IS THE WHOLE POINT.
        `observed` is MANDATORY and maps path -> the blob id THE GATE ACTUALLY READ.
        ZeroParadox's `common.ledger_subjects` derives the blob from the index AT
        RECORD TIME instead, and for a mechanical checker that is sound: read and
        record are milliseconds apart in one process, and its worktree-vs-index fence
        closes the remainder.

        For a REVIEW agent the same call sits MINUTES after the read, and the
        guarantee does not transfer. The silent case, measured by ZeroParadox
        2026-08-25: agent reads blob X -> the file changes to Y AND IS STAGED -> at
        record time worktree == index == Y -> no fence fires -> the record names Y.
        **The record then certifies content nobody examined, and nothing reports it.**
        Drift-and-revert is harmless for the same reason the fence looked sufficient
        (same content, same blob); it is drift-and-STAY that lies, and it is invisible
        to a deriving implementation by construction rather than by oversight.

        Taking the observed blob as an input makes that case unrepresentable: a
        mismatch is a `skipped` entry with both ids, and there is nothing to fence
        because nothing was assumed.

        ⚠ MANDATORY, NOT OPTIONAL-WITH-A-FALLBACK. An `observed=None` that quietly
        derived would put the silent case back for every caller that forgot — the
        two-route shape §12-0-alpha exists to refuse, where the weaker route wins
        exactly when you least want it to.

        ⚠ `skipped` IS THE FAIL-CLOSED SURFACE. A caller handed eight paths and four
        subjects with no explanation records a narrower verdict than it believes it
        recorded, and coverage shrinking silently is what §12a exists to prevent.
        Every fenced path comes back with its reason and both blob ids.

        ⚠⚠ TIER 2, NOT TIER 3, AND §3's TABLE NOW SAYS SO. `write-tree` materialises
        the index into tree OBJECTS. That is a mutation of the object database by any
        honest reading — which is why the read allow-list refuses it and why this
        tool, not that list, is the right home for it. It is as small as a mutation
        gets: it touches no ref, no index and no working tree, it is idempotent for an
        unchanged index, and its output is unreachable garbage until something names
        it. Audited like every other Tier 2 call.
        """
        if not isinstance(observed, dict) or not observed:
            raise UsageError(
                "ledger_subjects(observed={path: blob_id_you_read}) — `observed` is "
                "required and must be non-empty. Hash each file WHEN YOU READ IT "
                "(record.module_evidence does exactly this) and pass what you saw. "
                "This tool verifies your reading against the index; it will not "
                "derive one for you, because a derived blob can name content you "
                "never examined.")
        for path, blob in observed.items():
            v = blob.strip() if isinstance(blob, str) else ""
            # ⚠ FULL-LENGTH, LOWERCASE HEX ONLY. An abbreviated id is the dangerous
            # input here, not a malformed one: it compares unequal to what `ls-files`
            # prints, so it would land in `skipped` reading "DRIFTED SINCE YOU READ
            # IT" — sending the caller to re-read a file that never moved. Refused at
            # the door with the reason, rather than mis-diagnosed downstream.
            if (not v or v != v.lower()
                    or any(c not in "0123456789abcdef" for c in v)
                    or len(v) not in (40, 64)):
                raise UsageError(
                    f"observed[{path!r}] must be a FULL git blob id (40 or 64 "
                    f"lowercase hex), got {blob!r}. Use `git hash-object -- <path>` "
                    f"when you READ the file, or column 3 of `git ls-tree -r <ref>`. "
                    f"An abbreviated id would be reported as drift against content "
                    f"that never moved.")

        basis, at_ref = self._basis_and_blobs(ref)

        subjects, skipped = [], []
        for path in sorted(observed):
            seen = observed[path].strip()
            # ⚠⚠ `lstrip("./")` STRIPS CHARACTERS, NOT A PREFIX, AND THAT WAS A LIVE
            # BUG. It turned `.claude/commands/x.md` into `claude/commands/x.md`, so
            # EVERY DOTFILE PATH was reported as "not a repo-relative path" — and the
            # unit fixtures never caught it because none of their paths began with a
            # dot. Found on the first call against the real repository, which is the
            # argument for making that call rather than trusting a green suite.
            rel = path.replace("\\", "/")
            if rel.startswith("./"):
                rel = rel[2:]
            if (rel.startswith("/") or ":" in rel or rel.startswith("../")
                    or "/../" in rel or rel in ("", "..", ".")):
                skipped.append({"path": path, "why": "not a repo-relative path; "
                                "`git ls-files` prints forward-slashed paths relative "
                                "to the repo root, and that is what a subject must "
                                "carry. Absolute paths and `..` traversal are refused"})
                continue
            actual = at_ref.get(rel)
            if actual is None:
                skipped.append({"path": rel, "observed": seen, "at_ref": None,
                                "why": f"not tracked at {ref} — an untracked file "
                                       f"cannot be a subject, because nothing will "
                                       f"ever be able to tell whether it changed"})
                continue
            if actual != seen:
                # ⭐⭐ THE CASE THE DERIVING IMPLEMENTATION CANNOT SEE.
                skipped.append({"path": rel, "observed": seen, "at_ref": actual,
                                "why": f"DRIFTED SINCE YOU READ IT: you examined "
                                       f"{seen[:12]}…, {ref} holds {actual[:12]}…. "
                                       f"Re-read this path and judge it again; a "
                                       f"verdict over the bytes you saw would name "
                                       f"bytes nobody examined"})
                continue
            subjects.append({"path": rel, "git_blob_id": actual})

        return self._receipt(
            "ledger_subjects", {"ref": ref, "paths": len(observed)}, "allowed",
            detail=f"{len(subjects)} subject(s), {len(skipped)} skipped at {ref}",
            extra={"basis": basis, "subjects": subjects, "skipped": skipped,
                   "ok": True})

    def _basis_and_blobs(self, ref: str):
        """The tree a record should name, and every blob under it.

        ⚠ `INDEX` is the case that matters and the one `write-tree` is needed for: a
        gate reviews what is STAGED, before the commit exists. `ledger_basis`'s own
        docstring calls it "the tree the commit will carry", and ZeroParadox verified
        2026-08-25 that a record made against the index tree SURVIVES the commit of
        that index — the ledger resolves a commit ref to its tree, so committing an
        unchanged index re-stales nothing.
        """
        if ref == "INDEX":
            res = self.git.run(["write-tree"], timeout=120)
            if not res.ok:
                raise RepoError(
                    f"git write-tree failed, so there is no tree to certify against: "
                    f"{res.output.strip()}. An unmerged index is the usual cause; "
                    f"resolve the conflict and stage it.")
            tree = res.stdout.strip()
            blobs = self._blobs(["ls-files"])
        else:
            res = self.git.run(["rev-parse", f"{ref}^{{tree}}"], timeout=60)
            if not res.ok:
                raise RepoError(f"cannot resolve {ref!r} to a tree: "
                                f"{res.output.strip()}")
            tree = res.stdout.strip()
            blobs = self._blobs(["ls-tree", "-r", ref])
        return ({"kind": "tree", "value": tree, "resolved_from": "explicit"}, blobs)

    # ⭐⭐ ASK GIT FOR THE FIELD BY NAME. This used to take the blob COLUMN as a
    # parameter, because `ls-files -s` and `ls-tree -r` put it in different places.
    # That was correct HERE — and the verdictLedger copy of the same parse took the
    # wrong one, returned the STAGE (`0`) for every staged file, and made every key at
    # that basis permanently unsatisfiable. `--format` deletes the field to count:
    # `%(objectname)` cannot accidentally be the stage.
    #
    # ⚠ STILL THE GIT BINARY, AND THAT IS A CHOICE. A native binding (libgit2) would
    # remove the parse too, and would REIMPLEMENT git in exchange. These ids are only
    # meaningful because they equal what `git add` actually wrote, filters included —
    # and filters are live in this repo (`.gitattributes` mandates LF for *.json; CRLF
    # moved `policy_sha` on 2026-08-25). A binding computing a filtered blob even
    # slightly differently would produce records that append cleanly and read STALE
    # for ever: the 2026-08-23 sha256 defect again, subtler and harder to find.
    _FMT = "--format=%(objectname)%x09%(path)"

    def _blobs(self, args) -> dict:
        """path -> blob id, from either command, in one shape."""
        res = self.git.run([*args, self._FMT], timeout=180)
        if not res.ok or not res.stdout.strip():
            raise RepoError(
                f"git {' '.join(args)} produced no file list: "
                f"{res.output.strip()[:200]}. `--format` needs git >= 2.38 "
                f"(ls-files) / 2.36 (ls-tree). An empty list is never served as an "
                f"empty repository — every path would silently fence as untracked.")
        out = {}
        for line in res.stdout.splitlines():
            if "\t" not in line:
                continue
            blob, path = line.split("\t", 1)
            out[path.strip()] = blob.strip()
        return out

    # -- the sanctioned escape from Tier 1 -------------------------------------

    def worktree(self, action: str, *, ref: Optional[str] = None,
                 name: Optional[str] = None) -> dict:
        """Private throwaway checkouts — the alternative every Tier 1 refusal names.

        A worktree has its own HEAD, index and working tree, so anything done in
        one is unreachable from the caller's files. This is the one Tier 2
        operation gitRobot actively encourages, so it is one call.
        """
        if action == "list":
            return self.read("worktree", ["list"])
        if action == "add":
            ref = ref or "HEAD"
            if ref.startswith("-"):
                raise UsageError(f"{ref!r} is a flag, not a ref")
            self.scratch.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in (name or ref))
            # ⚠⚠ UNIQUE PER PROVISION, NEVER DERIVED FROM THE REF. The name used to be
            # `<ref>-<hash of that same path>`, which is a pure function of the ref --
            # so two provisions at one ref COLLIDE BY CONSTRUCTION. Measured by
            # ZeroParadox 2026-08-25: an aborted `add` left `HEAD-7c335d652168` holding
            # a partial checkout, and every later `add` at HEAD hit
            # `fatal: '…' already exists` for ever.
            #
            # `mkdtemp` reserves the name ATOMICALLY, which is the property a
            # "does it exist yet?" probe cannot have: two concurrent rounds at one tree
            # is precisely the case the review-snapshot design would make routine, and
            # a check-then-create races exactly there.
            #
            # ⚠ It creates the directory, and git accepts adding into an EXISTING EMPTY
            # one -- verified 2026-08-25, exit 0. An empty directory and a partial
            # checkout are different things to git, which is the whole distinction the
            # old scheme lost.
            path = Path(tempfile.mkdtemp(prefix=f"{safe}-", dir=self.scratch))
            result = self.git.run(["worktree", "add", "--detach", str(path), ref],
                                  timeout=300)
            decision = "allowed" if result.ok else "failed"
            return self._receipt("worktree.add", {"ref": ref, "path": str(path)}, decision,
                                 detail=result.output,
                                 extra={"path": str(path), "output": result.output,
                                        "ok": result.ok})
        if action == "prune":
            result = self.git.run(["worktree", "prune", "-v"], timeout=120)
            return self._receipt("worktree.prune", {}, "allowed" if result.ok else "failed",
                                 detail=result.output,
                                 extra={"output": result.output, "ok": result.ok})
        if action == "remove":
            if not name:
                raise UsageError("worktree(action='remove') requires name=<path from add>")
            path = Path(name)
            # Removable = anything GIT ITSELF lists as a worktree of this repo, except
            # the main checkout. Keying on git's own list rather than on gitRobot's
            # scratch directory means leftovers from other sessions can be cleaned up
            # (one was found stranded in a foreign scratchpad), while the set stays
            # enumerable from the repo instead of taken from the caller.
            known = self._worktree_paths()
            resolved = path.resolve()
            if resolved == self.repo:
                raise self._refuse(
                    "worktree.remove", {"name": name},
                    "that is the main checkout, not a worktree.",
                    "The main checkout is not removable by design — it is the thing every "
                    "other guard here exists to protect.",
                )
            if resolved not in known:
                # ⚠⚠ THE ORPHAN CASE, AND THE OLD REFUSAL NAMED TWO REMEDIES THAT BOTH
                # CANNOT WORK. Measured by ZeroParadox 2026-08-25: an aborted `add`
                # leaves a directory holding a partial checkout that git never
                # registered. `list` cannot show it -- git does not know it exists.
                # `prune` is the OPPOSITE case: it clears records whose directories are
                # gone, and here the directory is present and the record is not. So
                # every sanctioned route was closed while the refusal confidently named
                # two of them, and the only way out was a raw `Remove-Item` -- which is
                # a session with shell access working around this server, i.e. the
                # bypass §2 says a refusal without a workable alternative invents.
                #
                # ⚠ BOUNDED TO gitRobot'S OWN SCRATCH ROOT, which it created and which
                # holds nothing else. That is what makes a recursive delete safe to
                # offer here and nowhere else: outside it, a path git does not know is
                # somebody's actual work and the refusal below stands.
                scratch = self.scratch.resolve()
                orphan = (resolved != scratch and resolved.is_dir()
                          and scratch in resolved.parents)
                if orphan:
                    # Prune first: if git DID hold a stale record, this is the ordinary
                    # path and the rmtree below is then merely tidying the directory.
                    self.git.run(["worktree", "prune"], timeout=120)
                    shutil.rmtree(resolved, ignore_errors=False)
                    return self._receipt(
                        "worktree.remove_orphan", {"name": str(resolved)}, "allowed",
                        detail=f"removed an unregistered directory under {scratch}",
                        extra={"path": str(resolved), "orphan": True, "ok": True})
                raise self._refuse(
                    "worktree.remove", {"name": name},
                    f"{name!r} is not a worktree of this repository, and it is not a "
                    f"leftover directory under {self.scratch}.",
                    f"worktree(action='list') shows what git can remove. If the directory "
                    f"is gone but its record remains, worktree(action='prune') clears "
                    f"that. Neither applies to a path git never knew about outside "
                    f"gitRobot's own scratch root -- if that path is real work, removing "
                    f"it is not this server's call.",
                )
            result = self.git.run(["worktree", "remove", "--force", str(path)], timeout=300)
            decision = "allowed" if result.ok else "failed"
            return self._receipt("worktree.remove", {"name": str(path)}, decision,
                                 detail=result.output,
                                 extra={"output": result.output, "ok": result.ok})
        raise UsageError(
            f"unknown worktree action {action!r}; expected add, list, remove or prune")

    def _worktree_paths(self) -> set:
        """Every path git reports as a worktree of this repo (main checkout included)."""
        result = self.git.run(["worktree", "list", "--porcelain"])
        out = set()
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                out.add(Path(line.split(" ", 1)[1].strip()).resolve())
        return out

    # =========================================================================
    # Explanation + history
    # =========================================================================

    def explain(self, refusal_id: str) -> dict:
        """Why an operation was refused and exactly what discharges it."""
        cached = self._refusals.get(refusal_id)
        if cached:
            return {"refusal_id": refusal_id, **cached}
        for record in reversed(self.audit.read()):
            detail = record.get("detail") or ""
            if detail.startswith(f"[{refusal_id}]"):
                return {"refusal_id": refusal_id, "op": record["op"],
                        "args": record["args"], "what": detail.split("] ", 1)[-1],
                        # Persisted with the refusal, so this survives a restart. It
                        # used to degrade to "the audit record is the durable copy",
                        # which was true and useless: the alternative is the half a
                        # caller actually needs, and losing it turns a refusal back
                        # into a dead end.
                        "alternative": record.get("alternative") or "(recorded before "
                        "alternatives were persisted; see 'what' above)",
                        "ts": record["ts"]}
        raise UsageError(f"no refusal with id {refusal_id!r} in this session or the log")

    # ⚠ The fields a reader actually scans after an incident. Everything else --
    # full args, gate verdicts, inventory payloads -- is behind `full=True`.
    SUMMARY_FIELDS = ("ts", "op", "decision", "head", "branch", "actor", "reason")

    def history(self, limit: int = 20, full: bool = False, op: Optional[str] = None,
                decision: Optional[str] = None) -> dict:
        """The append-only op log. SUMMARY BY DEFAULT.

        ⚠⚠ GRB-4. `limit=30` returned 194,296 characters across 818 lines -- it had
        to be dumped to a file and grepped. §7 gives this tool one job, answering
        "did this guard ever fire?" after an incident, and it could not be read at the
        moment it was needed. A tool that must be post-processed to be used has the
        wrong default.

        ⚠ The full record is one flag away, never gone: truncation that cannot be
        undone would trade an unreadable log for a lossy one.
        """
        records = self.audit.read()
        if op:
            records = [r for r in records if r.get("op") == op]
        if decision:
            records = [r for r in records if r.get("decision") == decision]

        total = len(records)
        # ⚠ The MOST RECENT `limit`, because an incident is always at the end.
        shown = records[-limit:] if limit and limit > 0 else records
        if not full:
            shown = [{k: r.get(k) for k in self.SUMMARY_FIELDS if r.get(k) is not None}
                     for r in shown]

        return {
            "count": len(shown), "total": total, "path": str(self.audit.path),
            "full": full,
            # ⚠ NAME WHAT WAS LEFT OUT. A window that renders like the whole log is
            # the defect this file fixes elsewhere; silence about 780 skipped rows
            # would be that same shape.
            "omitted": max(0, total - len(shown)),
            "note": (None if len(shown) == total else
                     f"showing the most recent {len(shown)} of {total} \u2014 raise limit, "
                     f"or filter with op=/decision="),
            "records": shown,
        }
