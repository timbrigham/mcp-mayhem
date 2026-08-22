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
import os
import threading
from pathlib import Path
from typing import Any, Optional, Sequence

from core import tiers
from core.audit import AuditLog
from core.errors import RefusalError, RepoError, UsageError
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
                reason: Optional[str] = None) -> RefusalError:
        """Record the refusal, then return the error for the caller to raise.

        Refusals are audited exactly like allowed operations. A guard that only
        writes a record when it lets something through cannot answer "did this
        ever fire?", which is the question that matters after an incident.
        """
        rid = _refusal_id(op, what)
        self._refusals[rid] = {"op": op, "args": args, "what": what,
                               "alternative": alternative}
        self.audit.append(
            actor=self.actor, op=op, args=args, decision="refused",
            head=self.git.head(), branch=self.git.branch(), tree=self.git.tree_state(),
            reason=reason, detail=f"[{rid}] {what}", alternative=alternative,
        )
        return RefusalError(f"{what}\n\nINSTEAD: {alternative}",
                            alternative=alternative, refusal_id=rid)

    def _receipt(self, op: str, args: Any, decision: str, *, gates=None,
                 reason=None, detail=None, extra: Optional[dict] = None) -> dict:
        record = self.audit.append(
            actor=self.actor, op=op, args=args, decision=decision,
            head=self.git.head(), branch=self.git.branch(), tree=self.git.tree_state(),
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
            raise self._refuse(
                "read", {"op": op, "args": args},
                f"{('git ' + op + ' ' + ' '.join(args)).strip()!r} is not an "
                f"allow-listed read.",
                f"Read operations available: {allowed}. If this is a MUTATION use the "
                f"dedicated tool (stage / commit / push / worktree). If it is genuinely a "
                f"read that belongs on the list, say so — the list is meant to grow "
                f"deliberately, which is why an unclassified operation is refused rather "
                f"than assumed safe.",
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
        preflight = self._fresh_preflight()
        if preflight is None:
            blockers.append("no passing pre-push preflight for the current HEAD "
                            "(run preflight() first)")
        return {
            "repo": str(self.repo), "branch": branch, "head": self.git.head(),
            "tree": tree, "unpushed": unpushed,
            "gates_available": self.gates.available(),
            "preflight_ok": preflight is not None,
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
        target = self._target(repo_mode)
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
                                 detail=result.output, extra={"error": result.output})
        return self._receipt("stage", {"paths": paths, "repo": repo_mode}, "allowed",
                             extra={"staged": paths})

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
                reason=reason,
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
            extra={"output": result.output, "ok": result.ok},
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

    def _fresh_preflight(self) -> Optional[dict]:
        """The completed, PASSING preflight for the current HEAD, if there is one.

        A ``started`` row never satisfies this: an in-flight or interrupted run is
        not a verdict.
        """
        head = self.git.head()
        if head is None:
            return None
        record = self.audit.last_where(op="preflight", head=head, decision="allowed")
        return record

    def push(self, branch: str, *, reason: Optional[str] = None) -> dict:
        """Push a branch, only on a passing preflight for the current HEAD.

        There is no force, no lease, no upstream override and no ``--no-verify``:
        the tool surface has no parameter that reaches any of them, so the
        installed pre-push hook runs as the backstop on every push gitRobot makes.
        """
        if not branch or not isinstance(branch, str):
            raise UsageError("push requires a branch name")
        if branch.startswith("-") or branch.startswith("private/"):
            raise self._refuse(
                "push", {"branch": branch},
                f"{branch!r} is not a pushable branch name here "
                f"(private/* never reaches a remote; a leading '-' is a flag, not a branch).",
                "Push the working branch by name, e.g. push(branch='illustrated').",
                reason=reason,
            )
        if not reason:
            raise self._refuse(
                "push", {"branch": branch},
                "push requires a reason.",
                "Say what this push is for in one line: push(branch=…, reason='…'). It goes "
                "in the audit log, which is the only durable record of why a publication "
                "happened.",
            )
        preflight = self._fresh_preflight()
        if preflight is None:
            raise self._refuse(
                "push", {"branch": branch},
                "no passing pre-push preflight for the current HEAD.",
                "Run preflight() first and read its findings. That is deliberate: a gate that "
                "runs inside the push reports after the push has already happened, which is no "
                "window at all. A preflight is bound to the HEAD it ran against, so commit "
                "first, then preflight, then push.",
                reason=reason,
            )
        result = self.git.run(["push", "origin", branch], timeout=900)
        decision = "allowed" if result.ok else "failed"
        return self._receipt(
            "push", {"branch": branch}, decision,
            gates=preflight.get("gates"), reason=reason, detail=result.output,
            extra={"output": result.output, "ok": result.ok},
        )

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
            path = self.scratch / f"{safe}-{_refusal_id('wt', str(self.scratch / safe))}"
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
                raise self._refuse(
                    "worktree.remove", {"name": name},
                    f"{name!r} is not a worktree of this repository.",
                    f"worktree(action='list') shows what can be removed. If the directory is "
                    f"already gone, worktree(action='prune') clears its leftover record.",
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

    def history(self, limit: int = 20) -> dict:
        records = self.audit.read(limit=limit)
        return {"count": len(records), "path": str(self.audit.path), "records": records}
