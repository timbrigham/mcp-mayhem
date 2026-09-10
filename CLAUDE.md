# mcp-mayhem

Local MCP servers. Each subfolder is one server; Python unified stack.

    gitRobot        mediated git — the only path by which commits and pushes happen
                    ⛔ TO THE **CONSUMER'S** REPOSITORY. gitRobot is fixed at startup to one
                    repo and it is NOT this one: `read(op='rev-parse', args=['--show-toplevel'])`
                    answers `C:/Workspace/ZeroParadox`, on branch `illustrated`. **mcp-mayhem's
                    own commits go through plain `git`.** Measured 2026-09-10, after a `stage` +
                    `commit` from here would have landed in the consumer's tree over five staged
                    files this session never touched — a true sentence read against the wrong
                    object, in the file that exists to name that defect.
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

## Time is UTC, everywhere, and the entry says so

⭐ Tim, 2026-09-09: *"we need to make it blatantly obvious what time zone we are using for our
entries."*

**Every timestamp this fleet writes is UTC with an explicit offset.** Measured that day: all
2,625 ledger records end `+00:00`, as does the refusal sidecar; `_now()` is
`datetime.now(timezone.utc)`. That half was already right and needed no change.

⛔ **THE COMPARISONS WERE NOT, AND THAT IS WHERE IT BIT.** `loop_breaks_expired` used
`date.today()` — the LOCAL date — against UTC-dated carves. At UTC-5/-6 those differ for five
to six hours of every day, so a carve could read expired early or late. A true value read
against the wrong object, in the module written to remove that class. **Never compare a stored
UTC value against `date.today()`, `datetime.now()` without a tz, or anything else that resolves
locally.**

⚠ **A BARE `YYYY-MM-DD` IS AMBIGUOUS BY UP TO A DAY.** Where a date must stay bare — the
loop-break register — the file states the convention in a `_timezone` field rather than leaving
a reader to assume. Where a full timestamp is written, carry the offset.

⛔ **AND IN PROSE, WRITE THE INSTANT IN UTC AND DROP THE ZONE NAME.** The consumer's rule,
earned 2026-09-09: they printed a correct `-05:00` next to the zone id `Central Standard Time`,
whose BASE offset is `-06:00` and which says "Standard" year-round. The number was right and the
label beside it would make the next reader's arithmetic wrong by an hour in December. **A true
value displayed next to a misleading label is one reader away from `DC-44`** — the same shape as
a record id sitting next to a step name, which is what the whole 2026-09-09 arc was pulling on.

## An exit code names WHAT HAPPENED, never merely whether it happened

⭐⭐ Tim, 2026-09-10: *"as a design schematic, we should never have, for example zero and
non-zero as the appropriate exit codes. they need to be specific as to exactly what they mean.
that's true, both on your side and on zeroparadox."*

**It binds BOTH repositories.** A caller that branches on `rc != 0` has thrown away the answer
and kept only the alarm — and the remedies behind those codes are not the same action. `1` says
fix the content. `2` says the ledger never answered, so try again. `3` says it ran and could not
decide. `4` says a rule was applied and retrying is how you get past a rule you should have
obeyed. **Collapsing them tells a caller to do SOMETHING while refusing to say what.**

⛔ **THE VOCABULARY IS `mcpcommon/vocabulary.py:EXIT_CODES` AND IT IS SERVED BOTH WAYS** — the
`vocabulary()` TOOL and `docs://*/vocabulary`, one source. Do not restate the values anywhere;
a restatement is the copy that will be wrong.

⚠ **`4` WAS ADDED 2026-09-10 AND THE REASON IS THE RULE ABOVE.** `2` used to mean both "could not
ask" and "asked and REFUSED", which differ on the one axis `error_type` says must never be
collapsed — `unavailable` is RETRYABLE, `validation` is TERMINAL. While they shared a code the
only remedy the vocabulary could offer was *"read the line"*: dispatch on prose, which this fleet
forbids everywhere else. **A DIFFERENT VALUE, NOT A DIFFERENT MESSAGE.**

