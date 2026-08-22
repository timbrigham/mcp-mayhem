"""CLI over the gitRobot library.

``core`` is a working tool with no MCP installed — the same separation the
sibling registry keeps, and for the same reason: if the server is down, the rules
still exist and can still be run by a human. Enforcement lives in the library;
this is a thin argument parser.

Exit codes: 0 success; 1 refusal / gate failure / git failure; 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from core.engine import GitRobot
from core.errors import GitRobotError, RefusalError, UsageError

DEFAULT_REPO = os.environ.get("GITROBOT_REPO", r"C:\Workspace\ZeroParadox")
DEFAULT_DATA = os.environ.get("GITROBOT_DATA", "data/git_ops.jsonl")


def _robot(args) -> GitRobot:
    return GitRobot(args.repo, data_path=args.data, actor=args.actor)


def _emit(payload) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def cmd_read(args) -> int:
    _emit(_robot(args).read(args.op, args.args, repo_mode=args.repo_mode))
    return 0


def cmd_status(args) -> int:
    _emit(_robot(args).status())
    return 0


def cmd_stage(args) -> int:
    _emit(_robot(args).stage(args.paths, repo_mode=args.repo_mode))
    return 0


def cmd_commit(args) -> int:
    result = _robot(args).commit(args.message_file, reason=args.reason,
                                 repo_mode=args.repo_mode)
    _emit(result)
    return 0 if result.get("ok", True) else 1


def cmd_preflight(args) -> int:
    result = _robot(args).preflight(reason=args.reason)
    _emit(result)
    return 0 if result["passed"] else 1


def cmd_push(args) -> int:
    result = _robot(args).push(args.branch, reason=args.reason)
    _emit(result)
    return 0 if result.get("ok", True) else 1


def cmd_worktree(args) -> int:
    _emit(_robot(args).worktree(args.action, ref=args.ref, name=args.name))
    return 0


def cmd_explain(args) -> int:
    _emit(_robot(args).explain(args.refusal_id))
    return 0


def cmd_history(args) -> int:
    _emit(_robot(args).history(limit=args.limit))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gitrobot",
        description="Mediated git for one repository: destructive operations refused, "
                    "mutating operations gated and audited, reads passed through.")
    p.add_argument("--repo", default=DEFAULT_REPO,
                   help="the ONE repository this may act on (env GITROBOT_REPO)")
    p.add_argument("--data", default=DEFAULT_DATA,
                   help="append-only operation log (env GITROBOT_DATA)")
    p.add_argument("--actor", default=os.environ.get("GITROBOT_ACTOR", "cli"),
                   help="actor recorded in the log")
    p.add_argument("--repo-mode", default="main", dest="repo_mode",
                   help="'main' or '.claude-local' (a named nested repo, never a path)")
    sub = p.add_subparsers(dest="command", required=True)

    # REMAINDER so flags reach the allow-list check instead of argparse:
    # `read log -1 --oneline` must arrive as args, not die as an unknown option.
    r = sub.add_parser("read", help="allow-listed read-only git")
    r.add_argument("op")
    r.add_argument("args", nargs=argparse.REMAINDER)
    r.set_defaults(func=cmd_read)

    sub.add_parser("status", help="tree, branch, unpushed, and what would block a push"
                   ).set_defaults(func=cmd_status)

    # REMAINDER for the same reason, and additionally so `stage -A` reaches the
    # REFUSAL (with its explanation) rather than an argparse usage error, which
    # would teach nothing about why bulk staging is refused here.
    s = sub.add_parser("stage", help="stage NAMED paths (no bulk form)")
    s.add_argument("paths", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_stage)

    c = sub.add_parser("commit", help="commit the staged index; message read from a FILE")
    c.add_argument("message_file")
    c.add_argument("--reason", default=None)
    c.set_defaults(func=cmd_commit)

    f = sub.add_parser("preflight", help="run the pre-push pipeline WITHOUT pushing")
    f.add_argument("--reason", default=None)
    f.set_defaults(func=cmd_preflight)

    u = sub.add_parser("push", help="push a branch (requires a passing preflight for HEAD)")
    u.add_argument("branch")
    u.add_argument("--reason", required=True)
    u.set_defaults(func=cmd_push)

    w = sub.add_parser("worktree", help="private throwaway checkouts")
    w.add_argument("action", choices=["add", "list", "remove"])
    w.add_argument("--ref", default=None)
    w.add_argument("--name", default=None)
    w.set_defaults(func=cmd_worktree)

    e = sub.add_parser("explain", help="why an operation was refused")
    e.add_argument("refusal_id")
    e.set_defaults(func=cmd_explain)

    h = sub.add_parser("history", help="the append-only operation log")
    h.add_argument("--limit", type=int, default=20)
    h.set_defaults(func=cmd_history)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # argparse claims a leading-dash token for itself before REMAINDER can see it,
    # so `gitrobot stage -A` would die as "unrecognized arguments" — a usage error
    # that teaches nothing and invites the caller to reach for raw git instead.
    # Hand the leftovers to the operation so it produces its REFUSAL, which
    # explains why bulk staging is refused and what to do instead. Argument ORDER
    # is not preserved by this merge; legitimate paths never begin with '-', so the
    # only thing affected is the shape of a message that is about to refuse anyway.
    args, extra = parser.parse_known_args(argv)
    if extra:
        if getattr(args, "command", None) == "stage":
            args.paths = list(args.paths) + extra
        elif getattr(args, "command", None) == "read":
            args.args = list(args.args) + extra
        else:
            parser.error("unrecognized arguments: " + " ".join(extra))
    try:
        return args.func(args)
    except RefusalError as exc:
        print(str(exc), file=sys.stderr)
        if exc.refusal_id:
            print(f"\n(refusal id {exc.refusal_id})", file=sys.stderr)
        return 1
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except GitRobotError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
