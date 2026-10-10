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

    'staged' reads the index directly (`git ls-files -s`): checks run before the commit object
    exists, so there is no commit sha to resolve yet, but the staged blob ids already are.
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


def cmd_integrity_ack(args) -> int:
    """A person accepts recorded integrity breaches (2026-10-04). Deliberately CLI-only: there
    is no MCP tool for it, so an agent calling the server cannot clear its own alarm."""
    st = _ledger(args).store
    n = st.acknowledge_breaches(args.who, args.reason)
    _emit({"acknowledged": n, "integrity": st.verify_integrity()})
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
                              action=args.action, files=files, ref=args.ref,
                              repo=args.repo)
    print(render_mod.render_inventory(inv))
    if args.json:
        _emit(inv)
    return 0 if inv["complete"] else 1


def evidence_currency(inv: dict) -> dict:
    """Evidence currency from an inventory: per step, how many in-scope subjects carry a verdict
    bound to their current content (step, path, git blob id).

    Four counts, never merged into one rate:
      current         a verdict exists for this step at these exact bytes, whatever it recorded
                      (PASS, FAIL or UNDECIDED) - this measures whether the evidence is about
                      these bytes, not whether they passed
      stale           a verdict exists for this step and path, but at older bytes
      never_examined  no verdict for this step and path at any version
      in_scope        the step's subjects at this ref (current + stale + never_examined)
    A step that does not apply is NOT_APPLICABLE with `currency: null` and is left out of the
    totals - an empty scope is not "100% current". `not_applicable_because` says which cause:
      empty_scope               nothing in the step's scope exists at this ref
      when_matched_no_file      the step's applicability pattern (`when`) matched no file
      not_required_for_action   the configuration does not require the step for this action
      unclassified              the ledger marked it NOT_APPLICABLE without saying why; shown
                                rather than guessed, so a new cause is visible the day it appears
    The total is summed over (step, subject) pairs of applicable steps.
    """
    steps, tot = [], {"in_scope": 0, "current": 0, "stale": 0, "never_examined": 0}
    not_applicable = []
    for r in inv.get("rows") or []:
        judged = r.get("judged")
        in_scope = judged if isinstance(judged, int) else r.get("scope") or 0
        if r.get("status") == "NOT_APPLICABLE" or not in_scope:
            because = (r.get("not_applicable_because") or "unclassified"
                       if r.get("status") == "NOT_APPLICABLE" else "empty_scope")
            not_applicable.append(r["step"])
            steps.append({"step": r["step"], "status": "NOT_APPLICABLE", "in_scope": 0,
                          "current": 0, "stale": 0, "never_examined": 0, "currency": None,
                          "not_applicable_because": because})
            continue
        current, stale = r.get("subjects_covered") or 0, r.get("subjects_stale") or 0
        # derived so the three always partition the denominator (the row's own `unexamined`
        # is counted over scope only, and the denominator also includes switch files)
        never = in_scope - current - stale
        # Cannot go negative while the inventory counts `covered` and `stale` as disjoint subsets
        # of `judged`. If that ever stops holding, refuse rather than print a count that does
        # not partition its denominator.
        if never < 0:
            raise LedgerError(f"evidence currency for step {r['step']!r}: current ({current}) + "
                              f"stale ({stale}) exceeds in_scope ({in_scope}); the inventory "
                              f"row is inconsistent and no currency is reported for it")
        steps.append({"step": r["step"], "status": r.get("status"), "in_scope": in_scope,
                      "current": current, "stale": stale, "never_examined": never,
                      "currency": round(current / in_scope, 4)})
        for k, v in (("in_scope", in_scope), ("current", current), ("stale", stale),
                     ("never_examined", never)):
            tot[k] += v
    tot["currency"] = round(tot["current"] / tot["in_scope"], 4) if tot["in_scope"] else None
    return {"metric": "evidence_currency", "ref": inv.get("ref"), "action": inv.get("action"),
            "steps": steps, "total": tot, "not_applicable": not_applicable,
            "definition": ("currency = current / in_scope, per step and over all (step, subject) "
                           "pairs of applicable steps. stale and never_examined are reported "
                           "separately and are never folded into one number. A current verdict "
                           "counts whatever it recorded (PASS, FAIL or UNDECIDED). A step that "
                           "does not apply is NOT_APPLICABLE with currency null and is excluded "
                           "from the totals; an empty scope is never 100%.")}


