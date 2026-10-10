"""Command line.

    python -m inventory_fidelity measure --inventory FILE --artifact DIR [--json]
    python -m inventory_fidelity register --root DIR PATH [PATH ...]

Exit codes. Each names one event; no two events share a code.

    0   measured, whatever the values
    2   could not measure: the inventory or artifact is missing or unreadable, or the
        inventory was refused (both active and retired, a duplicate name, a bad hash, ...)
    3   measured, but the scan reported errors; the withheld names are not in the ratios
    64  the command line itself was malformed (argparse's own default is 2, which would
        collide with "could not measure", so it is moved here)

`register` uses the same codes: 0 printed every entry, 2 could not read, 3 printed the
entries it could and reported errors for the rest.

An uncaught exception exits 1 (Python's default). This module never chooses 1, so a 1 is
always a crash rather than a result.
"""

import argparse
import json
import sys

from .inventory import CannotMeasure, load_inventory
from .measure import CLASSES, measure
from .scan import register_items, scan_artifact

EXIT_MEASURED = 0
EXIT_CANNOT_MEASURE = 2
EXIT_MEASURED_WITH_SCAN_ERRORS = 3
EXIT_USAGE = 64


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        sys.exit(EXIT_USAGE)


def _fmt_ratio(r: dict) -> str:
    frac = f"{r['numerator']}/{r['denominator']}"
    if r["value"] is None:
        return f"{frac} = null (undefined: denominator is 0)"
    return f"{frac} = {round(r['value'], 4)}"


def render_text(report: dict, inventory_path: str, artifact_path: str) -> str:
    out = ["AI inventory fidelity",
           f"  inventory  {inventory_path}",
           f"  artifact   {artifact_path}",
           "",
           "Locations scanned"]
    width = max(len(loc["location"]) for loc in report["locations"])
    for loc in report["locations"]:
        state = "absent" if loc["status"] == "absent" else f"{loc['items']} item(s)"
        out.append(f"  {loc['location']:<{width}}  {state}")
        if loc["not_scanned"]:
            out.append(f"  {'':<{width}}  not scanned: {', '.join(loc['not_scanned'])}")
    out += ["", "Classes"]
    for c in CLASSES:
        names = ", ".join(report["names"][c]) or "-"
        note = "  (correct; not counted in the ratios)" if c == "retired-absent" else ""
        out.append(f"  {c:<14}  {report['counts'][c]}  {names}{note}")
    out += ["",
            f"  precision  m/(m+d+v)    {_fmt_ratio(report['precision'])}",
            f"  recall     m/(m+d+p+z)  {_fmt_ratio(report['recall'])}",
            ""]
    if not report["errors"]:
        out.append("Errors: none")
    else:
        out.append(f"Errors: {len(report['errors'])}")
        for e in report["errors"]:
            out.append(f"  {e['kind']}: {e['name'] if e['name'] is not None else '(no name)'}"
                       f" at {e['location']}: {e['detail']}")
        out.append(f"  withheld from classification: {', '.join(report['withheld']) or '-'}")
    return "\n".join(out) + "\n"


def _cannot(exc: CannotMeasure, as_json: bool) -> int:
    sys.stderr.write(f"could not measure: {exc.what}\n  succeeds when: {exc.satisfied_when}\n")
    if as_json:
        print(json.dumps({"measured": False, "error": exc.what, "satisfied_when": exc.satisfied_when}, indent=2))
    return EXIT_CANNOT_MEASURE


def cmd_measure(args) -> int:
    try:
        inventory = load_inventory(args.inventory)
        scan = scan_artifact(args.artifact)
    except CannotMeasure as exc:
        return _cannot(exc, args.json)
    report = measure(inventory, scan)
    if args.json:
        print(json.dumps({"measured": True, "inventory": args.inventory, "artifact": args.artifact, **report},
                         indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_text(report, args.inventory, args.artifact))
    return EXIT_MEASURED_WITH_SCAN_ERRORS if report["errors"] else EXIT_MEASURED


def cmd_register(args) -> int:
    try:
        present, errors = register_items(args.root, args.paths)
    except CannotMeasure as exc:
        return _cannot(exc, False)
    entries = [{"name": n, "sha256": h} for n, h in sorted(present.items())]
    print(json.dumps(entries, indent=2, ensure_ascii=False))
    for e in errors:
        sys.stderr.write(f"error: {e.kind}: {e.name if e.name is not None else '(no name)'}"
                         f" at {e.location}: {e.detail}\n")
    return EXIT_MEASURED_WITH_SCAN_ERRORS if errors else EXIT_MEASURED


def main(argv=None) -> int:
    parser = _Parser(prog="inventory_fidelity",
                     description="Reconcile an AI component inventory against a deployed artifact.")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    m = sub.add_parser("measure", help="measure inventory fidelity")
    m.add_argument("--inventory", required=True, help="inventory JSON file (read only)")
    m.add_argument("--artifact", required=True, help="deployed artifact directory")
    m.add_argument("--json", action="store_true", help="print the report as JSON")
    m.set_defaults(func=cmd_measure)

    r = sub.add_parser("register", help="print inventory entries for files, using the scan's hash routine")
    r.add_argument("--root", required=True, help="artifact directory the paths are relative to")
    r.add_argument("paths", nargs="+", help="component paths relative to --root, or models.json")
    r.set_defaults(func=cmd_register)

    args = parser.parse_args(argv)
    return args.func(args)
