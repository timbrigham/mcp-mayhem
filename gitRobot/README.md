# gitRobot

Mediated git for **one** repository. Destructive operations are refused, mutating
operations are gated and audited, reads pass straight through, and every mutating
call leaves a record — including the refused ones and the clean ones.

```
gitrobot --repo C:\Workspace\ZeroParadox status
gitrobot read log -5 --oneline
gitrobot stage src/a.lean docs/b.md
gitrobot commit .msg.txt --reason "fix the valuation bridge"
gitrobot preflight
gitrobot push illustrated --reason "ship the fix"
```

---

## ⚠ This is layer 2 of 3, and it is not sound on its own

gitRobot raises friction against **drift**. It cannot bind an actor who controls
the machine, and it must not be read as if it could.

| layer | what it is | soundness |
|---|---|---|
| 1 | remote branch protection + required status checks | **the only sound layer** |
| 2 | **gitRobot + a PreToolUse deny on direct `git`** | cooperative; defeats drift, not intent |
| 3 | the installed git hooks | a backstop gitRobot keeps reachable |

Installing this closes nothing on its own. Layer 2 works because the agent has no
hands, not because the door has a better lock — and an agent that decides to route
around it (a wrapper script, a base64-encoded command, indirection through a
variable) can. That is an accepted limit, not an oversight: the threat model is a
well-intentioned session under pressure treating a block as an obstacle, and
against that, capability removal is the effective control.

**No key, no token, no shared secret.** A local secret is readable by the actor it
defends against. The value here is capability removal and auditability, not
authentication.

## Why *all* of git, not just push

The push gate was the entry point. Pushing is not where the damage happened.

An agent told to "leave the repository exactly as it found it" ran `git reset
--hard` three times on a shared tree, destroyed an uncommitted `CLAUDE.md` edit,
and then correctly reported *"tracked tree clean, HEAD unchanged"* — which was
true, and was the destruction.

**No hook fires on that.** Measured 2026-08-22 on git 2.45.1:

- `git clean -fd` fires **zero** hooks; the file is simply gone.
- `git checkout -- .` fires only *post*-hooks — after the overwrite.
- `git reset --hard` with a hook that exits 1 prints `fatal: ref updates aborted
  by hook`, returns 128, **and the uncommitted work is gone anyway** — the
  worktree clobber happens before the ref transaction the hook guards.

So the most expensive class of incident in this project is invisible to every
hook-shaped mechanism. It has to be refused at the tool surface, which is what
Tier 1 is.

## The three tiers

Split by what an operation can **destroy**, never by mirroring git's command list.

### Tier 1 — refused outright

`reset --hard` (and `--merge`/`--keep`) · `checkout -- <paths>` / `restore` ·
`clean` · `stash` (mutating forms)

Every refusal **names the alternative**: a detached worktree under a scratch area
outside the repository, with its own HEAD, index and working tree. A refusal that
does not say what to do next is how bypasses get invented, so the alternative is a
required field, not a nicety.

> *"Restore the tree"* and *"preserve the tree"* are different instructions and
> only the caller knows which was meant. gitRobot resolves the ambiguity by
> refusing the destructive reading.

### Tier 2 — mediated

| operation | what gitRobot enforces |
|---|---|
| `stage` | named paths only; `-A`/`.`/`-u` refused on the main repo (background agents write here concurrently, and a scratch probe reached permanent history that way). `.claude-local` is exempt — bulk add is its documented flow — reached as a **named mode**, never a path. |
| `commit` | the project's `pre-commit` pipeline runs **first**, so a failing gate costs a report rather than a half-made commit; the installed hook runs again during the commit as the backstop. Message read from a **file**, never argv. |
| `preflight` | STARTS the full `pre-push` pipeline **without pushing** and returns at once; the verdict is recorded against the current HEAD when it lands |
| `preflight_status` | `running` / `passed` / `failed` / **`died`** / `none` for the current HEAD |
| `push` | refuses without a passing preflight for the current HEAD, and without a stated reason |
| `worktree` | **encouraged** — the sanctioned escape from Tier 1, in one call |

**Why `preflight` is separate from `push`.** A gate that runs *inside* the push has
a zero-length response window: the push completes in the same invocation, so the
findings arrive after the irreversible act. Splitting the verdict from the act is
the point. A preflight is bound to the HEAD it ran against, so it cannot authorise
anything committed after it.

**Why `preflight` does not wait.** Measured 2026-08-22: the real pipeline takes
~155s. Held open, that outlives two separate limits — the caller's ~120s call
window, and (the one that actually bit) the supervisor's 30s health poll. FastMCP
runs a synchronous tool function *on the event loop*, so a blocking call stalls
the whole server; the supervisor saw gitRobot unresponsive, declared it Down,
restarted it, and killed the run mid-flight, losing both the verdict and its audit
trail. So every tool is `async` and offloads to a worker thread, and `preflight`
writes a `started` row, runs in the background, and appends the verdict when it
lands. An interrupted run is reported as **`died`** rather than as silence —
because "it failed" and "it never ran" are different facts.

**gitRobot does not reimplement the gate pipeline.** It invokes the project's own
`tools/verify/hooks.py <phase>`. There was previously one pipeline in shell and
one in Python; they measurably disagreed three ways while checking disjoint
things, and the shell half was retired for it. A third implementation would drift
the same way. What gitRobot adds is that the pipeline cannot be skipped with a
flag, and that its verdict is recorded.

