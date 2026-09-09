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
  ⭐ **TRUE AS OF 2026-09-06 — 81 of 81** (verdictLedger 20, gitRobot 22, sjv 39), each in a
  `results.py` beside its server, and `mcpcommon/iserror.py` returns `structuredContent` on
  success. ⚠ **Every shape was MEASURED** — reads off live responses, writes off `_receipt` /
  `apply` — because a wrong schema is worse than none: it publishes a contract the response
  violates, and the client that suffers is the one that actually validates.
  ⛔ **`ok` IS NOT UNIVERSAL AND MUST NOT BE ASSUMED.** verdictLedger and gitRobot stamp it in
  `_guard`, so it is required there; **sjv's reads do not have it at all** — `find(count_only)`
  returns `{count}`, `validate` returns `{valid, violations}`. Copying the sibling's base class
  would have published a contract three read tools break on every successful call. A schema
  copied from a sibling is a claim about THIS server measured on a DIFFERENT one.
  ⚠ A refusal carries NO `structuredContent` on any server: it does not match a success schema
  and must never be validated against one.
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

## The resource surface — a contract written BEFORE anything is built

⚠⚠ THIS SECTION EXISTS BECAUSE THE CONCEPT WAS FLOATED IN CONVERSATION AND DIED THERE.
Measured 2026-09-08: **0 mentions of "resource" in this file, 0 in any commit message, 0 in the
conformance suite, 0 `@mcp.resource` declarations — and every server advertising a `resources`
capability.** The 2026-09-05 sweep that found "84 tools, zero annotations, zero outputSchema"
never looked, because the contract it checked against had four clauses and none of them were
about resources. ⭐ Tim, 2026-09-08: *"we need to have a standing contract for exactly what we
need to do so that we properly build the resources definition."* A rule agreed in conversation
binds only the participants. This is the copy that binds.

⛔ **THE CAPABILITY IS ALREADY A LIE AND THAT IS THE FIRST THING TO FIX.** FastMCP advertises
`resources` by default. Serving none while advertising it is the same untrue-contract class as
`validate` advertising V1-V18 while running V21, and `merge` naming its parameter `branch` while
accepting any commit-ish. **An understated or absent contract costs more than a wrong one,
because nothing ever fails.** Either serve resources or stop advertising the capability; the one
thing forbidden is the present state.

**WHAT A RESOURCE IS HERE, and the line against tools.** A tool is an ACTION — it has
annotations because it may change something, and a caller decides whether to invoke it. A
resource is a DOCUMENT the server publishes and a caller reads. If it takes arguments, branches
on them, or has a side effect, it is a tool. **The test: could two callers read it a thousand
times and observe the same bytes? Then it is a resource.**

**WHAT EVERY RESOURCE MUST DO**

- **Be GENERATED from the constants the code imports, never hand-authored.** This is the whole
  point and everything else is detail. A hand-written dictionary is the FOURTH copy, not the
  replacement for three. `schema.VERDICTS` is the model: `ledger.py` imports it, `inputs.py`
  derives its `Literal` from it, and the wire enum comes from the same tuple — so the code would
  BREAK if it disagreed. A resource that merely describes what the code happens to do is the
  defect `control.md` is currently demonstrating at 20 assertions and three rounds.
- **Carry value AND meaning.** An enum publishes `["PASS","FAIL","UNDECIDED"]` and cannot say
  what UNDECIDED denotes or when it is the honest answer. That meaning currently lives in prose
  that drifts. Value, meaning, and — where one exists — the remedy.
- **Declare `uri`, `name`, `description`, `mimeType`.** Same argument as `inputSchema`: a shape
  you FETCH cannot go stale the way a shape you INSTALL does.
- **STRUCTURAL FACTS ONLY, the same line the input models hold.** The VALUE SET and what each
  value denotes may be published. Registered step names, thresholds, and anything editable
  without a restart stay in config and are served by `requirements()`/`policy()`. Publishing a
  threshold here would be the second-copy-of-the-policy `config.py` forbids.