⭐ THE CONSUMER GOT THERE FIRST AND THAT IS EVIDENCE, NOT COINCIDENCE. `check_briefs.
classify_record_failure` had already split the code, on the strength of `record.reachable()` — a
SECOND network call recovering a distinction `emit` had already made and destroyed at its return.
**A workaround in the consumer dates the gap here.** It chose `3`, which collides with `3`'s
published meaning AND with `ci_report.SKIPPED_RC = 3`, where a `3` renders as `**skipped**`, a
non-failure. That collision is why `4` is a new value rather than a widening of `3`.

⛔ **KNOWN LIVE INSTANCE ON THIS SIDE, NOT YET FIXED: `gitRobot/core/gates.py`.**
`GateResult.passed` is `self.ran and self.exit_code == 0`, so every non-zero — a finding, an
outage, an undetermined, a refusal, and the `124` this file sets itself on timeout — renders
identically as `passed: False`. ⚠ It fails CLOSED, so it is a REMEDY defect and not a safety
hole: the caller is correctly blocked and cannot learn whether to retry, fix content, or read a
rule. The `exit_code` IS kept on the audit row; `passed` is the field everything branches on.

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
- **sets `isError` TRUE on a refusal.** A failed call must never be protocol-identical to a
  successful one. ⛔ **THE WORD `TRUE` IS LOAD-BEARING AND WAS MISSING UNTIL 2026-09-10.**
  Measured that day across all three servers: **`isError` is present on EVERY response,
  carrying `false` on success.** So a client testing for the KEY treats every success as a
  failure — and the earlier wording, "sets `isError` on a refusal", reads as presence.
  ⭐ Found only because a control call was made on the SUCCESS path: without it, "isError
  present on refusals" is indistinguishable from "isError present always".
  ⚠ AND `ok: false` IS NOT THE DISCRIMINATOR. `sjv.check_head` answers `ok: false` to mean
  "I ran and FOUND DRIFT" — the FINDING axis, which `core/cli.py` turns into exit 0-vs-1 —
  and it was being transported as a protocol error with its `structuredContent` stripped.
  A refusal is now `ok: false` **AND** `error_type` present; `ok: false` alone is a finding
  and keeps its structured body. ⚠ FastMCP has no seam for this — `call_tool` returns content or a dict,
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

⚠⚠ **`instructions` IS A BOOT-TIME CHANNEL WITH A SESSION-LENGTH TTL, NOT A BROADCAST.**
Measured 2026-09-09 by clearing the consumer's session as a deliberate test. A FRESH client
receives the current text unprompted — it arrives in the harness-supplied "MCP Server
Instructions" section of the system prompt, before any tool call. A LIVE session does not: the
previous session held the pre-update block across two successful reconnects and four successful
resource reads.

So the audience map is:

    fresh session      gets current instructions ✓   can fetch resources ✓
    running session    holds STALE instructions ✗    can fetch resources ✓
    spawned subagent   instructions unmeasured       CANNOT fetch resources ✗

⭐ THE CONSEQUENCE FOR ANYTHING URGENT: a long-lived session is exactly the caller that hits a
mid-session restart, so the readers who most need a newly-published warning are the least likely
to hold it. Publishing it does not reach them and NO additional channel fixes that — the only
remedy is that they start a new session. Write for the fresh client and say plainly that
existing sessions must restart to see it.

⛔⛔ AND "BOOT-TIME ONLY" IS ALREADY FALSIFIED — TREAT THE CHANNEL AS UNPREDICTABLE
MID-SESSION, NOT AS A SNAPSHOT. Three observations, same client, same fleet, unreconciled:

    2026-09-08  a LIVE session could not see the newly-added `admission` tool, then hit a
                reconnect, and afterwards saw BOTH the new tool AND the new `instructions`.
                A mid-session refresh, of roster and instructions together.
    2026-09-09  a live session held PRE-UPDATE `instructions` across two reconnects and four
                successful resource reads.
    2026-09-09  a live session held PRE-UPDATE tool DESCRIPTIONS after a confirmed restart
                (pid start 12:02:57 UTC, re-fetch 12:04) while a call on the same connection
                SUCCEEDED first try — which is also the first exception to the retry signature
                below.

