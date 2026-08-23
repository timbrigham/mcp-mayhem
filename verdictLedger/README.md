# verdictLedger

Every gate step emits a **validated JSON record** saying what it decided, on what,
and how. Records are append-only. The ledger validates them, serves them back,
renders the single human line, computes the signal families, and audits git
history so a bypass of the gate is detectable after the fact.

**An invalid or missing record means UNDECIDED, which blocks.** That is the entire
safety property: *the store cannot be the reason something passed.*

```
zpledger status
zpledger genesis <sha>                     # the recording floor
zpledger inventory commit --ref staged     # exit 1 if anything is short
zpledger crossref
zpledger signals
```

---

## ⚠⚠ This server is a MANDATORY dependency of every gated commit and push

When it is down, nothing lands. **That is intentional, not a fault** — the remedy
is to start it, not to add a bypass. A local fallback write would be the two-route
design returning through the back door.

The alternative was considered and rejected: "the pipeline must keep working with
the server down" is an availability escape hatch wearing safety clothing. Unpacked
it says *the record could not be written, so we proceed anyway.*

**What that buys has to be paid for explicitly:** supervised, health-checked and
auto-repaired; started as a subprocess in CI; loopback with no interactive auth.

## One route, one implementation

| who | how |
|---|---|
| checkers, `batch.py`, `hooks.py` | `tools/verify/record.py` — a thin **client**, ~40 lines, stdlib only |
| agents and humans | the MCP tools |

`record.py` holds **no validation logic**. The rules exist in exactly one place, so
the mirror defect is not avoided by discipline — it is unrepresentable.

Measured: a stdlib-only client speaks streamable-HTTP MCP fine (`initialize`,
`notifications/initialized`, `tools/call`; session id from the `Mcp-Session-Id`
header; payload on the SSE `data:` line). No `mcp` dependency in the ZP repo, and
no second write route.

## ⚠⚠ Exactly one hash, and it is git's

```
id = step@basis#revision          e.g.  check_prose@b5912c5a223c…#0
```

The record key is a **composite of things that already exist**, not a digest over a
description of them. `basis.value` is a git object hash — a tree sha at commit
time, a commit sha at push time — so git has already content-addressed the thing
being judged. A second hash adds no identity the first one did not.

It follows from V11: `(step, basis, revision)` is unique in the stream, so that
triple **is** the primary key and everything else is payload determined by it.

**What the removed hash was costing.** It required pinning a canonical JSON
encoding (key order, separators, `ensure_ascii`) so a reimplementation could
reproduce the digest to re-verify a deposit — and because free prose was in the
digest, it required a rule forbidding nondeterministic `reason` text. Both were
solving problems the hash created. A stranger re-verifying a deposit now reads the
fields; there is nothing to recompute and no encoding contract to honour.

`cost`, `run.started`, `run.id` and `run.policy_sha` are fields, never key parts —
needed to interpret a verdict, never to identify one.

`basis` is the content the check ran against, and it exists at check time in both
phases:

| phase | basis | why it exists then |
|---|---|---|
| commit | the staged tree sha (`git write-tree`) | ⚠ the commit sha does **not** exist yet — checks run before the object does |
| push / tag | the commit sha, or the range | the range is real by then |

Verified: `write-tree` before any commit == `rev-parse HEAD^{tree}` after it,
deterministic, and content-addressed — revert to content that previously passed and
the verdict already exists. **A pass is about content, not about when.**

`revision` replaces `supersedes`: an ordinal scoped to one `(step, basis)`, so a
chain never crosses bases and an accepted FAIL can never be carried onto content it
was not about. `(step, basis, revision)` is unique, which makes branching
unrepresentable rather than detected.

## The rules — V1–V13

Each makes a defect this project has already paid for unrepresentable. V1 basis
stated · V2 no PASS over nothing · V3 real unanimity · V4 inputs exist · V5 no
anonymous pass · V6 no unactionable block · V7 no smuggled keys · V8 unregistered
step cannot record · V9 run id · V10 policy sha known · V11 no branching · V12 no
self-override · V13 depth cap.

⚠ **V14 (deterministic `reason`) was retired** along with the hash that required
it. Prose is payload now — a checker may report whatever is most useful to a human.

**Every one has a probe that turns the validator red**, plus the **neuter control**:
stub the rules to return nothing and every probe must go green. Any that stays red
was testing a proxy rather than the rule.


## `crossref` — auditing for a bypass

Walks `rev-list <genesis>..HEAD`, resolves each commit's tree, and asks whether that
content was approved. Three findings, in the shape of the question:

