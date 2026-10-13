# Incident-Driven Guard Coverage

This is a single-author proof of concept, built for and used in one dedicated environment. It demonstrates the measurement; it is not a production or complete tool.

## What it measures

The full definition is in the submission. In short: observations are harmful actions the tools
allowed (incidents) and attempts a logging guard refused (policy refusals), each mapped to a
pattern by a versioned rule (rule 1, in `guard_coverage/rule.py`). K is the set of patterns
observed; G is the subset with a guard and a regression test at the same entry point. The tool
reports (1) |G|/|K|, (2) time to guard, (3) new patterns per batch of sessions, and (4) Û = Q1/n,
where Q1 counts patterns seen in exactly one session: an estimate of U_n, the expected number of
patterns absent from a window's n sessions that appear in the next one. Item 4 is reported only
when n ≥ 100.

When any of a pattern's occurrence times is unknown, its time to guard runs from detection, is
marked as a lower bound and is left out of the median, which therefore errs optimistic: long lags
gather more incidents and are more often left out.

Versions are only what is logged. This implementation logs the guard layer's commit (gitRobot, a
server that mediates an agent's git commands), the client's name and version, and each guard's
version history from the manifest, but no model version, so a model change silently pools
windows. Outside a git checkout the commit is null and the row is not windowed.

## Reproduce

Python 3.11 or later as `python3` (stock macOS Python may be older), standard library only;
`pip install pytest` for the tests. Check out the release tag the submission cites:

```console
git clone --branch <release tag> https://github.com/timbrigham/mcp-mayhem
cd mcp-mayhem/guardCoverage
python3 -m pytest -q
```

The expected real-data report is `examples/guard-coverage/fixture/expected_report.json` (compare
it with `--json` output), and `fixture/CHECKSUMS.sha256` verifies the fixture files.

## Real data

The fixture is a redacted extract of the real audit log and register (`make_fixture.py`: session
ids are salted hashes; no harm text, notes, paths, test names or arguments beyond the pattern
feature).

```console
$ python3 -m guard_coverage measure --audit examples/guard-coverage/fixture/audit.jsonl --register examples/guard-coverage/fixture/register.json --manifest examples/guard-coverage/fixture/manifest.json
Incident-Driven Guard Coverage (rule 1), as of 2026-10-13T14:23:31.326410+00:00
inputs: 6100 audit rows, 5 register entries, 3 declared guards; 0 policy-refusal observations, 5 incident observations, 14 MCP sessions
skipped audit rows:
     177  refused rows lacking refusal_class (before it existed): cannot be observations
       3  refused rows with refusal_class operational: not policy refusals
    5935  rows lacking the surface/session fields (before they existed): cannot be sessions
caveat: guard zp-block-git-gh (agent-shell) does not log refusals: it contributes no refusal observations
caveat: guard zp-dc71-dotnet-relative-write (agent-shell) does not log refusals: it contributes no refusal observations

1. guarded share |G|/|K| = 2/3 = 66.7%
   in G       gitrobot.push.refspec-force  (gitrobot-mcp/cli)
   in G       powershell.dotnet-file-write.relative-path  (agent-shell)
   unguarded  git.reset.work-destroying  (agent-shell), age >= 51.75 days
              - guard zp-block-git-gh at agent-shell has no regression test replaying it
              - INC-0001's recorded guard 77c6d09 is gitrobot's, at gitrobot-mcp/cli, not at agent-shell

2. time to guard (first occurrence to the commit with guard and test in place)
   gitrobot.push.refspec-force: >= 0.00 days  [lower bound: measured from detection; detected at fix time]
   powershell.dotnet-file-write.relative-path: >= 8.67 days  [lower bound: measured from detection]
   median: withheld (every value (2) is a lower bound: no occurrence time is known, so a median would describe detection, not occurrence)

3. discovery trend: new patterns per batch of 10 sessions (14 sessions)
   before the first logged session: 3
   batch 1 (10 sessions, from 2026-10-13T11:55:19.802146+00:00): 0 new
   batch 2 (4 sessions, partial, from 2026-10-13T12:33:42.317781+00:00): 0 new

4. unseen-pattern estimate U_hat = Q1/n (windows derived from versions fields and manifest guard versions)
   no window contains a session: n = 0, Q1 = 0, Q2 = 0; U_hat needs n >= 100
   sessions in no window: 14
   rows not placed in a window (no versions field: before it existed): 6099
   excluded from item 4: 1 incident observation(s) whose session is in no window
   excluded from item 4: 4 incident observation(s) with no known session
```

The real data is thin. K is 3 patterns, all from incidents. There are 0 policy refusals since
the `refusal_class` field was added, partly by construction: 2 of the 3 declared guards do not
log refusals. **Item 2's median is withheld and item 4 is not computable here**: every time to
guard is a lower bound, and no session yet carries version fields, so n = 0. The behaviour of
both is shown only on synthetic data.

**One case shows what the metric is for.** `git.reset.work-destroying` (INC-0001) happened in a raw
agent shell. ZeroParadox (the public project these agents work on) has a shell hook that has
denied all direct git since 2026-08-23T14:22:18Z, about 18 hours after detection. But no
regression test yet replays `git reset --hard` through that hook, and the register still records
gitRobot's guard, at a different entry point. So the pattern is **not** in G: protection came
fast, while the tested guard is still pending, about 52 days on.

## Synthetic replay

SYNTHETIC: simulated data with a known truth. Before a pattern has a guard, an attempt is seen
only if recorded as an incident (probability r); after a logging guard it is a refusal; after a
non-logging guard it leaves nothing.

```console
$ python3 -m guard_coverage synthetic --seed 7 --replicates 1000
SYNTHETIC REPLAY: simulated data, not observations
seed 7, 1000 replicates; 30 patterns, 2000 sessions, Zipf s=1.5, p_max=0.30
recording: before a guard, an attempt is a recorded incident with r=0.30 (occurrence time unknown for 30%);
  after a logging guard (70% of guards) it is a policy refusal; after a non-logging guard, nothing
injected lag uniform 12-240 h from first recorded occurrence; at each guard: pi x0.5, rank neighbours x1.5; window restarts

SYNTHETIC item 4, unseen-pattern estimate U_hat = Q1/n:
  windows 28908; withheld at n < 100: 23368 = 80.8% of windows, 36.4% of sessions
  why withheld: a window ends at every guard change (median 33 sessions); on Zipf data
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
(36% of sessions). Against patterns never observed at all it runs high, as the definition says. These bias and coverage figures are **conditional on
n ≥ 100**, an outcome-selected subset of windows. The exact-only median of time to guard is
optimistic: 9.2 h short of a median injected lag of 126 h, because long lags collect more
incidents and are more often demoted to lower bounds.
