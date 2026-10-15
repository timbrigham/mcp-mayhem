"""Command line.

  python -m guard_coverage measure --audit A [--calls C ...] (--instances MAP | --transcripts D ...)
                                   --register R --manifest M [--rule 1] [--json]
  python -m guard_coverage instances --calls C ... [--audit A] --transcripts D ... --out MAP
  python -m guard_coverage backfill --http H ... --audit A --transcripts D ... [--until TS]
                                    --out-calls C --out-audit A2
  python -m guard_coverage synthetic --seed S --replicates 1000 [--json]

The unit is an agent instance. `instances` writes the map from client call id to instance,
built from Claude Code transcript directories (private; arguments, never manifest content).
`backfill` is the one-off recovery of call rows from gitRobot's rotating HTTP call log, for calls
made before gitRobot kept tool_calls.jsonl, plus an audit log whose refusals are linked to them.

Exit codes (each names one event):
  0   measured. Withheld values are part of a measurement and carry their reasons.
  2   could not measure: an input is missing or invalid, or the rule version is unknown.
  64  usage error: the command line itself is malformed (sysexits EX_USAGE). Kept apart
      from 2 because the remedy differs: fix the invocation, not the inputs.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import core, render, synthetic
from . import instances as INST
from .inputs import (InputError, load_audit, load_calls, load_instance_map, load_json,
                     load_windows, parse_ts)
from .rule import UnknownRule

EXIT_MEASURED = 0
EXIT_CANNOT_MEASURE = 2
EXIT_USAGE = 64


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("usage error: %s\n" % message)
        sys.exit(EXIT_USAGE)


def _parser():
    p = _Parser(prog="python -m guard_coverage")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    m = sub.add_parser("measure", help="measure items 1-4 from real inputs")
    m.add_argument("--audit", required=True)
    m.add_argument("--calls", action="append", default=[],
                   help="call log (tool_calls.jsonl shape); repeatable")
    src = m.add_mutually_exclusive_group(required=True)
    src.add_argument("--instances", help="instance map JSON {\"map\": {call id: instance}}")
    src.add_argument("--transcripts", action="append",
                     help="Claude Code transcript directory; repeatable")
    m.add_argument("--register", required=True)
    m.add_argument("--manifest", required=True)
    m.add_argument("--rule", default="1")
    m.add_argument("--json", action="store_true")
    m.add_argument("--windows", help="JSON file {\"boundaries\": [ts, ...]}; default: "
                                     "derive windows from the versions fields")
    m.add_argument("--batch-size", type=int, default=core.DEFAULT_BATCH)
    m.add_argument("--audit-guard", default="gitrobot",
                   help="manifest id of the guard whose audit log this is")
    m.add_argument("--as-of", help="report ages as of this UTC timestamp; default: the "
                                   "latest timestamp in the inputs")
    n = sub.add_parser("instances", help="write the call id -> agent instance map")
    n.add_argument("--calls", action="append", required=True)
    n.add_argument("--audit", help="also map the ids on these audit rows")
    n.add_argument("--transcripts", action="append", required=True)
    n.add_argument("--out", required=True)
    b = sub.add_parser("backfill", help="recover call rows from gitRobot's HTTP call log")
    b.add_argument("--http", action="append", required=True)
    b.add_argument("--audit", required=True)
    b.add_argument("--transcripts", action="append", required=True)
    b.add_argument("--until", help="drop calls at or after this UTC time (where "
                                   "tool_calls.jsonl takes over)")
    b.add_argument("--out-calls", required=True)
    b.add_argument("--out-audit", required=True)
    s = sub.add_parser("synthetic", help="SYNTHETIC replay: checks the estimators on "
                                         "simulated data")
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--replicates", type=int, default=1000)
    s.add_argument("--json", action="store_true")
    return p


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "synthetic":
        if args.replicates < 1:
            sys.stderr.write("usage error: --replicates must be at least 1\n")
            return EXIT_USAGE
        res = synthetic.run(args.seed, args.replicates)
        sys.stdout.write(json.dumps(res, indent=2, sort_keys=True) + "\n" if args.json
                         else synthetic.render(res))
        return EXIT_MEASURED
    try:
        if args.cmd == "instances":
            return _instances(args)
        if args.cmd == "backfill":
            return _backfill(args)
        audit = load_audit(args.audit)
        calls = load_calls(args.calls) if args.calls else []
        if args.instances:
            imap, ambiguous = load_instance_map(args.instances)
        else:
            ids = {r.get("client_call_id") for r in audit + calls} - {None}
            tmap, ambiguous, _ = INST.index_transcripts(args.transcripts, wanted=ids)
            imap = {k: v["instance"] for k, v in tmap.items()}
        report = core.measure(
            audit, load_json(args.register, "register"),
            load_json(args.manifest, "manifest"), args.rule,
            calls=calls, instance_map=imap, ambiguous_ids=ambiguous,
            audit_guard=args.audit_guard,
            boundaries=load_windows(args.windows) if args.windows else None,
            batch_size=args.batch_size,
            as_of=parse_ts(args.as_of, "--as-of") if args.as_of else None)
    except (InputError, UnknownRule) as e:
        sys.stderr.write("could not measure: %s\n" % e)
        return EXIT_CANNOT_MEASURE
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n" if args.json
                     else render.render(report))
    return EXIT_MEASURED


def _write(path, text):
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))


def _jsonl(rows):
    return "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)


def _instances(args):
    calls = load_calls(args.calls)
    rows = calls + (load_audit(args.audit) if args.audit else [])
    ids = {r.get("client_call_id") for r in rows} - {None}
    tmap, ambiguous, stats = INST.index_transcripts(args.transcripts, wanted=ids)
    doc = {"map": {k: v["instance"] for k, v in sorted(tmap.items())},
           "ambiguous": sorted(ambiguous), "stats": dict(stats, ids_wanted=len(ids))}
    _write(args.out, json.dumps(doc, indent=1, sort_keys=True) + "\n")
    sys.stderr.write("instances: %s\n" % json.dumps(doc["stats"], sort_keys=True))
    return EXIT_MEASURED


def _backfill(args):
    http, torn = [], 0
    for path in args.http:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    http.append(json.loads(line))
                except ValueError:
                    torn += 1           # e.g. a line cut at rotation: counted, not guessed
                    continue
    # The same request can sit in two copies of a rotated log: keep one.
    seen, uniq = set(), []
    for r in http:
        key = (r.get("ts"), r.get("session"), r.get("rpc_id"), r.get("rpc_method"))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    audit = load_audit(args.audit)
    ids = set()
    for r in uniq:
        if r.get("rpc_method") == "tools/call":
            try:
                meta = (json.loads(r.get("req") or "").get("params") or {}).get("_meta") or {}
            except (ValueError, AttributeError):
                continue
            if isinstance(meta.get(INST.CLIENT_CALL_ID_KEY), str):
                ids.add(meta[INST.CLIENT_CALL_ID_KEY])
    tmap, _, tstats = INST.index_transcripts(args.transcripts, wanted=ids)
    calls, cstats = INST.calls_from_http(uniq, audit, tmap)
    if args.until:
        until = parse_ts(args.until, "--until")
        before = len(calls)
        calls = [c for c in calls if parse_ts(c["ts"], "call") < until]
        cstats["dropped at or after --until"] = before - len(calls)
    linked, lstats = INST.link_refusals(audit, calls)
    _write(args.out_calls, _jsonl(calls))
    _write(args.out_audit, _jsonl(linked))
    sys.stderr.write("backfill: %s\n" % json.dumps(
        {"http_rows": len(http), "http_lines_not_json": torn, "unique": len(uniq),
         "transcripts": tstats,
         "calls": cstats, "link": lstats}, sort_keys=True))
    return EXIT_MEASURED
