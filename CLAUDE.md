# mcp-mayhem

Local MCP servers. Each subfolder is one server; Python unified stack.

    gitRobot        mediated git — the only path by which commits and pushes happen
    verdictLedger   append-only verdict stream; gates commit and push
    sjv             separate server, separate concerns
    mcpSupervisor   PowerShell watchdog keeping the HTTP servers alive

**This repo is PUBLIC.** No personal paths, credentials, or private-project content in
anything tracked. Run data lives in the gitignored `.mcp-local/` (its own repo), not here.

## Running the servers

They are **long-lived HTTP servers**, not per-session subprocesses. `gitRobot` :8010,
`verdictLedger` :8011.

    mcpSupervisor\mcp.ps1 status
    mcpSupervisor\mcp.ps1 restart gitRobot        # BY NAME — bare `restart` bounces all five

⚠⚠ **`/clear` DOES NOT RESTART THEM.** Clearing conversation context leaves the same processes
running the same code. **A fix that is committed but not restarted is a fix nobody has.** The
sequence is always **commit → restart → clear**; a server started from an uncommitted tree runs
code that exists in no revision.

## Testing

    cd gitRobot && python -m pytest -q          # ~2.5 min
    cd verdictLedger && python -m pytest -q     # ~30 s

Both must be green before a commit. `jq` is NOT installed on this machine — parse JSON with
Python or PowerShell's `ConvertFrom-Json`.

## The defect class this codebase exists to remove

**A TRUE value read against the WRONG object.** Not wrong numbers — right numbers describing
something other than what the sentence claims. Measured repeatedly: a field pricing the TIP read
as the RANGE; a timestamp pricing WHEN read as WHOSE; a figure pricing one LEG read as the whole
RUN; a count on `origin/main..branch` read as the unpushed count.

Every instance passes review, because the number is real and the sentence is grammatical.

**Two defences, and only the second scales:**

1. **Never report a number without naming what it prices.** "27 unpushed" is incomplete;
   "27 on `origin/illustrated..illustrated`, which is what the push publishes" is not.
2. **Where a value crosses between agents or layers, measure it independently on both sides and
   treat the disagreement as the signal.** Attention does not survive a long session; a
   disagreement check does. Do not relay a peer's figure as fact — re-derive it.

Corollaries that keep recurring:
- **Quote the source, and quote it *from* the source.** A remembered quote is a paraphrase
  wearing quotation marks.
- **Pre-register a prediction before the measurement, and split it finely enough that the result
  discriminates.** Two outcomes that print the same line for different reasons are two findings,
  not one.
- **A checker's answer is only as scoped as its caller made it.** The same pipeline printed
  opposite prior-art answers thirty minutes apart, because one invocation was handed refs and one
  was not.

## Conventions that are load-bearing

**Content-keying.** A verdict binds `(step, path, git_blob_id)`. It may never travel to bytes
nobody judged — in *either* direction. Coverage needs proof these exact bytes were examined;
condemnation is the same claim with the sign flipped and needs the same proof. That is why
`failing` exists: a FAIL (or UNDECIDED) indicts the subset it NAMES, not everything it examined.

**Absence is never success.** A step that never ran, a config that could not be read, an empty
admission set, an unreachable ledger — each must render as its own state and block. The recurring
bug is one of these quietly rendering as PASS.

**A refusal names the success condition, not just the failure.** `UsageError(what, satisfied_when)`
requires both. Test: could a reader construct a passing next attempt from `satisfied_when` alone,
with `what` deleted? The next attempt is on different bytes, so a message about the current bytes
is stale on arrival.

**Rules are enforced where they are enforceable, not where they are convenient.** A rule living in
a client is a rule with one copy and no enforcement. Make the defect unrepresentable rather than
detected.

**Guards and their claims land together.** A control whose surviving enforcement is *asserted*
rather than *run* is an unpriced exemption. Verify by making it fail.

## The MCP surface is a contract, not a docstring

Measured 2026-09-05 across all four live servers: **84 tools, zero annotations, zero
`outputSchema`, zero titles**, and twelve parameters declared
`{"type": "object", "additionalProperties": true}` — the shape that constrains nothing.
None of that was decided. FastMCP builds a working server from type hints and docstrings,
so everything optional stays unset and the contract quietly migrates into prose. `append`
carried a fifty-line writing guide in its docstring while publishing `record: any object`.

