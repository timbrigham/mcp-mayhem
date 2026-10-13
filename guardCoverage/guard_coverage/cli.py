"""Command line.

  python -m guard_coverage measure --audit A --register R --manifest M [--rule 1] [--json]
  python -m guard_coverage synthetic --seed S --replicates 1000 [--json]

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
from .inputs import InputError, load_audit, load_json, load_windows, parse_ts
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
        report = core.measure(
            load_audit(args.audit), load_json(args.register, "register"),
            load_json(args.manifest, "manifest"), args.rule,
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
