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