**A shape you FETCH cannot go stale the way a shape you INSTALL does.** That is the whole
argument: `verdictLedger/client/record.py` told callers to copy it into the consumer repo,
and the two copies diverged in `emit()` with nothing comparing them. A published
`inputSchema` is discovered through `tools/list` and cannot be copied out of date.

Every tool on every server here:

- **declares a real `inputSchema`** — a Pydantic model, never a bare `dict`. Structural
  facts only. Registered step names and thresholds stay in config, because baking policy
  into a static schema is the second-copy-of-the-policy that `config.py` forbids.
- **declares `outputSchema` and returns `structuredContent`.** A caller must never have to
  parse a text blob to learn whether the call worked.
  ⛔ **NOT TRUE YET — 0 of 81 tools declare one, measured 2026-09-06.** This line is the
  STANDARD, not a description of the code, and it is marked because an unmarked aspiration
  in this file is indistinguishable from a rule that holds. That confusion is the defect
  the whole section is about. It is tracked as declared debt by
  `test_mcp_conformance.py`, which fails if the count moves in either direction, so it
  cannot sit here unnoticed. Every tool returns `-> dict`; real return models are the work.
- **carries `ToolAnnotations`** — `readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`. On servers whose value is *capability removal*, this is the field that
  expresses it. Classify from the CODE, never the name: `ledger_subjects` reads like a
  read and is Tier 2, because `write-tree` materialises objects.
- **sets `isError` on a refusal.** A failed call must never be protocol-identical to a
  successful one. ⚠ FastMCP has no seam for this — `call_tool` returns content or a dict,
  never a `CallToolResult` — so the only route is raising, and the low-level server
  REWRITES the text to `Error executing tool <name>: <msg>`, which is no longer JSON.
  Flipping it unilaterally silently collapses every structured refusal the consumer
  receives into `None`. It is a coordinated change, client first.
- **conformance is a test, not a habit.** `verdictLedger/tests/test_mcp_conformance.py`
  fails when a tool ships without annotations or a title, and RATCHETS the unconstrained
  parameters: it fails when new debt appears *and* when listed debt is fixed without
  updating the list. A one-directional check lets debt sit forever.

## HTTP call logging — an instrument, never evidence

`mcpcommon/calllog.py`, imported by every server. **One implementation at the repo root —
never copied into each server**, which is the defect the client above exists to warn about.
5 MB × 5 files per server, both bodies, into the gitignored `.mcp-local/`.

It exists because the servers had no record of being called. gitRobot audits mutations and
skips reads by design; verdictLedger's `records.jsonl` is the PRODUCT, the verdicts that
PASSED. **A refused append left no trace anywhere**, so `errors.py`'s stated fear — a caller
retrying its way past a validation rule — was unfalsifiable.

⭐ It is also the second measurement pointed at the consumer. Asked 2026-09-05 whether their
client emits `failing`, the only available answer was their word for it; the log answers
that from this side without believing a reply.

⛔ **It is NOT evidence and may never be cited as proof a control ran.** It rotates and
deletes its own oldest file. A rotating buffer cannot carry a claim about the past.

⚠ Bodies carry consumer content — `reason` prose, findings, paths — and **this repo is
public**. `ZPLOG_DIR` is a ROOT and the server name is always appended; letting it be the
final path aimed four servers at one file, and multi-process rollover renames the open
file, which fails on Windows and silently stops rotation. Truncation is always recorded:
`req_bytes`/`resp_bytes` price the WIRE, never the stored excerpt.

## Comment style

Heavy, and deliberately so. A non-obvious guard carries the measurement that produced it — the
date, the numbers, what broke. Prefer "measured 2026-09-02, this condemned an entire push" over
"be careful here". Anything that cost a debugging session earns a comment that would have saved it.

## Working with the ZeroParadox session

A peer Claude session owns the consumer project and is hook-fenced out of these repos. It is a
**research assistant**; Tim is the author. Coordinate by message; never patch across the boundary.
Its `CLAUDE.md` is a durable carrier for its conventions — a rule agreed in conversation binds only
the participants, so check whether a convention was ever written where the other side can read it.

Local state and current work-in-progress: see `.claude/HANDOFF.md` (gitignored, machine-local).
