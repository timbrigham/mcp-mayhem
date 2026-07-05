"""One-time migration: lift a legacy single-collection declarations registry into
the v2 multi-collection store envelope (interop issue #12, Option B).

    python -m scripts.migrate_to_collections --data data/registry.json

Before: the file is the bare declarations document
    { schema_version, anchor, counts, entries, vocab }
After: the same content nested under a store envelope
    { store_version, collections: { declarations: {…that…}, claims: {…empty…} } }

The migration preserves the declarations content (and its adopted vocab) verbatim
and adds an empty ``claims`` collection. It re-seals the result, recording a fresh
whole-store baseline hash in the SAME audit log (prior records are kept as
history). Idempotent: a file that is already a v2 envelope is left untouched.
"""

from __future__ import annotations

import argparse
import sys

from consumers.store import backfill_missing_collections, build_store, wrap_legacy
from core import store as store_io


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="migrate_to_collections")
    p.add_argument("--data", required=True, help="path to the flat JSON registry")
    p.add_argument("--actor", default="migration", help="actor recorded in the audit log")
    args = p.parse_args(argv)

    doc = store_io.read_json(args.data)
    is_envelope = isinstance(doc, dict) and doc.get("store_version") and "collections" in doc

    if is_envelope:
        # Already a v2 envelope — backfill any collection introduced since it was
        # migrated (e.g. `deps`, Issue 13). Existing collections are untouched.
        added = backfill_missing_collections(doc)
        if not added:
            colls = ", ".join(sorted(doc.get("collections", {})))
            print(f"already a complete v2 store envelope (collections: {colls}); nothing to do")
            return 0
        store_io.atomic_write_json(args.data, doc)
        note = f"backfilled empty collection(s): {', '.join(added)}"
    else:
        if not (isinstance(doc, dict) and "entries" in doc and "anchor" in doc):
            print("input does not look like a bare declarations registry "
                  "(expected top-level 'entries' + 'anchor')", file=sys.stderr)
            return 2
        n_decls = len(doc.get("entries", []))
        store_io.atomic_write_json(args.data, wrap_legacy(doc))
        note = (f"{n_decls} declarations lifted into collections.declarations; "
                f"empty claims + deps collections added")

    s = build_store(args.data, actor=args.actor)
    violations = s.validate()
    if violations:
        print(f"MIGRATION VALIDATION FAILED — {len(violations)} violation(s):", file=sys.stderr)
        for v in violations[:20]:
            print(f"  - {v}", file=sys.stderr)
        return 1
    rec = s.seal()
    print(f"MIGRATED — {note}.\n  new whole-store baseline hash {rec['resulting_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
