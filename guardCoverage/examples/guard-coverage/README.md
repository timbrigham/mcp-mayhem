# Incident-Driven Guard Coverage

This is a single-author proof of concept, built for and used in one dedicated environment. It demonstrates the measurement; it is not a production or complete tool.

## What it measures

The full definition is in the submission. In short: observations are harmful actions the tools
allowed (incidents) and attempts a logging guard refused (policy refusals), each mapped to a
pattern by a versioned rule (rule 1, in `guard_coverage/rule.py`). Only refusals of class
`policy` are observations; the other classes in the output (`allowlist`, `gate`, `operational`)
are not. K is the set of patterns observed; G is the subset with a guard and a regression test
at the same entry point, the place where the guard intercepts the action: the agent's own shell
(`agent-shell`) or gitRobot (`gitrobot-mcp/cli`). The tool reports (1) |G|/|K|, (2) time to
guard, (3) new patterns per batch of agent instances, and (4) Û = Q1/n, where Q1 and Q2 count
patterns seen in exactly one and exactly two agent instances: Û estimates U_n, the expected
number of patterns absent from a window's n instances that appear in the next instance. A
window is a stretch of time in which no logged version changes; a change starts a new one. Item
4 is reported for a window only when its n ≥ 100.

The unit is an agent instance: one agent context, such as a subagent. A pattern counts once per
instance. Here the agents are Claude Code, a coding-agent client, and the guard layer is
gitRobot, a server that mediates an agent's git commands. Claude Code keeps a transcript, a
local log of one agent's conversation, for each main conversation and each subagent; transcripts
are private and are not published. The client sends its own id with every tool call (Claude
Code's `tool_use` id), and the instance is the one transcript that contains it. gitRobot logs
that id from 2026-10-15T18:02Z; in this fixture 3,811 of the 3,812 call rows were recovered from
its HTTP call log instead (below). n counts only instances that called gitRobot at least once;
agents that never did are not seen.

A call is not placed in an instance when it has no id, when its id is in no transcript, or when
its id is in several: a forked subagent's transcript begins with a copy of its parent's history,
call ids included, and the copies cannot be told from the original. The report counts each
case. The manifest declares which client the ids belong to (`instance_source`) and which MCP
clients are agents (`agent_clients`). Calls from other clients, such as a commit hook calling
the guard layer (`zp-record`, `zp-hooks-attest` in the output), are not agent calls, and the
report lists them with reasons. A call row that records no client counts as an agent call when
the instance map places its id, since the map is built from that client's own transcripts;
every instance seen before 2026-10-13T14:23Z is placed that way. MCP sessions are reported as
context only.

When any of a pattern's occurrence times is unknown, its time to guard runs from detection, is
marked as a lower bound and is left out of the median, which therefore errs optimistic: long lags
gather more incidents and are more often left out.

Versions are only what is logged. This implementation logs the guard layer's commit, the client's
name and version, and each guard's version history from the manifest, but no model version, so a
model change silently pools windows. Outside a git checkout the commit is null and the row is not
windowed.

### Change of unit

The unit was an MCP session until 2026-10-15. One long-lived agent process spawns many
short-lived subagents over a single MCP connection: in the published data, all 301 instances in
the version window below called the guard layer over one MCP session. A session count could not
reach n ≥ 100.

## Reproduce

Python 3.11 or later as `python3` (stock macOS Python may be older), standard library only;
`pip install pytest` for the tests. Check out the release tag the submission cites:

```console
git clone --branch <release tag> https://github.com/timbrigham/mcp-mayhem
cd mcp-mayhem/guardCoverage
python3 -m pytest -q
```

The expected real-data report is `examples/guard-coverage/fixture/expected_report.json` (compare
it with `--json` output), and `fixture/CHECKSUMS.sha256` verifies the fixture files. The instance
map in the fixture was built from the private transcripts, so a reader can re-run the measurement
from it but cannot re-derive the map itself.

## Real data

The fixture is a redacted extract of the real audit log, call log, instance map and incident
register (`make_fixture.py`). Session ids, call ids and instance ids are salted hashes, each kind
in its own namespace. It contains no transcript text or file names, no harm text, notes, paths
or test names, and no arguments beyond the pattern feature.

gitRobot has logged call ids since 2026-10-15T18:02Z. Earlier calls were recovered once from its HTTP
call log (`python3 -m guard_coverage backfill`). That log rotates in about a day, and the copies
kept cover two stretches: 2026-10-09T17:19:30Z to 10-14T22:46:58Z, and 10-15T10:32:14Z onward.
**Calls between those two times are not recoverable.** The audit log has 676 rows strictly
between them, 76 of them from the agent client, so instances that worked only in the gap are
missing from n.

Refusals logged before audit rows carried call ids were linked to their calls by a unique-match
rule: the call in the same session that was in progress when the refusal was written, if there
was exactly one and it was a refusal. The rule ran on the private logs; the fixture carries only
its result. Of the 7 refused rows of any class that carry version fields (from 2026-10-14), 5
linked, including the one policy refusal; 2 allowlist refusals did not, because another call
was in progress at the same time.

```console
$ python3 -m guard_coverage measure --audit examples/guard-coverage/fixture/audit.jsonl --calls examples/guard-coverage/fixture/calls.jsonl --instances examples/guard-coverage/fixture/instances.json --register examples/guard-coverage/fixture/register.json --manifest examples/guard-coverage/fixture/manifest.json
Incident-Driven Guard Coverage (rule 1), as of 2026-10-15T18:02:28.922379+00:00; unit: agent instance
inputs: 9164 audit rows, 3812 call rows, 1839 instance-map entries, 5 register entries, 3 declared guards
observations: 1 policy refusals, 5 incidents; 404 agent instances (in 4 agent sessions, context only)
skipped rows:
    2521  audit rows from a client not declared as an agent
      54  audit rows from mcp without a versions field (before it existed): client unknown, not agent rows
    5935  audit rows lacking the surface/session fields (before they existed): cannot be agent rows
    1927  call rows from a client not declared as an agent
      33  call rows from mcp without a versions field (before it existed, or backfilled outside a known server process): client unknown, not agent rows
       9  call rows with no recorded client: not agent rows
     177  refused rows lacking refusal_class (before it existed): cannot be observations
       3  refused rows with refusal_class allowlist: not policy refusals
       2  refused rows with refusal_class gate: not policy refusals
       4  refused rows with refusal_class operational: not policy refusals
agent clients declared: claude-code; instances from: claude-code
agent rows not placed in an instance:
     480  audit rows lacking client_call_id (before it existed): no instance
       1  call rows whose call id is in no transcript: no instance
       3  call rows whose call id is in several transcripts (a forked subagent's copy of its parent's history): no instance
sessions not counted as agent sessions:
       9  client not recorded
      29  client unknown (no versions field)
      75  client zp-hooks-attest not declared as an agent
    2446  client zp-record not declared as an agent
caveat: guard zp-block-git-gh (agent-shell) does not log refusals: it contributes no refusal observations
caveat: guard zp-dc71-dotnet-relative-write (agent-shell) does not log refusals: it contributes no refusal observations

1. guarded share |G|/|K| = 4/4 = 100.0%
   in G       git.reset.work-destroying  (agent-shell)
   in G       gitrobot.push.refspec-force  (gitrobot-mcp/cli)
   in G       gitrobot.worktree-target.any  (gitrobot-mcp/cli)
   in G       powershell.dotnet-file-write.relative-path  (agent-shell)

2. time to guard (first occurrence to the commit with guard and test in place)
   git.reset.work-destroying: >= 51.89 days  [lower bound: measured from detection]
   gitrobot.push.refspec-force: >= 0.00 days  [lower bound: measured from detection; detected at fix time]
   gitrobot.worktree-target.any: guarded before first observation (41.23 days earlier); not a time to guard, excluded from the median
   powershell.dotnet-file-write.relative-path: >= 8.67 days  [lower bound: measured from detection]
   median: withheld (none of the 4 value(s) is exact: each is a lower bound or guarded before first observation)

3. discovery trend: new patterns per batch of 10 agent instances (404 instances)
   before the first logged instance: 2
   batch 1 (10 instances, from 2026-10-09T17:19:30+00:00): 0 new
   batch 2 (10 instances, from 2026-10-09T21:53:41+00:00): 0 new
   batch 3 (10 instances, from 2026-10-09T22:10:44+00:00): 0 new
   batch 4 (10 instances, from 2026-10-09T22:17:23+00:00): 0 new
   batch 5 (10 instances, from 2026-10-09T22:19:21+00:00): 0 new
   batch 6 (10 instances, from 2026-10-09T22:34:57+00:00): 0 new
   batch 7 (10 instances, from 2026-10-09T22:38:21+00:00): 0 new
   batch 8 (10 instances, from 2026-10-09T22:44:47+00:00): 1 new
   batch 9 (10 instances, from 2026-10-13T12:06:24+00:00): 0 new
   batch 10 (10 instances, from 2026-10-13T12:27:31+00:00): 0 new
   batch 11 (10 instances, from 2026-10-13T12:45:10+00:00): 0 new
   batch 12 (10 instances, from 2026-10-13T22:41:41+00:00): 0 new
   batch 13 (10 instances, from 2026-10-13T23:14:16+00:00): 0 new
   batch 14 (10 instances, from 2026-10-13T23:41:04+00:00): 0 new
   batch 15 (10 instances, from 2026-10-14T00:04:07+00:00): 0 new
   batch 16 (10 instances, from 2026-10-14T00:08:22+00:00): 0 new
   batch 17 (10 instances, from 2026-10-14T00:14:34+00:00): 0 new
   batch 18 (10 instances, from 2026-10-14T00:16:01+00:00): 0 new
   batch 19 (10 instances, from 2026-10-14T00:21:47+00:00): 0 new
   batch 20 (10 instances, from 2026-10-14T00:24:37+00:00): 0 new
   batch 21 (10 instances, from 2026-10-14T00:34:23+00:00): 0 new
   batch 22 (10 instances, from 2026-10-14T00:36:20+00:00): 0 new
   batch 23 (10 instances, from 2026-10-14T00:38:23+00:00): 0 new
   batch 24 (10 instances, from 2026-10-14T00:41:39+00:00): 0 new
   batch 25 (10 instances, from 2026-10-14T00:58:47+00:00): 0 new
   batch 26 (10 instances, from 2026-10-14T01:26:54+00:00): 0 new
   batch 27 (10 instances, from 2026-10-14T01:43:06+00:00): 0 new
   batch 28 (10 instances, from 2026-10-14T02:07:34+00:00): 0 new
   batch 29 (10 instances, from 2026-10-14T02:18:41+00:00): 0 new
   batch 30 (10 instances, from 2026-10-14T02:50:48+00:00): 0 new
   batch 31 (10 instances, from 2026-10-14T11:30:03+00:00): 0 new
   batch 32 (10 instances, from 2026-10-14T12:08:50+00:00): 0 new
   batch 33 (10 instances, from 2026-10-14T14:25:54+00:00): 0 new
   batch 34 (10 instances, from 2026-10-14T17:34:50+00:00): 0 new
   batch 35 (10 instances, from 2026-10-14T18:01:48+00:00): 0 new
   batch 36 (10 instances, from 2026-10-14T18:13:13+00:00): 0 new
   batch 37 (10 instances, from 2026-10-14T19:23:47+00:00): 0 new
   batch 38 (10 instances, from 2026-10-14T19:25:28+00:00): 0 new
   batch 39 (10 instances, from 2026-10-14T21:03:58+00:00): 1 new
   batch 40 (10 instances, from 2026-10-15T11:22:37+00:00): 0 new
   batch 41 (4 instances, partial, from 2026-10-15T13:16:30+00:00): 0 new

4. unseen-pattern estimate U_hat = Q1/n (windows derived from versions fields and manifest guard versions)
   W1 2026-10-13T15:02:31+00:00 .. 2026-10-15T14:19:44+00:00: n=301 Q1=1 Q2=0; U_hat = Q1/n = 0.0033
   instances in no window: 103
   rows not placed in a window (no versions field (before it existed)): 6099
   rows not placed in a window (no versions field (before it existed, or backfilled outside a known server process)): 548
   excluded from item 4: 5 incident observation(s) with no known agent instance
```

The real data is thin. K is 4 patterns: 3 from incidents and 1 policy refusal. 2 of the 3
declared guards do not log refusals. **Item 2's median is withheld**: every time to guard is a
lower bound, except `gitrobot.worktree-target.any`, whose guard and test (2026-09-03) predate
its first observation (2026-10-14), so it has no time to guard.

**Item 4 reports**, from one window of 301 agent instances: Q1 = 1, Q2 = 0, Û = 0.0033. Q1's
one pattern is `gitrobot.worktree-target.any`, the one policy refusal. All 5 incidents lack an instance and are excluded, so
on this data Û reflects only the gitRobot surface. With Q1 = 1 the estimate cannot be told
apart from zero: it shows the estimate can be computed on real data, not that it is precise. The
synthetic precision below describes a different regime (mean Û 0.026). The instances are also
not independent draws: many are subagents of one parent working on related tasks, so a pattern
handed to several of them counts toward Q2 rather than Q1, which would bias Û low.

The report counts 404 instances for item 3. 103 of them called gitRobot only before it logged
version fields (2026-10-13T14:23Z), so they cannot be placed in a version window and are not in n. 4
calls are not placed in an instance: 3 call ids appear in several subagent transcripts (forked
copies), and 1 is in no transcript (the one call gitRobot logged itself, at 2026-10-15T18:02Z,
made from outside the agent project). 480 agent audit rows carry no call id themselves; such a
call is placed through its call-log row when one exists.

**One case shows what the metric is for.** `git.reset.work-destroying` (INC-0001, the first
entry in the incident register) happened in a raw agent shell, outside gitRobot. A hook blocking
all direct git commands was committed the day after its first record, in ZeroParadox, the public
project these agents work on (commit 872811c). Per that commit's message the hooks were already
wired through an ignored local settings file, so blocking may have started earlier. But a
regression test replaying `git reset --hard` specifically through the hook came at least 51.9
days after that first record (5bf7106, merged as 283157b on 2026-10-13). The blocking hook was
committed fast; the guard tested against this action came much later. The register keeps the guard it first recorded (gitRobot's, at a different
entry point) in a `guard_history` list.

## Synthetic replay

SYNTHETIC: simulated data with a known truth. Before a pattern has a guard, an attempt is seen
only if recorded as an incident (probability r); after a logging guard it is a refusal; after a
non-logging guard it leaves nothing. Each simulated instance is independent and attempts a
pattern at most once: retries are not modelled. A retry within one instance would not change Q1
or Q2, but a retry handed to a new instance would, and that case is not simulated. In the output,
pi is a pattern's per-instance attempt probability: a guard halves it for its own pattern and
raises it by half for the patterns ranked next to it.

```console
$ python3 -m guard_coverage synthetic --seed 7 --replicates 1000
SYNTHETIC REPLAY: simulated data, not observations
seed 7, 1000 replicates; 30 patterns, 2000 agent instances, Zipf s=1.5, p_max=0.30
unit: agent instance; retries are not modelled (an instance attempts a pattern at most once)
recording: before a guard, an attempt is a recorded incident with r=0.30 (occurrence time unknown for 30%);
  after a logging guard (70% of guards) it is a policy refusal; after a non-logging guard, nothing
injected lag uniform 12-240 h from first recorded occurrence; at each guard: pi x0.5, rank neighbours x1.5; window restarts

SYNTHETIC item 4, unseen-pattern estimate U_hat = Q1/n:
  windows 28908; withheld at n < 100: 23368 = 80.8% of windows, 36.4% of instances
  why withheld: a window ends at every guard change (median 33 instances); on Zipf data
  the frequent patterns are seen and guarded early, so only later, quieter stretches reach n >= 100
  reported 5540 windows (n >= 100 only), mean U_hat 0.0262; 95% CIs: cluster bootstrap over replicates, 1000 resamples
  vs U_n (in-window), the target: bias +0.0004 (95% CI -0.0000 to +0.0009), RMSE 0.0180, mean relative error +0.282
    secondary: coverage P(U_hat >= truth | truth > 0) 0.501 (95% CI 0.488-0.515, 5521 windows); truth = 0 in 19
  vs never observed at all (secondary): bias +0.0185 (95% CI +0.0181 to +0.0190), RMSE 0.0255, mean relative error +5.609
    secondary: coverage P(U_hat >= truth | truth > 0) 0.903 (95% CI 0.895-0.911, 5141 windows); truth = 0 in 399
  (Q1 is skewed and discrete, so an unbiased estimate need not cover half the time)
SYNTHETIC item 2, time to guard vs injected lag (median injected 126 h):
  exact values 16183 (equal to the injected lag by construction)
  lower bounds 12031, mean shortfall 36.5 h
  median (exact only) minus median injected, mean over replicates: -9.2 h; median withheld in 0 replicates
end-to-end (replicate 0 through measure(): 878 refusal rows, 70 incidents): windows agree yes, time to guard agree yes
```

Against U_n, Û is close to unbiased (bias +0.0004) but imprecise: the RMSE of 0.018 is about 70%
of the mean Û (0.0262), the mean relative error is +0.28, and it is withheld for 81% of windows
(36% of instances). Against patterns never observed at all it runs high, as the definition says.
These bias and coverage figures are **conditional on n ≥ 100**, an outcome-selected subset of
windows. The exact-only median of time to guard is optimistic: 9.2 h short of a median injected
lag of 126 h, because long lags collect more incidents and are more often demoted to lower
bounds. The simulation's unit was always one independent simulated agent, so these figures did
not change when the real-data unit changed from an MCP session to an agent instance.