- **Be IDENTICAL across every server that serves it.** The vocabularies live in `mcpcommon`,
  imported — never restated per server. ⚠ Measured 2026-09-08, this has ALREADY happened:
  `error_type` is defined in two `errors.py` files with only `usage` in common
  (verdictLedger: config/ledger/unavailable/usage/validation; gitRobot:
  gate/gitrobot/refusal/repo/usage), while `mcpcommon/iserror.py` READS that field on every
  refusal from every server and owns none of it.

⛔⛔ **A RESOURCE IS UNREACHABLE FROM A SPAWNED SUBAGENT, AND THAT CHANGES WHO IT IS FOR.**
Measured by the consumer 2026-09-09: a subagent spawned via the Agent tool receives MCP TOOLS
but not the MCP RESOURCE surface — `ToolSearch("select:ReadMcpResourceTool,ListMcpResourcesTool")`
returns *"No matching deferred tools found"*, and neither appears in the 150+ deferred-tool
manifest handed to it at spawn. That is a harness boundary; nothing here can change it.

⚠ THE CONSEQUENCE IS A DESIGN RULE, NOT A CAVEAT. **Every gate brief is executed by a spawned
agent.** So for that entire class of document a URI is not a pointer the reader can follow — it
is decoration. Replacing a hand-maintained assertion with a URI in a brief swaps a stale copy
for an unfollowable one, and both read as authoritative.

⭐ THE SHAPE THAT WORKS: **state the one rule the reader needs, and cite the URI as PROVENANCE
FOR A HUMAN**, not as an instruction to the agent. The agent gets the rule; the auditor gets the
trail back to the authority; nobody holds a copy that can drift silently. ⛔ And do NOT paste
the vocabulary into the spawned prompt instead — that makes the caller the copier, which is the
same defect with an extra hop. ⛔ Nor name the HTTP fallback (`127.0.0.1:8010/mcp`): it works,
and it is a hand-maintained copy of deployment state in a file that cannot see the port change.

⚠ SO RESOURCES SERVE AGENTS THAT HOLD A SESSION AND HUMANS READING THE SURFACE — not spawned
reviewers. Publishing to an audience that cannot fetch is the same error as documenting in a
file nobody opens, which is the defect `verdictLedger/client/record.py` already exists to warn
about.

**CONFORMANCE MUST EXTEND PAST TOOLS.** All 22 checks in `test_mcp_conformance.py` audit tools.
The advertised-but-empty capability sat one layer above everything they look at. The suite must
also fail when: a capability is advertised and unserved; two servers render the same vocabulary
differently; or a vocabulary gains a value that no resource publishes. ⚠ That last one is the
ratchet — `UNVALIDATED` was added to the row statuses on 2026-09-07 and appears in no list, so
nothing can enumerate the statuses a caller may receive.

⛔ **NOTHING IS BUILT YET, AND THE ORDER IS NOT NEGOTIABLE.** Consolidate the vocabularies into
`mcpcommon` first — that is a live defect today, independent of any resource. Then publish. A
resource built over four scattered definitions would publish the divergence.

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

**⛔ NEVER `/clear` BOTH SESSIONS IN THE SAME WINDOW** (Tim, 2026-09-06). A handoff is PROSE: a
fresh session inherits a *description* of how the tooling behaves, never the experience of
watching it behave. Clear both together and both sides are reading descriptions, with nothing
anchored to observation — the two halves corroborate each other's paperwork. **Staggering
guarantees one session can say "I watched that, and it did not go that way."**

Measured that day: the peer's final handover asserted a push had landed; from this side it was on
no remote branch, four commits unpushed. They had told Tim "two unpushed" correctly four times
and then filed the opposite into the one document meant to survive the boundary. ⚠ And the
direction is why it mattered — **a false FAILURE gets re-run and discovers itself; a false
SUCCESS is never revisited.**

So: after the peer clears, treat everything from the new session as RELAYED until re-measured. It
has the handoff and the tickets, not the thread — and a message that merely *sounds* like a green
light is not one. ⚠ The mirror half of this rule binds only if it is written where the other side
reads it; this file is not that place.

Local state and current work-in-progress: see `.claude/HANDOFF.md` (gitignored, machine-local).