⚠ SO THE VARIABLE IS NOT "DOES IT EVER REFRESH". It does, sometimes. Nobody has WHICH reconnect
refreshes, and a tidy hypothesis here would be a cause attached to a real observation with no
negative case — the defect this pair filed as `DC-48` the same night. The 09-08 datum survives
only because the session that saw it was staggered against a session that did not clear.

⭐ WHAT A READER CAN RELY ON, WHICH IS THE ONLY PART WORTH DOCUMENTING: **if you need current
text, START A SESSION.** Do not reason about whether a reconnect gave you one, and do not
publish anything urgent expecting live sessions to see it.

⭐⭐ **AND AS OF 2026-09-09 16:22 UTC THE STALENESS HAS A BOUNDARY: IT IS THE DESCRIPTOR LAYER,
NOT THE SERVER.** Measured on both sides at once, which is the only reason it counts — neither
half concludes anything alone:

    RESPONSE BODIES ARE CURRENT.   V9's refusal text changed in `ceac023` (live 16:15:41Z).
                                   The consumer's LIVE session read the NEW text at 16:21:39Z,
                                   six minutes later. They also hold the OLD text from ~15:5x
                                   on a different channel, so it is a real before/after.
    DESCRIPTORS ARE NOT.           `find`'s description gained its ORDERING paragraph in
                                   `3ca550d` (12:03:22Z). The SAME live session re-fetched it
                                   at 16:22Z and got the old terse one. FOUR HOURS NINETEEN
                                   MINUTES. That is not deploy lag.
    AND FROM THIS SIDE             `tools/list` on the running server returns the new
                                   description — 1431 chars, `OLDEST FIRST` and `since=` both
                                   present — and has since the 15:33:57Z restart at the latest.

⛔ THE OBVIOUS OBJECTION IS THE ONE THAT MAKES IT STRONGER, NOT WEAKER. The consumer could not
prove their connection had not silently re-established. It does not matter: **either branch lands
in the same place.** No reconnect → descriptors are cached for the session. A reconnect at
16:15:41Z → `find` is STILL stale at 16:22Z, six minutes AFTER it, so descriptors survive a
reconnect. Nothing short of a NEW SESSION refreshes a descriptor.

⚠ WHY THIS IS WORTH THE INK, given the advice above does not change: it tells a mid-session
reader WHICH of the two things in front of them to believe. **A refusal you just received is
current. The docstring you just read may be four hours old.** So a caller who reasons from a tool
description about behaviour that recently changed is reasoning from a cache — and the refusal
that contradicts it is the one telling the truth.

⚠ ONE CLIENT, ONE SESSION, ONE OBSERVATION OF EACH. It narrows `DC-48`; it does not close it, and
the mechanism is still unknown. What changed is that the question is now "why are descriptors
pinned" rather than "does anything ever refresh".

⭐ AND THE PROBE DESIGN IS THE REUSABLE PART: every earlier attempt read a DESCRIPTOR — a tool
description, an `instructions` block, a resource — all of which are handed over at connect and
plausibly cached. A REFUSAL STRING is computed per call, on the server, from the code on disk, so
it cannot be cached by any mechanism either of us can name. **When you next need to know whether a
live session sees your change, change a response body, not a docstring.**

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

⭐⭐ **DURABILITY AND REACHABILITY ARE DIFFERENT PROPERTIES, AND THE TWO CHANNELS FAIL IN
OPPOSITE DIRECTIONS.** The consumer's line, 2026-09-09, and it corrects a claim made here the
same evening:

    a DOCSTRING   reaches everyone      and ROTS (cached per session; measured 4h19m stale)
    a RESOURCE    CANNOT rot (the body  and reaches almost nobody (no subagent route at all)
                  is read per call)

⛔ So "publish it as a resource" is NOT the fix for descriptor drift on its own. It was named
here as the cheapest fix without pricing who could read it, which is the same mistake one layer
up: a true property of the channel, asserted about the wrong audience.

