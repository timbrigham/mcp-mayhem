"""Tier classification — the policy, split by MUTATION rather than by subcommand.

The split that matters is what an operation can DESTROY, not how git's own
command list is organised. Mirroring git 1:1 would produce a proxy, not a guard.

  Tier 1  REFUSED   destroys uncommitted work and reports success
  Tier 2  MEDIATED  runs, but gitRobot owns how
  Tier 3  READ      allow-listed, no gates, no audit, always available

⚠ Tier 3 is an ALLOW-LIST and everything unrecognised falls through to refusal.
That inversion is the point: an enumerated deny-list permits every subcommand
nobody has thought of yet, which is this project's most repeated defect. Here an
unclassified operation is refused until someone classifies it.

⚠ Tier 3 must stay cheap and unconditional. An agent that cannot read repository
state is blind, and a blind agent makes worse decisions, not safer ones — so
reads never gate, never audit, and never depend on anything but a subprocess call.
"""

from __future__ import annotations

from typing import Optional, Sequence

# -- Tier 3 -------------------------------------------------------------------
#
# subcommand -> the argument forms that stay read-only. None = the whole
# subcommand is read-only whatever its flags. A tuple = only these first
# arguments are allowed (e.g. `branch --list` reads, `branch -D` deletes).
READ_OPS: dict[str, Optional[tuple[str, ...]]] = {
    "status": None,
    "log": None,
    "diff": None,
    "show": None,
    "ls-files": None,
    "ls-remote": None,
    "rev-parse": None,
    "rev-list": None,
    "cat-file": None,
    "describe": None,
    "blame": None,
    "shortlog": None,
    "config": ("--get", "--get-all", "--list", "-l"),
    "branch": ("--list", "-l", "-v", "-vv", "--show-current", "--contains", "-a", "-r"),
    "remote": ("-v", "show", "get-url"),
    "worktree": ("list",),
    "stash": ("list", "show"),      # inspecting the stash is a read; stashing is Tier 1
    "tag": ("--list", "-l", "-n"),
}

# Flags that redirect an operation out from under every other control: a
# different hook path, a different repository, a different work tree, a
# different exec path. Refused on ANY tier, reads included — a "read" pointed at
# another checkout is not a read of this one.
FORBIDDEN_GLOBALS = (
    "-c", "--exec-path", "--git-dir", "--work-tree", "--namespace",
    "--config-env", "--no-replace-objects", "-C",
)

# Flags that disable the very gates gitRobot exists to keep. Never accepted,
# never synthesised internally. The tool surface has no parameter that could
# reach them either — see tests/test_absent_controls.py.
FORBIDDEN_FLAGS = ("--no-verify", "-n", "--force", "-f", "--force-with-lease")


# -- Tier 1 -------------------------------------------------------------------
#
# Each entry: a predicate over (subcommand, args) and the refusal it produces.
# The alternative is part of the data, not an afterthought — every refusal names
# what to do instead.

_WORKTREE_ALTERNATIVE = (
    "Work in a throwaway checkout instead: worktree(action='add', ref=<ref>) gives you a "
    "private HEAD, index and working tree under the scratch area, so nothing you do there "
    "can reach the caller's files. worktree(action='remove', name=…) when you are done."
)

_UNCOMMITTED_HARM = (
    "It discards uncommitted work in the shared tree and then reports success — the most "
    "expensive incident recorded in this project was exactly that, and no git hook fires on "
    "it, so nothing downstream would have caught it either."
)


def _is_reset_hard(sub: str, args: Sequence[str]) -> bool:
    return sub == "reset" and any(a in ("--hard", "--merge", "--keep") for a in args)


def _is_checkout_paths(sub: str, args: Sequence[str]) -> bool:
    """`checkout -- <paths>` / `restore <paths>` overwrite files from the index."""
    if sub == "restore":
        return "--staged" not in args        # --staged only unstages; it keeps the file
    return sub in ("checkout", "switch") and "--" in args


def _is_clean(sub: str, args: Sequence[str]) -> bool:
    return sub == "clean"