| finding | meaning |
|---|---|
| `NOT_RUN` | no step examined this content — **it bypassed the gate** |
| `INCOMPLETE` | examined, but the required set was short |
| `NOT_APPROVED` | landed over a `FAIL` or `UNDECIDED` verdict |

⚠⚠ **It compares against git, not against gitRobot's audit log, and that was a
correction.** The first version joined the ledger to `git_ops.jsonl` — but *both are
written by the sanctioned path*, so a commit made AROUND gitRobot leaves no audit
row and the join was blind to precisely what it claimed to check. It could only find
disagreement between two systems that agree by construction. **Git history is the one
record a bypass cannot avoid writing to.**

The same correction retires an over-claim: that design said it closed `GRB-2` (a
dropped `preflight` leaving no verdict and no audit row) "from the other side". Both
stores were silent *together*, so a join sees nothing. What caught it was a `started`
row inside gitRobot's own log — detectable from one stream, not two.

⚠ Commits from a human terminal are unaffected by gitRobot's deny rule **by design**,
so they surface as `NOT_RUN`. That is the audit working, not noise.

⚠ Capped at 500 commits by default and **truncation is reported** — a capped audit
that reads as complete is the defect this server exists to end.

## Config, not constants

If changing a **policy** means editing **logic**, it is in the wrong place.
`policy.v1.json` holds thresholds, actions and the genesis floor; `required.v2.json`
is the type registry. Both live in `tools/verify/` in the ZP repo — **the bar must
be a reviewable diff in the same history as the work it gates.**

**Required by default.** A registered type binds on every action unless an entry
says otherwise, and saying otherwise costs a stated `reason`. **A narrowing without
a reason is ignored and the type stays required** — a typo in an exemption fails
safe. Inclusion is free; exclusion takes effort.

⚠ A malformed config makes the server serve **nothing** — it never falls back to a
built-in default, because a built-in default is a second copy of the policy and the
weaker one is the copy nobody notices.

## Concurrency

The writer takes a lock with a **30s bounded wait**; crossing **5s** stamps an
edge-condition observation on the record and still writes. It never returns
"locked" — with UNDECIDED blocking, transient contention would become a blocked
commit for nothing.

⚠ The two numbers are coupled: 30s is the supervisor's poll interval, and a wait
that long is safe **only because every tool is async-offloaded** so the health
endpoint keeps answering. A test asserts every registered tool is a coroutine.

("Sole writer process means appends serialise" is false and was corrected: sole
writer *process* is not sole writer *thread*, and Windows offers no `O_APPEND`
atomicity to fall back on. One torn line makes the stream unparseable, which fails
every subsequent query — total, not partial, for a mandatory dependency.)

## Absent by design

No `delete`, `edit`, `update`, `force`, `skip_validation`, `set_verdict`, bulk
import, or raw `passthrough` — asserted by a test over the tool registry.

## Layout

```
verdictLedger/
  core/      schema · config · validate · store · ledger · inventory · crossref · signals · render · cli
  ledger_server/  server.py          # thin FastMCP transport, module path is load-bearing
  config/    policy.v1.json  required.v2.json   # shipped copies; ZPLEDGER_CONFIG points at ZP's
  client/    record.py                          # installed as tools/verify/record.py
  data/      records.jsonl                      # append-only, gitignored
```

⚠⚠ The MCP package is `ledger_server/` — never `mcp_server/` (sjv) or
`gitrobot_server/` (gitRobot). The supervisor matches on process name plus a
command-line substring **and a repair force-kills every machine-wide match**, so a
shared module path is actively collateral-killing.

| env var | default |
|---|---|
| `ZPLEDGER_DATA` | `data/records.jsonl` |
| `ZPLEDGER_CONFIG` | directory holding both config files (ZP's `tools/verify`) |
| `ZPLEDGER_GITOPS` | gitRobot's `git_ops.jsonl`, for `crossref` |
| `ZPLEDGER_HOST` / `ZPLEDGER_PORT` | `127.0.0.1` / **8011** |
| `ZPLEDGER_RUN` | the pipeline's run id, exported per invocation |

## Status: what is built

Built and running: config loader (fail-closed), schema and identity, V1–V13 with
probes, the append-only store with the bounded-wait lock, genesis, `sign`/`override`,
`validate`/`get`/`find`/`render`, `requirements`/`policy`, `inventory`, `coverage`,
`crossref` P1–P4, six signal families, the CLI, the MCP server, and the stdlib client.

**60 tests.** Not yet built: the remaining signal families (flake, disagreement,
escalation, time-to-clear, suppression growth, cost, first-failure latency), and the
gitRobot side of the join — its commit rows must capture the tree sha and the
inventory id, without which P1/P2 have nothing to join to.