⛔⛔ **AND THE SUBAGENT MODEL IS RICHER THAN "TOOLS YES, RESOURCES NO" — FOUR GATES, MEASURED
2026-09-10 BY A THIRD SESSION AND CORROBORATED IN CONFIG FROM THIS SIDE.** Anything designed for
a spawned agent must clear ALL of them, and clearing three reads exactly like clearing four:

    1  ToolSearch MUST BE IN THE AGENT'S ALLOWLIST. MCP tools are DEFERRED — a child's schema
       at spawn contains no `mcp__` name at all; all 147 across seven servers arrive as
       name-only strings behind ToolSearch. ⚠ An allowlist of `mcp__*, ToolSearch, Read, Glob`
       delivered only Read and Glob, 3 for 3. **Granting `mcp__*` without ToolSearch actually
       landing grants permission over an empty set** — there is no route to populate it.
    2  THE BRIEF MUST NAME THE EXACT TOOL. The deferred entries carry NO DESCRIPTIONS, so a
       child cannot browse or discover by concept. It can only select a name it already knows.
       ⭐ This is why "cite the URI as provenance and state the rule inline" generalises: a
       spawned agent cannot follow a pointer of any kind, URI or tool, that it must first
       discover.
    3  ⛔ SCHEMA-LOAD AND CALL-PERMISSION ARE INDEPENDENT GATES. "The schema loaded" tells you
       NOTHING about "the call will be allowed". Measured in one agent, one permission mode:
       `mcp__gitRobot__admission` EXECUTED while `mcp__verdictLedger__status` was REFUSED.
    4  THE CONTENT MUST NOT LIVE ONLY BEHIND A `docs://` URI. `ListMcpResourcesTool` and
       `ReadMcpResourceTool` do not reach a child. ⛔ THE MECHANISM IS NOT ESTABLISHED AND
       THIS ENTRY DELIBERATELY DOES NOT PICK A SIDE — see the disagreement below.

