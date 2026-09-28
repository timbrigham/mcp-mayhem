"""The ONLY place that invokes git. Everything else asks this module.

Two properties the rest of the design leans on:

* **No shell.** Every call is an argv list handed to ``subprocess.run`` with
  ``shell=False``. There is no string a caller can inject a second command into,
  no quoting to get wrong, and no ``| head`` that can close a pipe and kill a
  hook before its ``exit 1`` (which is how a push gate was bypassed here once).
* **One repository.** The path is resolved at construction and never comes from
  a caller. gitRobot is an allow-list of one; accepting a ``repo`` argument would
  make it a general-purpose git proxy for every checkout on the machine — a
  strictly worse hole than the one it closes.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from core.errors import RepoError

# git is invoked with these globals ALWAYS. `-c core.hooksPath=` is deliberately
# NOT here and must never be: the installed hooks are a layer gitRobot protects,
# not one it overrides.
_BASE_ARGS = (
    "--no-pager",          # never page; there is no terminal to page into
)

DEFAULT_TIMEOUT = 120


@dataclass(frozen=True)
class GitResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        """stdout and stderr joined — hooks write their verdict to both."""
        parts = [p for p in (self.stdout.strip(), self.stderr.strip()) if p]
        return "\n".join(parts)


class Git:
    """A git invoker bound to exactly one working tree."""

    def __init__(self, repo: str | os.PathLike, *, timeout: int = DEFAULT_TIMEOUT):
        self.repo = Path(repo).resolve()
        self.timeout = timeout

    # -- resolution -----------------------------------------------------------

    def require_repo(self) -> Path:
        """Fail loudly at startup rather than mysteriously at first use."""
        if not self.repo.exists():
            raise RepoError(f"configured repository does not exist: {self.repo}")
        if not (self.repo / ".git").exists():
            raise RepoError(f"not a git repository (no .git): {self.repo}")
        return self.repo

    def sub_repo(self, name: str) -> "Git":
        """A nested repository inside the configured tree, named — never a free path.

        ``.claude-local`` is a separate repo living inside the main checkout with
        its own rules (``add -A`` is its documented flow). Reaching it as a NAMED
        mode keeps that exception enumerable; taking a path argument would reopen
        the general-proxy hole this class exists to close.
        """
        target = (self.repo / name).resolve()
        if self.repo not in target.parents:
            raise RepoError(f"{name!r} does not resolve inside {self.repo}")
        if not (target / ".git").exists():
            raise RepoError(f"{name!r} is not a git repository: {target}")
        return Git(target, timeout=self.timeout)

    # -- invocation -----------------------------------------------------------

    def run(self, args: Sequence[str], *, timeout: Optional[int] = None,
            check: bool = False, byte_faithful: bool = False) -> GitResult:
        """Run git. ``byte_faithful=True`` preserves the EXACT bytes git emitted.

        ⛔⛔ THE DEFAULT PATH IS LOSSY BY DESIGN AND THAT IS FINE UNTIL THE OUTPUT *IS* CONTENT.
        `text=True` applies universal-newline translation, so `\\r\\n` arrives as `\\n`, and
        `errors="replace"` substitutes U+FFFD for anything not valid UTF-8. Both are right for a
        transcript a human reads; both destroy a file.

        ⚠⚠ MEASURED 2026-09-27 on a 20-byte CRLF blob: `cf9b2a85` on disk came back as 18 bytes
        hashing to `e5c5c558`. **So a `byte_faithful: True` field on the default path would have
        been a FALSE CLAIM, and I nearly shipped one** — caught only by testing the assertion
        against a CRLF fixture before committing it, rather than against the LF file that had
        exposed the original bug.

        ⭐ `surrogateescape` IS THE LOAD-BEARING CHOICE, not `replace`. It round-trips arbitrary
        bytes through `str` losslessly, so `.encode("utf-8", "surrogateescape")` recovers exactly
        what git wrote — including a PDF or any non-UTF-8 blob. `replace` would silently substitute
        and make the corruption unrecoverable rather than merely present.
        """
        argv = ["git", *_BASE_ARGS, *args]
        # ⚠⚠ BYTES MODE, THEN DECODE BY HAND — `subprocess.run` HAS NO `newline` PARAMETER, and my
        # first attempt passed one and raised `TypeError` on the first call. There is no way to keep
        # `text=True` and disable universal-newline translation, so the only faithful route is to
        # capture bytes and decode explicitly.
        _binary = byte_faithful
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.repo),
                capture_output=True,
                shell=False,                      # never; see the module docstring
                timeout=timeout or self.timeout,
                **({} if _binary else
                   {"text": True, "encoding": "utf-8", "errors": "replace"}),
            )
        except FileNotFoundError as exc:
            raise RepoError("git executable not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise RepoError(
                f"git {' '.join(args)} timed out after {timeout or self.timeout}s"
            ) from exc
        # ⭐ `surrogateescape` IS WHAT MAKES THE DECODE REVERSIBLE. `.encode("utf-8",
        # "surrogateescape")` recovers exactly the bytes git wrote, including a PDF or any
        # non-UTF-8 blob. `errors="replace"` — the default path — substitutes U+FFFD and makes the
        # loss unrecoverable rather than merely present, which is right for a transcript and fatal
        # for content.
        if _binary:
            _out = (proc.stdout or b"").decode("utf-8", "surrogateescape")
            _err = (proc.stderr or b"").decode("utf-8", "surrogateescape")
        else:
            _out, _err = proc.stdout or "", proc.stderr or ""
        result = GitResult(argv=argv, exit_code=proc.returncode,
                           stdout=_out, stderr=_err)
        if check and not result.ok:
            raise RepoError(f"git {' '.join(args)} failed ({result.exit_code}): "
                            f"{result.output}")
        return result

    # -- state the audit and the guards need ---------------------------------

    def head(self) -> Optional[str]:
        res = self.run(["rev-parse", "HEAD"])
        return res.stdout.strip() if res.ok else None

    def branch(self) -> Optional[str]:
        res = self.run(["rev-parse", "--abbrev-ref", "HEAD"])
        return res.stdout.strip() if res.ok else None

    def porcelain(self) -> list[str]:
        """`status --porcelain` lines. Empty list = clean tree (tracked AND untracked)."""
        res = self.run(["status", "--porcelain"])
        if not res.ok:
            raise RepoError(f"could not read status: {res.output}")
        return [ln for ln in res.stdout.splitlines() if ln.strip()]

    def is_dirty(self) -> bool:
        return bool(self.porcelain())

    def tree_state(self) -> dict:
        """A compact snapshot for the audit record.

        Records the counts, not the file list: the audit is a receipt, and a
        1000-line status dump per record would bury the signal it exists to keep.
        """
        # ⚠⚠ GRB-3. `staged` used to be `ln[:1].strip()`, which is TRUE for the "?"
        # of an untracked "?? path" line. Measured twice 2026-08-23: `staged: 3,
        # untracked: 3` for the same three files, while `status --short` showed three
        # `??` and `diff --cached` was empty. A caller that trusts that count commits
        # nothing and believes it committed three files.
        #
        # Porcelain v1 is two status characters then a space then the path. X is the
        # INDEX state and Y the WORK TREE state; "?" and "!" are not states, they are
        # the whole-line markers for untracked and ignored. Testing "is X non-blank"
        # therefore had to be wrong for exactly those two.
        lines = self.porcelain()
        staged = unstaged = untracked = ignored = unmerged = 0
        for ln in lines:
            x, y = (ln[:1] or " "), (ln[1:2] or " ")
            if ln.startswith("??"):
                untracked += 1
                continue
            if ln.startswith("!!"):
                ignored += 1
                continue
            # ⚠ A conflicted path is neither staged nor unstaged; counting "UU" as
            # both is the same miscount GRB-3 was, one state over.
            if "U" in (x, y) or (x, y) in (("A", "A"), ("D", "D")):
                unmerged += 1
                continue
            if x != " ":
                staged += 1
            if y != " ":
                unstaged += 1
        return {"dirty": bool(lines), "staged": staged, "unstaged": unstaged,
                "untracked": untracked, "ignored": ignored, "unmerged": unmerged}

    def unpushed_count(self) -> Optional[int]:
        """Commits on HEAD not on its upstream. None when there is no upstream."""
        res = self.run(["rev-list", "--count", "@{upstream}..HEAD"])
        if not res.ok:
            return None
        try:
            return int(res.stdout.strip())
        except ValueError:
            return None