### Tier 3 — read-through

`status` `log` `diff` `show` `ls-files` `ls-remote` `rev-parse` `rev-list`
`cat-file` `describe` `blame` `shortlog`, plus the read forms of
`config` `branch` `remote` `worktree` `stash` `tag`.

No gates, no audit, no confirmation. **An agent that cannot read repository state
is blind, and a blind agent makes worse decisions, not safer ones.** Reads depend
on nothing but a subprocess call — not the gate pipeline, not the preflight, not
network.

**It is an allow-list, and that inversion is deliberate.** An enumerated
deny-list permits every subcommand nobody has thought of yet — this project's most
repeated defect. Here an unclassified operation is refused until someone
classifies it. `branch --list` reads; `branch -D` deletes; splitting by subcommand
alone would have let the second through.

## Absent by design

No `force`, no `no_verify`, no `skip_gates`, no `allow_dirty`, no `repo`, no raw
`passthrough(cmd)`. Their absence is what makes the installed hooks a real
backstop instead of an honour system, so it is **asserted by a test** over both
the library and the MCP surface, not assumed. *A control nobody has seen fail is a
hypothesis.*

`GITROBOT_REPO` is an allow-list of one, resolved at startup. There is no repo
argument: accepting one would make this a general-purpose git proxy for every
checkout on the machine — a strictly worse hole than the one it closes.

## The audit log

Every Tier 1 and Tier 2 call appends one line to `data/git_ops.jsonl` — timestamp,
actor, operation, arguments, HEAD, branch, tree state, decision, gate verdicts
where run, the caller's reason, the refusal's *alternative* (so `explain` survives
a restart), and the writing `pid` (so an interrupted run is detectable). Append-only, same shape as the sibling
registry's audit sidecar.

**Refusals are logged too, and so are clean passes.** This comes directly from a
measured defect: the consumer project's push gate spends real time and real money
per run and writes no file at all when everything passes, because it only writes
on a finding. Afterwards, *"judged clean"* and *"never ran"* are
indistinguishable — which is precisely the state in which a control has quietly
stopped working.

Tier 3 reads are not logged. They change nothing, and the volume would bury the
signal.

## Architecture

```
gitRobot/
  core/                 engine.py  tiers.py  gates.py  gitio.py  audit.py  errors.py  cli.py
  gitrobot_server/      server.py               # thin FastMCP transport
  data/git_ops.jsonl                            # append-only, gitignored
  scripts/serve.ps1
  tests/
```

`core` owns everything — repo resolution, tier classification, gate running, git
invocation, audit. `gitrobot_server` is transport and enforces nothing. **`core`
is a working library and CLI with no MCP installed**, so if the server is down the
rules still exist and a human can still apply them.

⚠ **The availability trade is real.** Mediating *all* git means a dead gitRobot
leaves agents with no git. That is why it is registered with the supervisor
(health-checked every 30s, automatic repair with backoff) and why Tier 3 must
never depend on anything but a subprocess call.

⚠⚠ **The MCP package is `gitrobot_server/`, not `mcp_server/`, and this is
load-bearing.** The supervisor identifies a running server by process name plus a
command-line substring — no working-directory or port filter. The sibling registry
already runs `python -m mcp_server.server`; a second server on that module path
would be indistinguishable from it, and a gitRobot repair would have targeted and
killed the registry. Never give two supervised servers the same module path.

| env var | default | purpose |
|---|---|---|
| `GITROBOT_REPO` | `C:\Workspace\ZeroParadox` | the one repo this may act on |
| `GITROBOT_DATA` | `data/git_ops.jsonl` | append-only audit sidecar |
| `GITROBOT_HOST` / `GITROBOT_PORT` | `127.0.0.1` / `8010` | loopback unless you mean otherwise |
| `GITROBOT_ACTOR` | `mcp` | actor recorded in the log |

## Still open — decisions, not omissions

1. **Does `push` run the paid LLM gates?** `preflight` runs whatever
   `tools/verify/hooks.py pre-push` runs; gitRobot does not choose the legs. If
   those legs should be split from the deterministic ones, that split belongs in
   the project's own plan, not here.
2. **`.claude-local`** is lightly mediated (bulk add permitted, no gates). It has a
   private remote and no pipeline. Deliberate, but worth revisiting.
3. **`push` does not reach branch or PR creation**, and `gh` is not proxied.
   Releases mint permanent DOIs; that is a human decision, and it is out of scope
   until someone decides otherwise.
4. **The `.claude-local` → OneDrive backup** used to be triggered by a PostToolUse
   hook matching `git commit`. Direct git is now blocked, so that hook can no
   longer fire. It needs re-hooking to gitRobot's commit path.

## Tests

```
python -m pytest -q          # 125 tests
```

Every test runs against a disposable repository created per test — never the
configured one. A suite for a guard that could damage the thing it guards would be
its own worst defect. Coverage: a refusal on each Tier 1 operation *with the
uncommitted work asserted still present afterwards*; `-A` refused on the main repo
and permitted for `.claude-local`; a blocked commit and a blocked push on a failing
gate; a clean allow; one audit line per Tier 1/2 call including the clean path; and
the control asserting the absent parameters are still absent.