def _is_stash_mutating(sub: str, args: Sequence[str]) -> bool:
    if sub != "stash":
        return False
    if not args:
        return True                          # bare `git stash` == push
    return args[0] not in ("list", "show")


TIER1_RULES = (
    (_is_reset_hard,
     "reset --hard (and --merge/--keep) overwrites the working tree from a commit.",
     _WORKTREE_ALTERNATIVE),
    (_is_checkout_paths,
     "checkout -- <paths> / restore <paths> overwrites files from the index.",
     "To see what would be lost, read(op='diff'). To work from a clean state, "
     + _WORKTREE_ALTERNATIVE),
    (_is_clean,
     "clean deletes untracked files outright.",
     "Untracked files are usually the caller's in-progress work. Identify them with "
     "read(op='status') and delete named paths deliberately if that is really the intent; "
     "for a clean slate, " + _WORKTREE_ALTERNATIVE),
    (_is_stash_mutating,
     "stash moves uncommitted work off the tree into a place the caller will not think to look.",
     "stash list / stash show are readable via read(). To set work aside, commit it on a "
     "branch where it is visible, or " + _WORKTREE_ALTERNATIVE),
)


def tier1_refusal(sub: str, args: Sequence[str]) -> Optional[tuple[str, str]]:
    """``(what, alternative)`` if this is a Tier 1 operation, else ``None``."""
    for predicate, what, alternative in TIER1_RULES:
        if predicate(sub, args):
            return f"{what} {_UNCOMMITTED_HARM}", alternative
    return None


# -- Tier 3 classification -----------------------------------------------------

# Operations that ARE available, just not through `read`. Without this a caller
# who asks for a mutation gets the generic "not an allow-listed read" and has to
# guess which tool does it — and guessing is how people end up looking for a way
# around the wall instead of the door beside it.
MEDIATED_ELSEWHERE: dict[str, str] = {
    "add": "stage(paths=[…])",
    "commit": "commit(message_file=…)",
    "push": "preflight() then push(branch=…, reason=…)",
    "fetch": "fetch()",
    "pull": "fetch() then merge(branch=…, reason=…) — pull is fetch+merge in one "
            "step, and the merge half is the half that needs a clean tree and an audit row",
    "switch": "switch(branch=…)",
    "merge": "merge(branch=…, reason=…)",
    "rebase": "rebase(onto=…, reason=…)",
    # ⚠ THE TWO PLUMBING COMMANDS `squash` IS BUILT FROM. A caller who has worked out
    # that commit-tree collapses a range is reaching for the right operation through the
    # wrong door, and the generic "not an allow-listed read" would send them looking for
    # a way around rather than at the tool that does it with the published-history guard.
    "commit-tree": "squash(onto=…, message=…, reason=…)",
    "update-ref": "squash(onto=…, message=…, reason=…) moves the branch as part of a "
                  "squash; there is no general branch-pointer write, because one would "
                  "reach every Tier 1 outcome without naming any of them",
    "rm": "remove_files(paths=[…], reason=…)",
    "mv": "remove_files(...) plus stage(...) — a rename is a delete and an add, and "
          "gitRobot would rather you see both",
}


def forbidden_token(args: Sequence[str]) -> Optional[str]:
    """The first redirect/gate-disabling flag present, if any."""
    for arg in args:
        if arg in FORBIDDEN_GLOBALS or arg in FORBIDDEN_FLAGS:
            return arg
        # --git-dir=… / --work-tree=… / --config-env=… attached forms
        head = arg.split("=", 1)[0]
        if head != arg and head in FORBIDDEN_GLOBALS:
            return head
    return None


def is_read(sub: str, args: Sequence[str]) -> bool:
    """Is this an allow-listed, side-effect-free read?"""
    if sub not in READ_OPS:
        return False
    if forbidden_token(args):
        return False
    allowed_first = READ_OPS[sub]
    if allowed_first is None:
        return True
    return bool(args) and args[0] in allowed_first