def cmd_evidence_currency(args) -> int:
    # Both guards exist because the unguarded command answered confidently about nothing.
    # Measured 2026-10-09 by an adversarial review before publication: `--ref doesnotexist`
    # printed every step `n/a` and exit 0 (the git error was swallowed into an empty file
    # list), and an unset ZPLEDGER_DATA silently read the default stream and printed 0.0%
    # everywhere. Both are absence rendering as a measurement.
    if not args.data or not os.path.isfile(args.data):
        raise UsageError(
            f"no verdict stream at {args.data!r}",
            "pass --data <records.jsonl> (or set ZPLEDGER_DATA) naming an existing stream; an "
            "empty file is allowed and measures 0 current, but a missing one measures nothing")
    if args.ref != "staged" and _git(args.repo, "rev-parse", "--verify", "--quiet",
                                     f"{args.ref}^{{commit}}").returncode != 0:
        raise UsageError(
            f"{args.ref!r} does not resolve to a commit in {args.repo!r}",
            "pass --repo <a git repository> and --ref <a commit, branch or tag that exists there>")
    led = _ledger(args)
    cfg = led._require_config()
    files = _files_at(args.repo, args.ref)
    inv = inventory_mod.build(config=cfg, records=led.store.records(), action=args.action,
                              files=files, ref=args.ref, repo=args.repo)
    out = evidence_currency(inv)
    if args.json:
        _emit(out)
        return 0
    fmt = "{:<24} {:>8} {:>8} {:>8} {:>15} {:>9}"
    print(f"evidence currency at {args.ref} (action: {args.action})")
    print(fmt.format("step", "in_scope", "current", "stale", "never_examined", "currency"))
    for s in out["steps"]:
        cur = "n/a" if s["currency"] is None else f"{s['currency']:.1%}"
        print(fmt.format(s["step"][:24], s["in_scope"], s["current"], s["stale"],
                         s["never_examined"], cur))
    t = out["total"]
    print(fmt.format("TOTAL (applicable steps)", t["in_scope"], t["current"], t["stale"],
                     t["never_examined"], "n/a" if t["currency"] is None else f"{t['currency']:.1%}"))
    na = [f"{s['step']} ({s['not_applicable_because'].replace('_', ' ')})"
          for s in out["steps"] if s["currency"] is None]
    if na:
        print(f"not applicable (excluded from totals): {', '.join(na)}")
    return 0


def cmd_can_push(args) -> int:
    led = _ledger(args)
    result = canpush_mod.check(records=led.store.records(),
                               config=led._require_config(), repo=args.repo,
                               rev_range=args.range, action=args.action,
                               admission=args.admit,
                               commit_admission=args.admit_commit or args.admit,
                               limit=args.limit,
                              refusals=led.store.refusals())
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
    # `--data`, `--repo` (and the config variables) are top-level options: they go before the
    # subcommand, e.g. `python -m core.cli --repo R --data D evidence-currency --ref HEAD`.
    p.add_argument("--data", default=os.environ.get("ZPLEDGER_DATA"),
                   help="the append-only stream (env ZPLEDGER_DATA)")
    # The default is the current directory. It used to be a hard-coded path on one developer's
    # machine, which meant nothing anywhere else and should never have been in a public repo.
    p.add_argument("--repo", default=os.environ.get("ZPLEDGER_REPO", os.getcwd()),
                   help="the git repo whose content is judged (env ZPLEDGER_REPO; default: "
                        "the current directory)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="stream health, config state, genesis floor"
                   ).set_defaults(func=cmd_status)

    ec = sub.add_parser("evidence-currency",
                        help="per step: in-scope subjects with a verdict at their CURRENT bytes, "
                             "vs stale, vs never examined (never one merged rate)")
    ec.add_argument("--ref", default="HEAD", help="the git ref to measure (default HEAD)")
    ec.add_argument("--action", default="push",
                    help="which action's registry narrowing applies (default push)")
    ec.add_argument("--json", action="store_true", help="machine-readable output")
    ec.set_defaults(func=cmd_evidence_currency)

    ia = sub.add_parser("integrity-ack",
                        help="a PERSON accepts the recorded integrity breaches (sticky until then)")
    ia.add_argument("--who", required=True, help="the person accepting the bytes")
    ia.add_argument("--reason", required=True, help="why the bytes are trusted")
    ia.set_defaults(func=cmd_integrity_ack)

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
    cp.add_argument("--admit-commit", action="append", default=None,
                    help="a type that must be green at each INTERMEDIATE commit; "
                         "defaults to --admit. The tip carries --admit")
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
    """Refusal text contains non-ASCII characters (warning signs, em dashes), and a
    Windows console defaults to cp1252. Without this the tool raises
    UnicodeEncodeError and prints nothing, so the refusal that matters most would
    crash instead of explaining itself. Measured 2026-08-23 while testing the
    ledger gate.
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
