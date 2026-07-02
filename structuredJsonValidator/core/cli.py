"""CLI over the handler library (spec §12 milestone 5).

Enforcement lives in the library, not here (spec §4 principle 4) — the CLI is a
thin argument parser that calls :class:`core.engine.Registry`. It defaults to the
Lean consumer; a different consumer would ship its own tiny entry point or extend
``--consumer``.

Exit codes: 0 success; 1 validation/integrity/operation failure; 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from core.errors import IntegrityError, OperationError, ValidationError


def _load_registry(args) -> Any:
    if args.consumer != "lean":
        print(f"unknown consumer {args.consumer!r} (only 'lean' is wired up)", file=sys.stderr)
        raise SystemExit(2)
    from consumers.lean import build_registry

    return build_registry(args.data, actor=args.actor)


def _parse_scalar(text: str) -> Any:
    """Parse a CLI value as JSON when possible (numbers, booleans, null, quoted
    strings); otherwise treat it as a bare string."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _parse_kv_list(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            print(f"expected key=value, got {pair!r}", file=sys.stderr)
            raise SystemExit(2)
        key, _, value = pair.partition("=")
        out[key] = _parse_scalar(value)
    return out


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# -- command handlers ---------------------------------------------------------

def cmd_validate(args) -> int:
    reg = _load_registry(args)
    violations = reg.validate()
    if violations:
        print(f"INVALID — {len(violations)} violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("VALID")
    return 0


def cmd_seal(args) -> int:
    reg = _load_registry(args)
    try:
        record = reg.seal()
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"SEALED — baseline hash {record['resulting_sha256']}")
    return 0


def cmd_verify_integrity(args) -> int:
    reg = _load_registry(args)
    try:
        sha = reg.verify_integrity()
    except IntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"OK — file matches last audit hash {sha}")
    return 0


def cmd_get(args) -> int:
    reg = _load_registry(args)
    entry = reg.get(args.id)
    if entry is None:
        print(f"no entry with id {args.id!r}", file=sys.stderr)
        return 1
    _emit(entry)
    return 0


def cmd_find(args) -> int:
    reg = _load_registry(args)
    filters = _parse_kv_list(args.filters)
    results = reg.find(**filters)
    _emit(results)
    print(f"{len(results)} match(es)", file=sys.stderr)
    return 0


def cmd_history(args) -> int:
    reg = _load_registry(args)
    _emit(reg.history(args.id))
    return 0


def cmd_view(args) -> int:
    reg = _load_registry(args)
    try:
        print(reg.export_view(args.kind))
    except OperationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_export(args) -> int:
    reg = _load_registry(args)
    try:
        result = reg.export_full(args.to)
    except (ValidationError, IntegrityError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"EXPORTED {result['entries']} entr(ies) -> {result['dest']}\n"
        f"  artifact sha256 {result['export_sha256']}\n"
        f"  source   sha256 {result['source_sha256']}"
    )
    return 0


def cmd_apply(args) -> int:
    reg = _load_registry(args)
    if args.json is not None:
        try:
            params = json.loads(args.json)
        except ValueError as exc:
            print(f"--json is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(params, dict):
            print("--json must be a JSON object of params", file=sys.stderr)
            return 2
    else:
        params = _parse_kv_list(args.set)
    try:
        result = reg.apply(args.op, params)
    except (ValidationError, IntegrityError, OperationError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _emit(result)
    return 0


# -- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sjv", description="Schema-enforced flat-file SSOT registry.")
    p.add_argument("--data", required=True, help="path to the flat JSON source of truth")
    p.add_argument("--consumer", default="lean", help="consumer wiring (default: lean)")
    p.add_argument("--actor", default="cli", help="actor recorded in the audit log")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="full-file conformance; exit 1 on any violation").set_defaults(func=cmd_validate)
    sub.add_parser("seal", help="adopt the current file as the managed baseline").set_defaults(func=cmd_seal)
    sub.add_parser("verify-integrity", help="check file hash vs last audit hash").set_defaults(func=cmd_verify_integrity)

    g = sub.add_parser("get", help="fetch one entry by id")
    g.add_argument("id")
    g.set_defaults(func=cmd_get)

    f = sub.add_parser("find", help="filter entries by dotted.path=value (AND)")
    f.add_argument("filters", nargs="*", help="e.g. disposition=\"pending\" ontology.domain=\"number\"")
    f.set_defaults(func=cmd_find)

    h = sub.add_parser("history", help="read the audit log (optionally one entry)")
    h.add_argument("--id", default=None)
    h.set_defaults(func=cmd_history)

    v = sub.add_parser("view", help="render a projection view")
    v.add_argument("kind")
    v.set_defaults(func=cmd_view)

    e = sub.add_parser("export", help="publish the full validated registry to a path")
    e.add_argument("--to", required=True, help="destination path for the deterministic dump")
    e.set_defaults(func=cmd_export)

    a = sub.add_parser("apply", help="run a write operation (verb)")
    a.add_argument("op", help="operation name, e.g. rename, drop, annotate")
    a.add_argument("--json", default=None, help="params as a JSON object")
    a.add_argument("--set", nargs="*", default=[], help="params as key=value (values JSON-parsed)")
    a.set_defaults(func=cmd_apply)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
