# structuredJsonValidator

A **schema-enforced flat-file SSOT registry**: a plain JSON file behaves like a
database — strict schema, operation-mediated (parameterized) writes, an
append-only audit + hash-drift log, a query/projection reader, and an optional
MCP server. The tool is **project-agnostic**; the worked example is a *Lean
declaration registry* (consumer #1), used only to make the shape concrete.

## Why this exists
Off-the-shelf options each miss one piece:
- **lowdb** — flat JSON, but schemaless at runtime.
- **SQLite** — real constraints, but a binary file (not greppable/diffable).
- **Generic DB-MCP servers** — heavy, add a running service + write-trust surface.

The gap this fills: the **published artifact is a plain, diffable flat file**
AND the **schema + integrity are strictly enforced** AND writes are
**operation-mediated** (no free-form drift).

## Design principles (see the build spec for the full list)
1. The flat JSON file is the source of truth and the published artifact.
2. Structure is invariant across every entry; only leaf scalars may be `null`.
3. Writes go only through the handler, as verbs — never raw field edits.
4. Enforcement lives in the **library** (+ CLI); the MCP is a thin wrapper added
   last. If the MCP is down, the file and its rules still hold.
5. The reader is a projection engine (views cannot drift from the source).
6. Integrity via an append-only SHA-256 hash-log; drift = out-of-band edit.
7. Atomic writes (temp-then-rename). 8. Single-writer assumption for v1.
9. The validator reports **all** violations and exits non-zero on any.

## Layout
```
core/                     # the project-agnostic tool (the real deliverable)
  store.py                # canonical serialization, atomic write, hashing
  schema.py               # structural validation (JSON Schema 2020-12)
  audit.py                # append-only hash-log + verify_integrity (drift)
  engine.py               # Registry: operation framework, pre/post validation
  query.py                # get / find (dotted-path filters)
  cli.py                  # argparse CLI over the library
consumers/lean/           # consumer #1 — kept OUT of core (spec §13/§14)
  declaration.schema.json # the document schema (§6)
  rules.py                # §7 per-disposition table + id-uniqueness + counts
  operations.py           # §9 verbs (rename/move/drop/merge/split/…)
  views.py                # projections (status table, domain table)
mcp_server/               # thin MCP transport (added last; no enforcement)
data/sample.json          # two conforming entries (§8)
tests/                    # negative tests proving the gate is real
```

## Enforcement, split honestly
- **Structural** (types, enums, required-ness, `additionalProperties:false`) →
  the JSON Schema in `consumers/lean/declaration.schema.json`.
- **Business rules** (per-disposition conditionals, id-uniqueness, counts) →
  `consumers/lean/rules.py`. These exceed what JSON Schema expresses cleanly.

## CLI
```bash
# structural + business conformance; exit 1 on any violation
python -m core.cli --data data/sample.json validate

# adopt an existing/hand-written file as the managed baseline (records 1st hash)
python -m core.cli --data data/sample.json seal

# operation-mediated write (a verb, never a raw edit)
python -m core.cli --data data/sample.json apply rename \
  --json '{"id":"...","new_qualified":"A.B.c","new_file":"A/B.lean","namespace":"A.B","reason":"restructure"}'

# integrity gate — run in pre-commit / CI to catch out-of-band edits fast
python -m core.cli --data data/sample.json verify-integrity

# reader + projections + audit history
python -m core.cli --data data/sample.json find disposition='"pending"'
python -m core.cli --data data/sample.json view status
python -m core.cli --data data/sample.json history --id '<entry-id>'

# publish the COMPLETE validated registry as a deterministic artifact
python -m core.cli --data data/sample.json export --to ../other-repo/registry/decls.json
```

`seal` writes a sidecar audit log at `data/sample.json.audit.jsonl` (the log is
the integrity anchor and the full mutation history).

**Data privacy:** by default, everything the server/CLI writes under `data/` is
treated as private live data and git-ignored — only the `sample.json` demo
fixture is tracked (see `.gitignore`). To publish a registry as a committed
source-of-truth, use `export_full` into a consuming repo, point `--data` at a
tracked path outside `data/`, or `git add -f` a specific file. See
[`mcp_server/README.md`](mcp_server/README.md#data-privacy--real-data-is-git-ignored-by-default).

## Publication (`export` / `export_full`)
`sjv` owns the (possibly hidden) working source; a consuming repo gets a **full,
validated, deterministic dump** it can commit with normal git. `export` differs
from `view`: `view` renders a lossy projection, `export` writes the *complete*
`schema_version`/`anchor`/`counts`/`entries` document.

- **Validated** — refuses to publish an invalid registry (and refuses a drifted
  source when sealed); an out-of-conformance source never reaches the public path.
- **Deterministic** — entries sorted by `id`, object keys sorted recursively,
  stable 2-space formatting, so git diffs of the artifact are meaningful. Two
  exports of the same source are byte-identical.
- **Traceable** — the export is recorded in the audit log (`op: export_full`)
  with the artifact's `export_sha256`. The record's `resulting_sha256` stays
  equal to the unchanged source hash, so the source integrity chain is preserved
  (exporting never counts as a source mutation).

The caller only *triggers* the dump to a public path — it never writes registry
content directly. **Open, consumer-side:** *what* to publish (in-flight working
ledger vs a stabilized export), *where* it lives in the consuming repo, and
whether it goes through that repo's review gates.

## MCP server (optional, thin)
```bash
SJV_DATA=data/sample.json SJV_PORT=8000 python -m mcp_server.server
# streamable-HTTP MCP at http://127.0.0.1:8000/mcp
```
Read tools: `get, find, history, view, validate, verify_integrity`.
Write tools: `seal` + the §9 verbs + `export_full` (publish a full validated dump)
+ a generic `apply`. The MCP enforces nothing
itself — it calls the library. Grant write access only to vetted clients.

## Tests
```bash
python -m pytest -q      # 25 tests: structural + business negative tests, engine round-trip, drift detection, publication export
```

## Adding a second consumer
Add a sibling package under `consumers/` with its own `*.schema.json`, `rules.py`
(business validator), `operations.py` (verbs), and `views.py`, then a
`build_registry()` factory. `core/` needs no changes — it is data-shape-agnostic.

## Runtime decisions (from the spec's open questions)
- **Runtime:** Python end-to-end (enforcement core + HTTP MCP in one platform).
- **Schema mechanism:** JSON Schema 2020-12 (`jsonschema`) for structure; Python
  for business rules. (The sqlite-DDL variant was rejected: expressing §7's
  conditional per-disposition rules as SQL CHECKs is awkward, and the spec
  already routes those to handler code.)
- **Audit log:** append-only JSONL sidecar next to the data file.
- **Name:** `structuredJsonValidator`.
