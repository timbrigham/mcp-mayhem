"""CLI over the ledger library. `core` works with no MCP installed.

Exit codes: 0 success; 1 a refusal / violation / finding; 2 usage or config error.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from core import canpush as canpush_mod
from core import crossref as crossref_mod
from core import inventory as inventory_mod
from core import render as render_mod
from core import signals as signals_mod
from core.errors import ConfigError, LedgerError, UsageError, ValidationFailure
from core.ledger import Ledger


def _emit(payload) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _ledger(args) -> Ledger:
    return Ledger(args.data)


def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _files_at(repo, ref):
    """path -> blob sha for a ref, or for the staged index when ref is 'staged'.

    ⚠ 'staged' resolves through `git write-tree`, which exists BEFORE the commit
    does — the commit sha does not, because checks run before the object.
    """
    if ref == "staged":
        listing = _git(repo, "ls-files", "-s")
    else:
        listing = _git(repo, "ls-tree", "-r", ref)
    out = {}
    for line in listing.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out[line.split("\t", 1)[-1].strip() if "\t" in line else parts[-1]] = parts[2]
    return out


def cmd_status(args) -> int:
    _emit(_ledger(args).status())
    return 0


def cmd_validate(args) -> int:
    record = json.loads(Path(args.file).read_text(encoding="utf-8"))
    result = _ledger(args).validate(record)
    _emit(result)
    return 0 if result["ok"] else 1


def cmd_append(args) -> int:
    record = json.loads(Path(args.file).read_text(encoding="utf-8"))
    _emit(_ledger(args).append(record))
    return 0


def cmd_genesis(args) -> int:
    _emit(_ledger(args).seed_genesis(args.commit, args.note))
    return 0


def cmd_get(args) -> int:
    rec = _ledger(args).get(args.id)
    if rec is None:
        print(f"no record {args.id!r}", file=sys.stderr)
        return 1
    _emit(rec)
    return 0


def cmd_find(args) -> int:
    _emit(_ledger(args).find(step=args.step, verdict=args.verdict, limit=args.limit))
    return 0


def cmd_render(args) -> int:
    rec = _ledger(args).get(args.id)
    if rec is None:
        print(f"no record {args.id!r}", file=sys.stderr)
        return 1
    print(render_mod.render(rec))
    return 0


def cmd_requirements(args) -> int:
    led = _ledger(args)
    _emit(led._require_config().requirements(args.action))
    return 0


def cmd_inventory(args) -> int:
    led = _ledger(args)
    cfg = led._require_config()
    files = _files_at(args.repo, args.ref)
    inv = inventory_mod.build(config=cfg, records=led.store.records(),
                              action=args.action, files=files, ref=args.ref)
    print(render_mod.render_inventory(inv))
    if args.json:
        _emit(inv)
    return 0 if inv["complete"] else 1


def cmd_can_push(args) -> int:
    led = _ledger(args)
    result = canpush_mod.check(records=led.store.records(),
                               config=led._require_config(), repo=args.repo,
                               rev_range=args.range, action=args.action,
                               admission=args.admit, limit=args.limit)
    if args.json:
        _emit(result)
    else:
        print(canpush_mod.render(result))
    return 0 if result.get("allowed") else 1


def cmd_crossref(args) -> int:
    led = _ledger(args)
    result = crossref_mod.check(records=led.store.records(),
                                config=led._require_config(), repo=args.repo,
                                since=args.since, limit=args.limit)
    _emit(result)
    return 0 if result["ok"] else 1


def cmd_signals(args) -> int:
    led = _ledger(args)
    _emit(signals_mod.compute(records=led.store.records(), config=led.config,
                              family=args.family, step=args.step))
    return 0


def cmd_coverage(args) -> int:
    led = _ledger(args)
    paths = list(_files_at(args.repo, args.ref))
    _emit(inventory_mod.coverage(records=led.store.records(), paths=paths))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zpledger",
        description="Append-only validated record store for gate verdicts.")
    p.add_argument("--data", default=os.environ.get("ZPLEDGER_DATA"),
                   help="the append-only stream (env ZPLEDGER_DATA)")
    p.add_argument("--repo", default=os.environ.get("ZPLEDGER_REPO",
                                                    r"C:\Workspace\ZeroParadox"),
                   help="the repo whose content is judged (env ZPLEDGER_REPO)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="stream health, config state, genesis floor"
                   ).set_defaults(func=cmd_status)

    v = sub.add_parser("validate", help="validate a record file; no write")
    v.add_argument("file")
    v.set_defaults(func=cmd_validate)

    a = sub.add_parser("append", help="validate then append a record file")
    a.add_argument("file")
    a.set_defaults(func=cmd_append)

    g = sub.add_parser("genesis", help="seed the recording floor")
    g.add_argument("commit")
    g.add_argument("--note", default=None)
    g.set_defaults(func=cmd_genesis)

    ge = sub.add_parser("get", help="one record by id")
    ge.add_argument("id")
    ge.set_defaults(func=cmd_get)

    f = sub.add_parser("find", help="query the stream")
    f.add_argument("--step", default=None)
    f.add_argument("--verdict", default=None)
    f.add_argument("--limit", type=int, default=50)
    f.set_defaults(func=cmd_find)

    r = sub.add_parser("render", help="THE human line for one record")
    r.add_argument("id")
    r.set_defaults(func=cmd_render)

    rq = sub.add_parser("requirements", help="which types bind for an action")
    rq.add_argument("action")
    rq.set_defaults(func=cmd_requirements)

    i = sub.add_parser("inventory", help="required vs satisfied for a ref (exit 1 if short)")
    i.add_argument("action")
    i.add_argument("--ref", default="staged")
    i.add_argument("--json", action="store_true")
    i.set_defaults(func=cmd_inventory)

    cp = sub.add_parser("can-push",
                        help="may this RANGE be pushed? one answer, every commit in it")
    cp.add_argument("range", help="a git range expression, e.g. origin/main..main")
    cp.add_argument("--action", default="push")
    cp.add_argument("--admit", action="append", default=None,
                    help="a type that must be green; repeat. Omitted means UNSET, "
                         "which refuses -- it is not an empty set")
    cp.add_argument("--limit", type=int, default=canpush_mod.DEFAULT_LIMIT)
    cp.add_argument("--json", action="store_true")
    cp.set_defaults(func=cmd_can_push)

    c = sub.add_parser("crossref",
                       help="audit git history: did anything land without the gate?")
    c.add_argument("--since", default=None,
                   help="floor commit (defaults to the genesis record)")
    c.add_argument("--limit", type=int, default=crossref_mod.DEFAULT_LIMIT,
                   help="cap on commits audited; 0 for the whole range. Truncation is reported")
    c.set_defaults(func=cmd_crossref)

    s = sub.add_parser("signals", help="the signal families; prints counts clean or not")
    s.add_argument("--family", default=None)
    s.add_argument("--step", default=None)
    s.set_defaults(func=cmd_signals)

    cv = sub.add_parser("coverage", help="tracked paths minus everything ever examined")
    cv.add_argument("--ref", default="HEAD")
    cv.set_defaults(func=cmd_coverage)
    return p


def _utf8_stdout() -> None:
    """⚠ Refusal text carries ⚠ and — , and a Windows console defaults to cp1252.
    Without this the tool raises UnicodeEncodeError and prints NOTHING — the
    refusal that matters most would crash instead of explaining itself. Measured
    2026-08-23 while proving the ledger gate.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValidationFailure as exc:
        for v in exc.violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    except (ConfigError, UsageError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except LedgerError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
