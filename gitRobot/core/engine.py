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
import stat as _stat
# ⚠ THE ONLY DIRECT subprocess USE IN THIS MODULE, AND IT IS NOT GIT. Every git call goes through
# `gitio.run`, which is where the option guards and the audit live — nothing here may bypass it.
# This is for `mklink /J`, which has no Python equivalent that works without elevation:
# `os.symlink` on a directory needs admin or developer mode, and a tool that only works for an
# administrator is one people work around.
import subprocess
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

    def _target(self, repo_mode: str, worktree: Optional[str] = None) -> Git:
        """The main tree, the ONE named nested repository, or a worktree GIT VOUCHES FOR.

        ⚠⚠ `worktree` IS NOT A FREE PATH, AND THE DISTINCTION IS THE WHOLE SAFETY ARGUMENT.
        `sub_repo`'s docstring says taking a path argument "would reopen the general-proxy hole
        this class exists to close" — correct, and the objection is to paths the CALLER INVENTS,
        not to paths as such. This one is validated against `git worktree list`: the caller can
        name only something git already reports as a worktree of THIS repo, and the only way
        into that set is `worktree(action='add')`, which gitRobot owns. A path outside the repo,
        a different repository, a removed worktree, or a made-up string is simply not in the
        list and is refused.

        ⭐ THAT IS A STRONGER CHECK THAN `sub_repo`'s, which validates with two hand-written
        tests (`parents` contains the repo, `.git` exists). This one asks git.

        ⚠ WHY IT EXISTS: concurrent edits. A worktree has its own HEAD, index and working tree,
        so two sessions can author in two worktrees without contending for the state they would
        otherwise share. Until now the mediated path could not reach a worktree at all — you
        could read and run checkers in one, but not commit from it — which is why the intended
        worktree-per-change flow lapsed into serial commits on one branch.
        """
        if worktree:
            if repo_mode not in ("", "main", None):
                raise UsageError(
                    f"worktree and repo_mode={repo_mode!r} are mutually exclusive; a nested "
                    f"repository has no worktrees of its own")
            resolved = Path(worktree).resolve()
            known = self._worktree_paths()
            if resolved == self.repo:
                raise UsageError(
                    "that is the main checkout, not a worktree; omit `worktree` to target it")
            if resolved not in known:
                raise self._refuse(
                    "worktree.target", {"worktree": str(worktree)},
                    f"git does not list {resolved} as a worktree of this repository.",
                    "worktree(action='list') shows what is targetable. Create one with "
                    "worktree(action='add') — gitRobot will not accept a path git has not "
                    "vouched for, because that is the general-proxy hole the repo modes exist "
                    "to close.",
                )
            return Git(resolved, timeout=self.git.timeout)
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
                 target: Optional[Git] = None, run_id: Optional[str] = None) -> dict:
        # ⚠ `run_id` TIES A TERMINAL ROW TO THE `started` ROW THAT OPENED IT. Needed once
        # an operation runs on a worker thread, because the receipt no longer arrives in
        # the call that requested it and `push_status` has to match them up. Optional, so
        # every synchronous caller is unaffected.
        # The audit must name the tree the operation actually touched. Recording the
        # main repo's HEAD for a `.claude-local` write would be a log that lies.
        git = target or self.git
        record = self.audit.append(
            actor=self.actor, op=op, args=args, decision=decision, run_id=run_id,
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
             repo_mode: str = "main", worktree: Optional[str] = None) -> dict:
        """Run an allow-listed read-only git command.

        Unrecognised operations are REFUSED, not passed through: the allow-list
        is what makes "everything not yet classified" safe by default.

        ⚠⚠ `worktree=` ADDED 2026-09-03, AND ITS ABSENCE WAS A REAL GAP. `stage`, `unstage` and
        `commit` all gained a worktree target when worktrees became the sanctioned unit of work;
        `read` did not. So an agent could WRITE to a worktree through gitRobot and then had no
        sanctioned way to LOOK at it — ZeroParadox hit exactly that verifying the arc handshake:
        *"`git ls-files -v` is denied to me and `read` has no worktree parameter, so I cannot see
        the `S` flag directly. I did not work around it."* That refusal was correct and the gap
        was mine.

        ⭐ A MEDIATED SURFACE THAT CAN WRITE SOMEWHERE IT CANNOT READ PUSHES CALLERS TOWARD RAW
        GIT — which is the one outcome the whole design exists to prevent. The asymmetry, not the
        missing feature, is the defect.
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
        # ⚠ Validated against the registered worktree set by `_target`, exactly as the write
        # paths are — a read aimed at an arbitrary directory would describe a tree gitRobot does
        # not guard, which is what `forbidden_token` above refuses in flag form.
        target = self._target(repo_mode, worktree)
        result = target.run([op, *args])
        return {"op": op, "args": args, "worktree": worktree,
                "exit_code": result.exit_code,
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

    def stage(self, paths: Sequence[str], repo_mode: str = "main",
              worktree: Optional[str] = None) -> dict:
        """Stage NAMED paths. Bulk forms are refused on the main repository."""
        paths = [str(p) for p in (paths or [])]
        if not paths:
            raise UsageError("stage requires at least one path; there is no bulk form")
        target = self._target(repo_mode, worktree)
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

    def unstage(self, paths, reason=None, repo_mode: str = "main",
                worktree: Optional[str] = None) -> dict:
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
        target = self._target(repo_mode, worktree)
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
               worktree: Optional[str] = None,
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

        target = self._target(repo_mode, worktree)
        if not target.run(["diff", "--cached", "--quiet"]).exit_code:
            raise self._refuse(
                "commit", {"message_file": str(path), "repo": repo_mode},
                "nothing is staged, so this commit would be empty.",
                "stage(paths=[…]) the files you changed first; read(op='status') shows them.",
                reason=reason, target=target,
            )

        # ⛔⛔ THE BACKSTOP: A COMMIT MAY NEVER CARRY A NON-ZERO ARC ROUND.
        # The tracked default is `round: 0`, and `--skip-worktree` normally makes a bumped round
        # unstageable outright. This covers the case that flag CANNOT cover: a worktree gitRobot
        # did not create, a checkout where the index flag was lost, or the main checkout, where
        # nothing "creates" the arc and so nothing seals it.
        #
        # ⚠ WHY IT IS WORTH A SECOND CONTROL. One committed non-zero round is inherited by EVERY
        # future arc, permanently, and it arrives from the TREE rather than from a stale local
        # file — so `gate_round.py`'s existing "base recorded X, HEAD is now Y" warning never
        # fires and the over-count it exists to catch becomes invisible. Cheap to prevent, very
        # expensive to notice.
        #
        # ⭐ IT LIVES HERE RATHER THAN IN A CHECKER because gitRobot is the CHOKE POINT: direct
        # git is denied by a PreToolUse hook, so every agent commit comes through this method. A
        # scanner in the verify bundle would have to remember to run and would buy a routing
        # round; this cannot be skipped.
        staged_round = self._staged_arc_round(target)
        if staged_round is not None and staged_round != 0:
            # ⚠⚠ SAY WHAT WAS READ AND WHERE, NOT "STAGED" — measured cost, 2026-09-03.
            # `_staged_arc_round` reads `git show :<path>`, the INDEX copy, which equals HEAD
            # whenever nothing is staged. So "is staged" was FALSE in the ordinary case, and it
            # sent ZeroParadox to look at a clean main checkout four times while the value came
            # from a SECOND `gate_round.json` inside `.claude-local` carrying round 5 from a
            # different arc. The refusal was correct; its message cost the diagnosis.
            #
            # ⭐ §3's rule about refusals naming the alternative has a sibling: a refusal must
            # name the OBJECT it read. "Staged" described a mechanism the caller could check and
            # find absent, which reads as a stale guard rather than a true one — and a caller who
            # concludes the guard is stale is a caller looking for a way around it.
            where = f"{repo_mode or 'main'}:{self._ARC_STATE}"
            raise self._refuse(
                "commit", {"message_file": str(path), "repo": repo_mode},
                (f"the index copy of {where} carries round={staged_round}, and the tracked copy "
                 f"must stay at 0. ⚠ This is read from the INDEX, so it fires whether or not you "
                 f"staged anything — a tracked file already at a non-zero round reads the same "
                 f"way." if staged_round >= 0 else
                 f"the index copy of {where} has an unreadable `round`, so the count this commit "
                 f"would publish is UNKNOWN — an unknown count next to a cap fails closed."),
                (f"⚠ CHECK THE REPO NAMED ABOVE — {repo_mode or 'main'} — not whichever tree "
                 f"you are looking at. There is a separate {self._ARC_STATE} per repo, and a "
                 f"clean main checkout tells you nothing about the one this read.\n"
                 f"If it is genuinely staged: unstage(paths=['{self._ARC_STATE}']). If the "
                 f"TRACKED copy is at a non-zero round, that is the real defect — reset it to 0 "
                 f"and commit that, because every future arc inherits it.\n"
                 f"It is the ARC HANDSHAKE: a tracked default every worktree opens with, never a "
                 f"place to record this arc's progress. Its round stays local and dies with the "
                 f"worktree."),
                reason=reason, target=target,
            )

        gate_records = []
        if run_gate and repo_mode == "main":
            # ⚠⚠ THE GATE MUST RUN IN THE TREE BEING COMMITTED. `self.gates` is bound to the
            # MAIN checkout, so once `worktree` became targetable this would have verified the
            # main tree while committing the worktree's content — **the check and the act about
            # different objects**, which is the defect class this project has spent three days
            # removing, introduced by the fix for something else. Caught by a test that could
            # not find the pipeline, not by review.
            gates = self.gates if target is self.git else Gates(target.repo)
            gate = gates.run("pre-commit")
            gate_records = [gate.record()]
            if not gate.passed:
                self.audit.append(
                    actor=self.actor, op="commit",
                    args={"message_file": str(path), "repo": repo_mode,
                          "worktree": worktree},
                    # ⚠ And the receipt records the TARGET's head/branch/tree, not the main
                    # tree's. An audit row naming the wrong tree is a log that lies about where
                    # the work landed.
                    decision="refused", head=target.head(), branch=target.branch(),
                    tree=target.tree_state(), gates=gate_records, reason=reason,
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
        # ⭐⭐ THREE STATES, AND THE OLD `or` COLLAPSED TWO OF THEM. This read
        # `if alive or started.get("pid") == os.getpid(): running`, so once the audit row had
        # been written by THIS process the answer was "running" whether or not any worker
        # existed. A thread that died while the process lived reported `running` FOREVER, with
        # no owner and no way for a caller to tell it from work in flight.
        #
        # ⭐ ZeroParadox's framing, 2026-09-02: **"`preflight_status` reports the LOCK, and I
        # asked it about the PIPELINE."** Two different objects, one answer — the same
        # check-and-claim-are-about-different-objects shape this codebase keeps finding.
        #
        # ⚠ THE NIGHT IT WAS REPORTED THE PIPELINE WAS GENUINELY ALIVE and the alarm was
        # false — a stale `running` was inferred from a bad process count. The defect is real
        # anyway, and it is the reason neither of us could settle the question without
        # enumerating processes by hand.
        alive = any(t.name == f"preflight-{run_id}" and t.is_alive()
                    for t in threading.enumerate())
        if alive:
            return {"state": "running", "head": head, "run_id": run_id,
                    "started_at": started["ts"]}
        if started.get("pid") == os.getpid():
            # ⚠⚠ OUR PROCESS, NOT OUR THREAD. Nothing is executing and nothing will ever write
            # the verdict, so a caller told `running` waits for an event that cannot arrive.
            # Naming it ORPHANED is what makes re-running a legitimate remedy rather than a
            # guess about whether a lock is stale.
            return {"state": "orphaned", "head": head, "run_id": run_id,
                    "started_at": started["ts"],
                    "note": "this process started the run and its worker thread is gone, so no "
                            "verdict will ever be written. Nothing is executing — this is not a "
                            "lock you are waiting on. Re-run preflight()."}
        # ⚠ A DIFFERENT PROCESS OWNS IT AND WE CANNOT SEE ITS THREADS. Thread liveness is
        # process-local, so "it is dead" and "I cannot observe it from here" are different
        # claims; this branch is the second wearing the first's name, and the note says so
        # rather than letting a restart-survivor read as a corpse.
        return {"state": "died", "head": head, "run_id": run_id,
                "started_at": started["ts"],
                "started_pid": started.get("pid"),
                "note": "the run was started by a process that is not this one and never "
                        "recorded a verdict — most likely killed mid-flight by a restart. "
                        "⚠ Thread liveness cannot be read across processes: if that pid is "
                        "still alive the run may be too. Check the pid before re-running."}

    def push(self, branch: str, *, reason: Optional[str] = None,
             repo_mode: str = "main", wait: bool = True) -> dict:
        """Push a branch. On the main repo, only if verdictLedger says so.

        ⚠⚠ THE GIT PUSH RUNS ON A WORKER THREAD AND THIS RETURNS A ``run_id``. Poll
        ``push_status()``. `preflight` has had this shape since 2026-08-22 and its
        docstring argues for it in terms; `push` did not, and on 2026-08-30 that cost
        a real push. Measured: the MCP client abandons the call at **300s**, this
        method capped git at **900s**, and the pre-push hook — which is the backstop,
        so it always runs — now takes **1498s**. The sanctioned route was
        unreachable by ~5x, and BOTH ceilings were below the floor, so raising one
        would have fixed nothing.

        ⭐ AND THE CAUSE IS WORTH KEEPING: the pipeline got slower BECAUSE the routing
        control was repaired the same night (`RLY41-1` — it stopped inheriting a red
        baseline and started constructing one, at the price of extra `prepush` runs).
        **A control we made honest became, by the same change, expensive enough that
        the compliant path stopped working.** Nobody decided to cheat; every honest
        route closed at once, which is how a bypass gets invented. **The cost of a
        control is part of the control**, and it was not priced. ZeroParadox's
        framing, and it is the durable lesson here rather than the timeout number.

        ⚠ WHAT STAYS SYNCHRONOUS, DELIBERATELY: every refusal — branch shape, missing
        reason, and the ledger inventory. A caller must learn "this push is not
        allowed" from the call it made, not from a later poll. Only the irreversible
        act itself is backgrounded.

        ⚠⚠ A DIED PUSH IS NOT LIKE A DIED PREFLIGHT, AND `push_status` SAYS SO. A
        preflight that dies changed nothing; a push that dies MAY ALREADY HAVE
        PUBLISHED. The remote is the only authority on that, so the ``died`` state
        names `ls-remote` as the check rather than implying nothing happened.

        ⚠ ``wait`` DEFAULTS TO **True**, AND THE DEFAULT SITS HERE DELIBERATELY. The 300s
        ceiling is a property of the MCP TRANSPORT, not of pushing, so the MCP tool is the
        one that opts out (``wait=False``) and everything else — the CLI, tests, any
        script — keeps a call that returns the real outcome. Defaulting to async would
        have made every existing caller report success for a push that had not happened
        yet, which is exactly the confusion the ``started`` decision exists to prevent.

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

        # ⚠ ONE PUSH AT A TIME, same reason `preflight` refuses a second run: two
        # concurrent pushes of one branch race, and the audit could not say which
        # receipt belonged to which act.
        running = self.push_status()
        if running.get("state") == "running":
            raise self._refuse(
                "push", args, "a push is already running for this store.",
                "Wait for it and poll push_status(). The pre-push hook re-runs the full "
                "pipeline on every push, so a second run would spend it twice.",
                reason=reason, target=target,
            )

        run_id = _refusal_id("push", f"{self.git.head()}|{branch}|{len(self.audit.read())}")
        self.audit.append(
            actor=self.actor, op="push", args=args, decision="started",
            head=self.git.head(), branch=self.git.branch(), tree=self.git.tree_state(),
            reason=reason, detail="push started", run_id=run_id,
        )

        def _do_push() -> dict:
            # ⚠⚠ THE TIMEOUT MUST CLEAR THE HOOK, NOT THE NETWORK. This was 900s, chosen
            # when the pre-push pipeline took ~155s. It is the BACKSTOP hook — it runs on
            # every push by design — and it now takes 1498s, so 900s killed the push
            # mid-gate and looked like a network fault. Sized well above the measured
            # pipeline rather than just above it, because the pipeline grows whenever a
            # control is added and the next person to add one will not revisit this number.
            result = target.run(["push", "origin", branch], timeout=3600)
            decision = "allowed" if result.ok else "failed"
            return self._receipt(
                "push", push_args, decision, gates=None, reason=reason,
                detail=result.output, run_id=run_id,
                extra={"output": result.output, "ok": result.ok, "run_id": run_id},
                target=target)

        push_args = args
        if inv is not None:
            # ⚠ The audit row NAMES the inventory that authorised this push and the
            # policy it was judged under, so a bar that moved later cannot
            # re-interpret a past action.
            push_args = {**args, "inventory_ref": inv.get("tip") or inv.get("ref"),
                         "inventory_range": inv.get("range"),
                         "commits_gated": inv.get("commits_in_range"),
                         # ⚠ RENAMED 2026-08-25: the ledger key is config_sha, because it
                         # covers the policy AND the registry. Reading the old key here
                         # would have silently written null into every push audit row --
                         # the audit still LOOKS complete, which is the shape that hides.
                         "config_sha": inv.get("config_sha"),
                         "admission": inv.get("admitted"),
                         "inventory": inv.get("line")}

        if wait:
            return _do_push()

        thread = threading.Thread(target=_do_push, name=f"push-{run_id}", daemon=True)
        thread.start()
        return {"op": "push", "run_id": run_id, "branch": branch, "state": "running",
                "head": self.git.head(),
                "inventory": None if inv is None else inv.get("line"),
                "note": ("the push is running in the background; poll push_status(). The "
                         "pre-push hook re-runs the full pipeline as the backstop, measured "
                         "at ~25 minutes, so expect minutes not seconds.")}

    def push_status(self) -> dict:
        """Where the last started push got to. The sibling of `preflight_status`.

        ⚠⚠ `died` MEANS SOMETHING DIFFERENT HERE THAN IT DOES FOR A PREFLIGHT, AND THE
        DIFFERENCE IS THE WHOLE REASON THIS IS NOT A COPY. A preflight that dies changed
        nothing — re-run it. A push that dies **may already have published**: the git
        process can be killed after the remote accepted the ref and before the receipt is
        written. So this never says "it did not happen"; it names the remote as the only
        authority and tells the caller to ask it.
        """
        started = None
        for record in self.audit.read():
            if record.get("op") == "push" and record.get("decision") == "started":
                started = record
        if started is None:
            return {"state": "none", "note": "no push has been started from this store."}

        run_id = started.get("run_id")
        for record in self.audit.read():
            if record.get("run_id") == run_id and record.get("decision") in ("allowed", "failed"):
                return {"state": record["decision"], "run_id": run_id,
                        "branch": started.get("args", {}).get("branch"),
                        "head": started.get("head"), "ts": record["ts"],
                        "output": (record.get("extra") or {}).get("output")}

        alive = any(t.name == f"push-{run_id}" and t.is_alive()
                    for t in threading.enumerate())
        if alive:
            return {"state": "running", "run_id": run_id,
                    "branch": started.get("args", {}).get("branch"),
                    "head": started.get("head"),
                    "note": "still running; the pre-push hook re-runs the full pipeline (~25 min)."}
        return {"state": "died", "run_id": run_id,
                "branch": started.get("args", {}).get("branch"),
                "head": started.get("head"),
                "note": ("the worker is gone and no receipt was written — the server most "
                         "likely restarted mid-push. THIS DOES NOT MEAN NOTHING WAS PUSHED: "
                         "git can be killed after the remote accepted the ref. Ask the remote, "
                         "which is the only authority: read(op='ls-remote') or compare "
                         "origin/<branch> against local. Do NOT retry until you have."),
                "check": "ls-remote"}

    # ⚠⚠ SHARED, GITIGNORED BUILD DEPENDENCIES A FRESH WORKTREE CANNOT HAVE. `.lake` holds the
    # pinned Mathlib and nine other packages; it is gitignored, so `git worktree add` produces a
    # checkout without it, and in that checkout Lean cannot build and `check_paths` WITHHOLDS on
    # "Mathlib absent". Measured 2026-08-30 during a real healing run.
    #
    # ⭐⭐ THAT IS WHY THE WORKTREE FLOW LAPSED. The intended model is a private worktree per
    # change, converging at a local merge — but a worktree straight out of the tool could not
    # build the corpus, so work went serially onto one branch instead. 26 commits in three days,
    # all on `illustrated`, every other branch months stale. **A sanctioned path that does not
    # produce a working tree is not a sanctioned path**, and the mandatory rule could not be
    # enforced because compliance was impossible.
    #
    # ⚠ A JUNCTION, NOT A COPY: `.lake` is far too large to duplicate per worktree (a `du` over
    # it did not finish in two minutes). Tim confirms a link to the folder was tested and works.
    _SHARED_DEPS = (".lake",)

    # ⭐⭐ THE ARC HANDSHAKE. Tim, 2026-09-02: **a worktree is the project root and the instance
    # acting inside it IS the arc.** So the review-round counter is per-arc BY CONSTRUCTION rather
    # than by convention — it lives at the arc's own root, and it dies with the worktree, which is
    # correct because the arc is over.
    #
    # ⚠ The file is TRACKED, committed once at `round: 0`, so every fresh checkout OPENS with the
    # known-good state — "what is supposed to be there by default". That solves the thing that made
    # worktrees unusable: a gitignored file is ABSENT in a fresh worktree, and absence had to be
    # guessed at. `gate_round.py` treats missing as `{'round': 0, 'fresh': True}` and says so,
    # because "deleting the file is otherwise an unlogged reset" — nine bypass routes have been
    # found and closed on that one counter. A tracked default removes the guess entirely.
    #
    # ⚠⚠ AND `--skip-worktree` IS WHAT MAKES THE MISTAKE UNAVAILABLE RATHER THAN MERELY UNLIKELY.
    # Git then treats local modifications as nonexistent: `git add` on the file is a no-op, so a
    # bumped round CANNOT be staged or committed even deliberately. Without it the file is an
    # ordinary tracked file, every bump shows dirty, and one committed non-zero round would be
    # inherited by every future arc — permanently, and arriving from the TREE rather than from a
    # stale file, which is the invisible version of the over-count `gate_round.py` already warns
    # about ("an inherited count stops a fresh arc early").
    #
    # ⚠ NOT `--assume-unchanged`: documented as not a guarantee, and git clobbers it on checkout
    # and merge. The index flag is also PER WORKTREE — each has its own index — which is precisely
    # why it is set here, at the one place that creates worktrees.
    _ARC_STATE = "gate_round.json"

    def _seal_arc_state(self, worktree: Path) -> dict:
        """Mark the arc handshake file skip-worktree in a fresh worktree, so its local round
        bumps can never be staged. A no-op when the file is not tracked (it is not, yet)."""
        target = Git(Path(worktree), timeout=self.git.timeout)
        probe = target.run(["ls-files", "--error-unmatch", self._ARC_STATE], timeout=30)
        if not probe.ok:
            # ⚠ Not tracked here. That is the state TODAY — the file still lives under
            # `.claude-local/` and has not been migrated — so this must be silent and inert
            # rather than a failure, and it must start working the moment the file lands.
            return {"sealed": False, "reason": "not tracked in this worktree"}
        res = target.run(["update-index", "--skip-worktree", self._ARC_STATE], timeout=30)
        return {"sealed": bool(res.ok), "file": self._ARC_STATE,
                "reason": None if res.ok else (res.output or "").strip()[:200]}

    def _staged_arc_round(self, target) -> Optional[int]:
        """The `round` in the INDEX copy of the handshake, or None if absent/unreadable.

        ⚠ Read from the index (`:path`), never the working tree — the question is what a commit
        WOULD carry, and those differ by exactly the local bump this exists to keep out.
        """
        res = target.run(["show", f":{self._ARC_STATE}"], timeout=30)
        if not res.ok:
            return None
        try:
            doc = json.loads(res.output)
        except (ValueError, TypeError):
            # ⚠ Unparseable is NOT "no round". `gate_round.py` fails closed on a corrupt counter
            # for the same reason, and this returns a sentinel the caller refuses on rather than
            # a None that reads as "nothing to see".
            return -1
        value = doc.get("round") if isinstance(doc, dict) else None
        if isinstance(value, bool) or not isinstance(value, int):
            return -1
        return value

    def _link_shared_deps(self, worktree: Path) -> list:
        """Junction the shared, gitignored build deps into a fresh worktree. Best effort."""
        made = []
        for name in self._SHARED_DEPS:
            src = self.repo / name
            dst = Path(worktree) / name
            if not src.is_dir() or dst.exists():
                continue
            # ⚠ `mklink /J` needs no elevation, unlike a directory SYMLINK on Windows. A tool
            # that only works for an administrator is one people work around.
            proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            if proc.returncode == 0:
                made.append(name)
        return made

    def _unlink_shared_deps(self, worktree: Path) -> list:
        """Remove OUR junctions before git sees the tree. ⚠⚠ THE ORDER IS THE WHOLE SAFETY
        ARGUMENT: measured 2026-08-30, `git worktree remove --force` FOLLOWS a junction and
        deletes what it points at while returning 0. Left in place, removing a worktree would
        destroy the pinned Mathlib. `Path.rmdir()` on a junction removes the LINK only, never
        the target — the same non-recursive delete that was done by hand, four times, verified."""
        removed = []
        for name in self._SHARED_DEPS:
            dst = Path(worktree) / name
            try:
                attrs = getattr(dst.lstat(), "st_file_attributes", 0)
            except OSError:
                continue
            if not (attrs & getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                continue          # a real directory here is NOT ours to delete
            try:
                dst.rmdir()
                removed.append(name)
            except OSError:
                pass
        return removed

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
            # ⚠⚠ NAME THE STALE-EARLIER-COMMITS SHAPE, BECAUSE ITS REMEDY IS NOT THE
            # OBVIOUS ONE AND THE GENERIC TEXT SENDS PEOPLE THE WRONG WAY. Coverage is
            # content-keyed, so an old commit's blobs never move and its verdicts stay
            # valid for it — EXCEPT that `evidence` points at the CHECKER, not at the
            # commit. Edit `tools/verify/*` or a brief, and every earlier commit in the
            # same range cites a checker that no longer exists: green when made, stale
            # now, through no change of theirs. Measured 2026-08-30 on 2dc895e4 — five
            # STALE, zero missing. Told only "record the verdicts", a caller goes hunting
            # for a recording bug that is not there.
            commits = inv.get("commits") or []
            tip_ok = any(c.get("is_tip") and c.get("complete") for c in commits)
            stale_under = [c for c in commits
                           if not c.get("is_tip") and not c.get("complete")
                           and (c.get("stale") or [])]
            extra = ""
            if tip_ok and stale_under:
                worst = ", ".join(sorted(stale_under[0].get("stale") or [])[:5])
                extra = (
                    f"\n\n⚠ THE TIP IS COMPLETE AND {len(stale_under)} EARLIER COMMIT(S) ARE "
                    f"STALE — e.g. {stale_under[0]['commit'][:8]}: {worst}. **That is almost "
                    f"never a recording failure, so do not go looking for one** — those commits "
                    f"recorded plenty. Call heal_plan(action='push', ref=…, admission=…): it "
                    f"reports `subjects_stale` and `evidence_stale` SEPARATELY, which is the "
                    f"distinction that tells you what to do.\n"
                    f"  · subjects_stale — the covered files changed. Ordinary, expected, and the "
                    f"common case. Re-run those checkers and record; measured 2026-08-30 the six "
                    f"usual suspects re-run in 16.1s total.\n"
                    f"  · evidence_stale — the CHECKER or BRIEF moved, so verdicts died for files "
                    f"that did not change. Same remedy, different cause; worth knowing which so "
                    f"you do not go hunting content that never moved.\n"
                    f"⚠ SQUASH IS NOT THE REMEDY FOR EITHER. It is remediation for a backlog that "
                    f"recorded nothing, and rewriting history on every push to satisfy a rule that "
                    f"exists BECAUSE intermediate commits are permanent is self-defeating. ⚠ NOTE "
                    f"the standing defect behind this: `precommit` records 11 of the commit set "
                    f"while six mechanical steps are recorded only against the TIP, so "
                    f"intermediates sit at 11/19 by construction. Moving those six into precommit "
                    f"is the fix; healing them by hand each time is the workaround.")
            raise self._refuse(
                "push", args,
                f"verdictLedger reports the admission set is not satisfied for "
                f"{short}.\n\n{rendered}",
                "Every required verdict must be recorded and passing for the EXACT hash "
                "being pushed. This is not advisory and there is no flag that skips it — "
                "a push allowed while the ledger said 0/19 is the failure this gate "
                "exists to prevent." + extra,
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
        # ⭐⭐ THE ARC STATE FILE IS NOT DIRT. It is TRACKED so every worktree inherits the
        # default, and DESIGNED to be modified locally and never committed — `worktree add`
        # seals it with `--skip-worktree` precisely so its bumps stay invisible to git.
        #
        # ⛔ BUT NOTHING CREATES THE MAIN CHECKOUT, so nothing seals it there, and a round bump
        # in the main tree reads as ordinary dirtiness. Measured 2026-09-03: `gate_round.json`
        # at round 1 in the main checkout, and **the next `merge` would have refused** — which
        # is exactly what an arc does at the end, so the arc flow would have blocked itself on
        # its own bookkeeping.
        #
        # ⚠ Counting it as dirt is the same category error as counting a build cache: a file
        # whose whole contract is "differs locally, never commits" is not uncommitted WORK.
        # Nothing is weakened — the commit backstop still refuses a STAGED non-zero round, and
        # `status` still reports the file honestly. Only the branch-moving guard stops treating
        # expected local state as a reason to refuse.
        blocking = [ln for ln in self.git.porcelain()
                    if ln[3:].strip().strip('"') != self._ARC_STATE]
        if not blocking:
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

    def squash(self, onto: str, message_file: str, *, reason: str) -> dict:
        """Replace ``onto..HEAD`` with ONE commit carrying HEAD's EXISTING tree.

        ⚠⚠ THE MESSAGE IS READ FROM A FILE, NEVER PASSED AS AN ARGUMENT — same as
        `commit`, and the first cut of this method got it wrong. It shipped with
        ``-m <message>`` on argv, which contradicted `commit`'s own stated rule for the
        one thing both tools produce: a commit object. Caught by ZeroParadox 2026-08-29,
        and the argument is that a SQUASH message is strictly worse than a commit
        message on every axis the rule names — it summarises N commits, so it is longer,
        more likely to quote prose, and more likely to carry a glyph. This corpus writes
        ε₀, ⊥ and p-adic notation into prose constantly. R-SHELL: "CONTENT NEVER TRAVELS
        ON A COMMAND LINE — argv breaks on LENGTH (Windows caps at ~32k), QUOTING and
        ENCODING; move it by file or stdin." Only the PATH goes on argv, via `-F`.

        ⭐⭐ WHY THIS EXISTS AT ALL: `can_push` WALKS EVERY COMMIT, SO INTERMEDIATES
        ARE THE PROBLEM. Measured 2026-08-29 on the convergence run:

            can_push(origin/illustrated..HEAD)      REFUSED  short 31/31
            can_push(origin/illustrated..<squashed>) REFUSED  short  1/1

        Every one of those 31 recorded nothing (`admission_state: UNSET, required: 0`),
        because they were intermediate states of a single remediation — fix, commit,
        fix, commit. `can_push` is right to refuse them: they are just as published as
        the tip, and "fetchable, bisectable, citable forever" is its own docstring's
        phrase. The two honest ways out are to certify all 31 after the fact, which
        `crossref` would correctly flag BACKFILLED, or to stop creating 31 published
        commits. This is the second. **It relaxes no gate** — it makes the published
        history equal to the tree that actually passed.

        ⚠⚠ commit-tree, NOT `reset --soft` + commit, AND THE DIFFERENCE IS THE POINT.
        The ordinary squash idiom moves the branch and rebuilds the commit FROM THE
        INDEX, so the result depends on index state at the moment it runs. This takes
        HEAD's existing tree OBJECT and gives it a new parent: the tree is not
        recomputed, it is reused by id. Verified below rather than assumed. Nothing
        reads or writes the index or the working tree, which is why this is reachable
        where `reset` is not — §3 Tier 1 refuses `reset --hard` for destroying
        uncommitted state, and this cannot touch any.

        ⚠ MEASURED THE DAY THIS WAS WRITTEN, and it is the fact that makes the
        operation worth having: verdict records survive it. A probe commit built with
        this exact shape (same tree, new sha, new parent) returned an identical
        inventory to HEAD — 18/19, same rows, same STALE. Coverage is content-keyed on
        (step, path, blob), so an identical tree inherits every verdict. Squashing does
        NOT force a re-sweep.

        ⚠ THE PUBLISHED GUARD IS THE SAME ONE `rebase` USES, for the same reason:
        rewriting commits someone has already pulled breaks their checkout and the
        damage only surfaces later. Refused, not flagged.

        ⚠ THE OLD TIP IS NAMED IN THE RECEIPT because after this the old commits are
        unreferenced. They are not gone — git keeps them until gc — and the receipt is
        how a person finds them again. An irreversible-looking operation that records
        no way back is how §7's audit stops being an audit.
        """
        if not onto or onto.startswith("-"):
            raise UsageError(f"{onto!r} is not a ref")
        if not (isinstance(reason, str) and reason.strip()):
            raise UsageError("squash requires a non-empty reason")
        if not (isinstance(message_file, str) and message_file.strip()):
            raise UsageError(
                "squash requires message_file=<path>; the message is read from a file, "
                "never passed as an argument. Write the message to a file and name it.")
        msg_path = Path(message_file)
        if not msg_path.is_file():
            raise UsageError(f"message file not found: {msg_path}")
        if not msg_path.read_text(encoding="utf-8").strip():
            raise UsageError(f"message file is empty: {msg_path}")

        args = {"onto": onto, "message_file": str(msg_path)}
        self._require_clean("squash", args, f"squashing {onto!r}..HEAD", reason=reason)

        # ⚠ A DETACHED HEAD HAS NO BRANCH TO MOVE. Refuse rather than silently
        # leaving the new commit unreferenced, which looks like success and loses it.
        head_ref = self.git.run(["symbolic-ref", "--quiet", "HEAD"])
        branch = (head_ref.stdout or "").strip()
        if not head_ref.ok or not branch.startswith("refs/heads/"):
            raise self._refuse(
                "squash", args,
                "HEAD is detached, so there is no branch to move; the squashed commit "
                "would be created and immediately unreferenced.",
                "Check out the branch you mean to rewrite first.",
                reason=reason)

        published = self._published_commits_rewritten_by(onto)
        if published:
            raise self._refuse(
                "squash", args,
                f"this would rewrite {published} commit(s) that are already on the "
                f"remote. Rewriting published history breaks every checkout that "
                f"already has it, and the damage only surfaces when someone else pulls.",
                "Squash only unpublished work. Confirm with "
                "read(op='branch', args=['-r','--contains','<oldest sha>']) — an empty "
                "result means no remote has it.",
                reason=reason)

        count = self.git.run(["rev-list", "--count", f"{onto}..HEAD"])
        n = int(count.stdout.strip()) if count.ok and count.stdout.strip().isdigit() else 0
        if n == 0:
            raise self._refuse(
                "squash", args,
                f"{onto}..HEAD is empty — there is nothing to squash.",
                "Check the base ref: read(op='log', args=['--oneline', f'{onto}..HEAD']).",
                reason=reason)

        old_tip = self.git.run(["rev-parse", "HEAD"]).stdout.strip()
        tree = self.git.run(["rev-parse", "HEAD^{tree}"])
        if not tree.ok or not tree.stdout.strip():
            raise UsageError("could not resolve HEAD's tree")
        tree_id = tree.stdout.strip()

        # ⚠ `-F <path>`: the PATH travels on argv, the CONTENT never does. Same shape as
        # `commit`'s `--file`, for the same reason.
        made = self.git.run(["commit-tree", tree_id, "-p", onto, "-F", str(msg_path)],
                            timeout=120)
        if not made.ok or not made.stdout.strip():
            return self._receipt("squash", args, "failed", reason=reason,
                                 detail=made.output,
                                 extra={"output": made.output, "ok": False})
        new_sha = made.stdout.strip()

        # ⚠⚠ VERIFY THE TREE CARRIED BEFORE MOVING THE BRANCH. The whole safety
        # argument is "the tree object is reused, not recomputed". Asserting it after
        # the fact is what separates this from hoping.
        check = self.git.run(["rev-parse", f"{new_sha}^{{tree}}"])
        if check.stdout.strip() != tree_id:
            return self._receipt(
                "squash", args, "failed", reason=reason,
                detail=(f"refusing to move {branch}: squashed commit {new_sha} has tree "
                        f"{check.stdout.strip()}, expected {tree_id}"),
                extra={"ok": False, "expected_tree": tree_id,
                       "got_tree": check.stdout.strip()})

        moved = self.git.run(["update-ref", "-m", f"squash: {reason}", branch, new_sha,
                              old_tip], timeout=120)
        decision = "allowed" if moved.ok else "failed"
        return self._receipt(
            "squash", args, decision, reason=reason, detail=moved.output,
            extra={"ok": moved.ok, "branch": branch, "onto": onto,
                   "commits_squashed": n, "old_tip": old_tip,
                   "new_sha": new_sha, "tree": tree_id, "output": moved.output})

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
            linked = self._link_shared_deps(path) if result.ok else []
            # ⭐ THE ARC OPENS HERE. Creating the worktree IS entering the arc, so the handshake
            # is sealed at the same moment — one place, the only place that makes worktrees.
            arc = self._seal_arc_state(path) if result.ok else {"sealed": False}
            return self._receipt("worktree.add", {"ref": ref, "path": str(path)}, decision,
                                 detail=result.output,
                                 extra={"path": str(path), "output": result.output,
                                        "ok": result.ok, "linked": linked,
                                        "arc_state": arc})
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
            # ⚠⚠ REFUSE BEFORE GIT EVER SEES IT. `git worktree remove` FOLLOWS JUNCTIONS and
            # deletes what they point at, returning 0 — measured 2026-08-30, a junction to a
            # scratch target was removed along with the target while git reported success. The
            # documented procedure for healing pre-fix commits puts a junction to the pinned
            # Mathlib inside a worktree, so this is the live path to destroying it.
            #
            # ⚠ REFUSE RATHER THAN AUTO-CLEAN. Silently deleting something the caller created is
            # not this tool's shape, and a refusal that NAMES the junction teaches the hazard
            # where a quiet cleanup hides it. The escape is an action, not a flag.
            # ⚠⚠ REMOVE OUR OWN JUNCTIONS FIRST, THEN LET THE GUARD JUDGE WHAT IS LEFT. The
            # ones `worktree add` created are known and safely removable (rmdir on a junction
            # takes the link, never the target). Anything still present afterwards was made by
            # hand, and THAT is what the refusal below is for — a caller who linked something we
            # do not know about must clear it themselves, because we cannot know what it points
            # at. Before this, the guard refused the tool's OWN provisioning, which would have
            # made the sanctioned worktree flow un-teardownable.
            unlinked = self._unlink_shared_deps(resolved) if resolved.exists() else []
            if resolved.exists():
                links = _reparse_points_under(resolved)
                if links:
                    raise self._refuse(
                        "worktree.remove", {"name": name},
                        f"this worktree contains {len(links)} junction/symlink(s) — "
                        f"{', '.join(links[:5])}. `git worktree remove` FOLLOWS them and deletes "
                        f"what they point at, reporting success. If one targets the pinned "
                        f"Mathlib checkout, removing this worktree destroys it.",
                        "Remove each link FIRST, non-recursively, so only the link goes and not "
                        "its target — PowerShell: [System.IO.Directory]::Delete($p, $false). "
                        "Verify the target still exists, then remove the worktree. Note "
                        "os.path.islink() returns FALSE for a junction, so do not rely on it.",
                    )
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
            return self._receipt("worktree.remove", {"name": str(path), "unlinked": unlinked},
                                 decision,
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

    def requirements(self, action: str = "push") -> dict:
        """⭐⭐ THE SUCCESS CONDITIONS FOR `action`, SERVED FROM THE CONFIG THAT ACTUALLY GATES.

        Tim, 2026-08-30: *"it might be worthwhile having a specific endpoint to call that
        documents the exact success conditions for things to work.. that way whenever a chronic
        mistake like that is made, it will have the 'this is what you need to do to fix it'
        directly in front at the right moment."*

        ⚠⚠ IT EXISTS BECAUSE gitRobot SERVED ITS ADMISSION SET NOWHERE, AND THAT CAUSED A
        MEASURED DEFECT. 2026-08-30: ZeroParadox reported `heal_plan` for dropping a failing
        gating step (`rely`). It had not — `rely` is REGISTERED but deliberately NOT ADMITTED,
        and the only queryable list was the ledger's REGISTRY, which is a superset. With no way
        to ask what actually gates, a caller derives a set, and then two internally-consistent
        systems disagree about what "complete" means. **Registered means RECORDABLE; admitted
        means REQUIRED.** That distinction had a home in a contract document nobody is obliged
        to open, and none on the tool surface where the mistake gets made.

        ⚠ EVERY FIELD IS DERIVED FROM LIVE CONFIG, NOT WRITTEN HERE. The admitted list comes
        from the same `admission.v1.json` that `_require_inventory` reads, and the exclusion
        reasons are quoted out of that file's own `_`-prefixed keys. A hand-maintained copy of
        the success conditions would be the second copy this project keeps removing — and it
        would be the most convincing kind, because it would read as authoritative.
        """
        # ⚠⚠ THE LIST COMES FROM `admission_for`, NOT FROM THE RAW DOCUMENT, AND THE FIRST
        # VERSION OF THIS GOT IT WRONG. Reading `doc["admission"][action]` directly returned []
        # for an unknown action, so `requirements("shove")` reported "0 admitted" — an unnamed
        # action rendering as unrestricted, which is the precise failure `admission_for`
        # validates against and which this tool exists to make legible. Caught by its own test.
        # `admission_doc` is used ONLY for the rationale prose below.
        admitted = sorted(ledger_client.admission_for(action))
        doc = ledger_client.admission_doc()
        # ⚠⚠ THE FIRST VERSION CALLED A FUNCTION THAT DOES NOT EXIST AND SWALLOWED THE
        # AttributeError, so `registered_not_admitted` came back `[]` — reading as "nothing is
        # excluded" when it meant "I could not look". That is a fail-open rendering as a clean
        # result, in the field this tool was BUILT to surface: the whole point is naming `rely`.
        # Caught by running it against the live repo rather than by the tests, which never
        # asserted the list was non-empty. A bare `except` around the load-bearing lookup was
        # the actual defect; the wrong name was just what triggered it.
        registry, registry_error = [], None
        try:
            registry = sorted((ledger_client.call("requirements", {}) or {}).get("types") or [])
        except Exception as exc:                       # noqa: BLE001 - reported, never hidden
            registry_error = f"{type(exc).__name__}: {exc}"
        not_admitted = sorted(set(registry) - set(admitted))
        # the file's own words for why something was excluded — never a paraphrase
        rationale = {k: v for k, v in doc.items()
                     if k.startswith("_") and isinstance(v, str)}
        return {
            "action": action,
            "admitted": admitted,
            "admitted_count": len(admitted),
            "registered_not_admitted": not_admitted,
            # ⚠ AN EMPTY LIST AND AN UNREADABLE REGISTRY MUST NOT LOOK THE SAME. If the lookup
            # failed, say so here rather than letting `[]` read as "nothing excluded".
            "registry_unreadable": registry_error,
            "_registered_vs_admitted": (
                "REGISTERED means a verdict of that type may be RECORDED. ADMITTED means it "
                "must be GREEN for this action. The registry is deliberately larger. A step in "
                "`registered_not_admitted` failing does NOT block this action — see the "
                "rationale below before spending rounds on it."),
            "exclusion_rationale": rationale,
            "preconditions": [
                "a `reason` on every mutating call — it is the only durable record of why",
                "a clean tree for anything that moves a branch (untracked files count as dirty)",
                "for push: EVERY commit in the range carries its own admission set, not just "
                "the tip — can_push walks them all",
                "no force, no lease, no --no-verify: no parameter reaches them, so the "
                "pre-push hook always runs as the backstop",
            ],
            "order_of_operations": [
                "1. heal_plan(action, ref, admission) — ask what is owed",
                "2. FIX everything in `blocked` first. Those are FAILED, not stale; re-running "
                "finds the same finding, and recording before the fix buys keys that die on "
                "the next commit",
                "3. THEN re-run everything in `auto` and record (mechanical, no judgement)",
                "4. `agent` needs a review round — an agent and a judgement, never automated",
                "5. push(branch, reason) — returns a run_id; poll push_status()",
            ],
            "which_tool_answers_what": {
                "may this action proceed?": "verdictLedger inventory(action, ref, admission) -> complete",
                "may this RANGE be pushed?": "verdictLedger can_push(rev_range, admission, commit_admission)",
                "what do I need to re-run?": "verdictLedger heal_plan(action, ref, admission)",
                "which PATHS does step X owe?": "verdictLedger coverage_gap(step=X)",
                "is it converging?": "verdictLedger progress(action, ref, admission)",
                "what gates this action?": "gitRobot requirements(action) — this call",
                "why was I refused?": "gitRobot explain(refusal_id)",
            },
            "source": "gitRobot/config/admission.v1.json (the file _require_inventory reads)",
        }


def _reparse_points_under(root: Path, limit: int = 20) -> list:
    """Every junction / symlink / reparse point inside `root`, as relative paths.

    ⭐⭐ MEASURED 2026-08-30, AND THE RESULT IS THE REASON THIS EXISTS:

        git worktree add --detach wt HEAD     rc=0
        mklink /J wt/.lake -> REAL/           rc=0
        git worktree remove --force wt        rc=0     <- reports SUCCESS
        PRECIOUS SURVIVED:                    False    <- the target was DELETED

    **`shutil.rmtree` does not follow junctions; `git worktree remove` DOES.** So the safety
    argument that covers gitRobot's ORPHAN path does not cover its REGISTERED path, which shells
    out to git — a control whose reasoning is about a different code path than the one that runs.

    ⚠ THIS IS NOT HYPOTHETICAL. Healing pre-fix commits requires checking each one out in a
    worktree and running the checkers there, and a fresh worktree has no `.lake`, so `check_paths`
    withholds. The documented remedy is a directory junction to the main checkout's `.lake` —
    which points at the pinned Mathlib. Removing that worktree through git deletes it.

    ⚠⚠ `os.path.islink()` RETURNS FALSE FOR A JUNCTION (Python 3.12.10, measured), so the obvious
    guard does not fire. Detection is the REPARSE POINT attribute, which is the thing junctions
    and symlinks actually share.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in list(dirnames) + list(filenames):
            full = Path(dirpath) / name
            try:
                attrs = getattr(full.lstat(), "st_file_attributes", 0)
            except OSError:
                continue
            if attrs & getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                found.append(str(full.relative_to(root)))
                if len(found) >= limit:
                    return found
        # ⚠ DO NOT DESCEND INTO ONE WHILE LOOKING FOR THEM. Walking into a junction would
        # enumerate the target — here that is the whole of Mathlib, and it would also report
        # its contents as if they lived in the worktree.
        dirnames[:] = [d for d in dirnames
                       if not (getattr((Path(dirpath) / d).lstat(), "st_file_attributes", 0)
                               & getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))]
    return found