⛔⛔ **TWO SESSIONS PROBED GATE 4 AND GOT DIFFERENT MESSAGES. THAT DISAGREEMENT IS THE FINDING,
AND AN EARLIER VERSION OF THIS ENTRY QUIETLY PICKED ONE.** Corrected 2026-09-10 after the second
session read the first's evidence back to me and neither of us could reconcile them:

    probed by CALLING the tool     "No such tool available: ReadMcpResourceTool.
    (consumer session)              ReadMcpResourceTool is DISABLED for this session,
                                    in subagents as well as here."
                                   -> reads as a DELIBERATE DISABLE.

    probed by ToolSearch           ToolSearch("select:ListMcpResourcesTool,
    (provenance-ring session)       ReadMcpResourceTool") -> "No matching deferred
                                    tools found."
                                   -> reads as NOT REGISTERED.

⚠ THE SECOND PROBE CANNOT CARRY THE STRONGER WORD, AND ITS OWN AUTHOR SAID SO FIRST. **"No
matching deferred tools found" is a NEGATIVE SEARCH RESULT, not a statement of non-existence** —
it cannot separate "no such tool anywhere" from "a real tool this query failed to match." So
"absent from the deferred registry" was stronger than that probe earns, and it was the phrasing
this file had adopted.

⭐ THE FIRST PROBE EARNS MORE, VIA A CONTROL: a FABRICATED tool name returns the same "No such
tool available" WITHOUT the `disabled` clause — so the harness distinguishes a name it knows and
has disabled from a name that does not exist. ⚠ That control was run only after it was suggested
in conversation, so it postdates the original claim rather than founding it.

⭐⭐ **RESOLVED 2026-09-10, IN THE CONSUMER SESSION'S FAVOUR: THE TOOLS ARE PRESENT AND
SUPPRESSED, NOT UNREGISTERED.** The provenance-ring session found the discriminator by calling
each name DIRECTLY, with no ToolSearch first:

    ListMcpResourcesTool  -> "No such tool available: ListMcpResourcesTool.
                              ListMcpResourcesTool is disabled for this session, ..."
    ZzQxNotARealToolName  -> "No such tool available: ZzQxNotARealToolName"    <- STOPS HERE

⭐ **ALL THREE SHARE THE PREFIX. ONLY THE REAL ONES CARRY A SECOND SENTENCE.** So the prefix is
the generic wrapper and the trailing clause is the entire signal — and that is exactly how two
honest probes disagreed: **both read the same first sentence, and only one read to the end of the
line.** ToolSearch reports on the DEFERRED REGISTRY, where a suppressed tool is absent for a
different reason than a nonexistent one, so that route never shows the cause at all.

⚠ NEITHER ACCOUNT WAS FABRICATED. "No matching deferred tools found" was true and uninformative
about mechanism; "disabled" was true and was the mechanism. **The strong word belonged to whoever
had made the call that carries the second sentence.**

⛔ AND THE SCOPE CLAUSE IS DISPROVEN INSIDE A SINGLE SESSION: the same session called
`ReadMcpResourceTool(server="sjv", uri="docs://sjv/vocabulary")` successfully from the PARENT while
its own child, minutes later, was told the tool is disabled *"in subagents as well as here."*
⭐ The mechanism is that the string is a FIXED TEMPLATE written from the parent's vantage — "here"
means the main session — so it cannot be tailored to its reader and will be wrong wherever the
template's vantage does not match the reader's position. **A message describing its own blast
radius is not evidence about that radius**, now with two instances and a cause.

⚠ The design rule is unchanged and was never in doubt: a spawned agent does not reach the resource
surface. Only the mechanism was contested, and it is a suppression.

⚠⚠ AND THE PROVENANCE LESSON IS THE EXPENSIVE ONE. Writing this entry, I credited the fabricated-
name control and a separate observation to the WRONG PEER SESSION — real findings, wrong source,
and I did it while three sessions were live on one machine. **A true finding attached to the wrong
origin is `DC-44` in the provenance rather than in the units**, and it is worse here: the sessions
disagree, so which one said it is exactly what decides how much the claim is worth. ⭐ It was
caught only because the misattributed session recognised words it had never written. **Name the
session beside a relayed measurement, every time.**

⭐ WHY GATE 3 BIT, AND IT IS CONFIG RATHER THAN CHANCE — verified here 2026-09-10 by reading the
consumer's `.claude/settings.json` rather than trusting the symptom:

    defaultMode  dontAsk
    allow        mcp__sjv, mcp__gitRobot
    verdictLedger  ABSENT from allow, ABSENT from deny

⛔⛔ **SO THE LEDGER — THE STATE ENGINE EVERY CALLER IS TOLD TO CONSULT FIRST — IS THE ONE SERVER
A SPAWNED AGENT IN THAT PROJECT CANNOT REACH.** Under `dontAsk` a child cannot prompt, so an
absent allow entry is a silent refusal. The parent session reaches it fine, which is exactly why
nobody noticed: **the session that can check is the session that is not affected.**

⚠ THE FIX IS ONE LINE IN A FILE THAT IS NOT OURS AND MUST NOT BE EDITED FROM HERE. A permission
allowlist is never changed on a peer's report — that is the shape of permission laundering even
when the change is plainly correct.

⭐ THE DESIGN RULE THAT FOLLOWS, AND IT BINDS ANYTHING THIS FLEET BUILDS FOR SUBAGENTS:
**content a spawned agent must have belongs in a TOOL RESPONSE or in the server `instructions`
block — never only in a resource.** The vocabularies are the live instance: `docs://*/vocabulary`
is the canonical, generated-from-constants home, its own header says a document restating it is
the copy that will be wrong, and **it is unreachable to every gate brief, because every gate
brief is executed by a spawned agent.** A subagent asked "what does exit 2 mean" has no route to
the rendered definition and only restatements remain — which is the exact failure the resource
was built to prevent.

⚠ THE SHAPE THAT RESOLVES IT WITHOUT A SECOND COPY: serve the SAME generated render through both
transports — a `vocabulary()` tool and the `docs://` resource, both calling the one function over
`mcpcommon`'s constants. Two transports, one source, so they cannot disagree. **NOT BUILT — it is
a surface expansion rather than a defect fix, and it is Tim's call.**

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
