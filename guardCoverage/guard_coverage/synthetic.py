"""SYNTHETIC replay. Simulated data only; nothing here is an observation.

It checks the estimators against a world whose truth is known.

The unit is an AGENT INSTANCE (one agent context, such as a subagent): one simulated instance
per hour, 2,000 of them, each its own unit.

Attempts
  30 patterns; pattern k (rank 1..30) is attempted in an instance with probability
  pi_k = P_MAX / k**ZIPF_S (a Zipf shape: a few frequent patterns, a long tail of rare ones),
  independently per instance.
  RETRIES ARE NOT MODELLED: an instance attempts a pattern at most once. A retry inside the same
  instance would not change Q1 or Q2 (a pattern counts once per instance); a retry handed to a
  NEW instance (an agent re-spawned to try again) would, by making a single-instance pattern
  look like a two-instance one, and that case is not simulated.

What an attempt leaves behind (the recording rule)
  before the pattern has a guard   an INCIDENT, recorded with probability R_RECORD; otherwise
                                   nothing. Its occurrence time is unknown with probability
                                   P_UNKNOWN, and it is detected some time after it happened.
  after a guard that LOGS          a policy REFUSAL in that instance.
  after a guard that does not log  nothing. A share P_LOGS of guards log.
  So a pattern is first observed through a recorded incident, and its guard lands LAG hours
  after that first recorded occurrence, LAG ~ uniform{12..240} (injected, so recovery can be
  scored). The first incident is detected before its guard lands.

Guards
  At each guard the guarded pattern's pi is multiplied by GUARD_SELF and its rank neighbours'
  (k-1, k+1: "related") by GUARD_NEIGHBOUR, capped at PI_CAP. Each guard is a new guard
  version, so the item-4 window restarts there.

Targets for U_hat = Q1/n, in a window with n >= 100. omega_k is the per-instance probability
that pattern k is OBSERVED (pi_k times R_RECORD, 1 or 0 by guard state), in force in the window:
  U_n (in-window)          sum of omega_k over patterns absent from the window's instances:
                           the expected number of patterns absent from the window that appear
                           in the next instance. This is what item 4 defines U_hat to estimate.
  never observed at all    sum of omega_k over patterns never observed by the window end. A
                           secondary comparison: patterns seen only in earlier windows count
                           as absent in U_n, so U_hat errs high against this one.
Coverage = share of windows with truth > 0 in which U_hat >= truth; its 95% interval is a
cluster bootstrap over replicates (windows within one replicate are correlated).

The estimators are core.unseen_estimate, core.time_to_guard and core.median_of_exact: the code
under test, not a copy. Replicate 0 is also materialised as audit rows, a register and a
manifest and passed through core.measure end to end, and the results are compared.
"""

from __future__ import annotations

import heapq
import math
import random
import statistics
from datetime import datetime, timedelta, timezone

from . import core

N_PATTERNS = 30
N_INSTANCES = 2000
ZIPF_S = 1.5
P_MAX = 0.30
LAG_HOURS = (12, 240)
R_RECORD = 0.3
P_LOGS = 0.7
P_UNKNOWN = 0.3
DETECT_MAX_HOURS = 72
GUARD_SELF = 0.5
GUARD_NEIGHBOUR = 1.5
PI_CAP = 0.9
BOOTSTRAP = 1000
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)

UNGUARDED, LOGGING, SILENT = 0, 1, 2


def _geom(rng, start, p):
    """First instance >= start with an attempt, attempts i.i.d. Bernoulli(p) per instance."""
    u = rng.random()
    return start + int(math.log(1.0 - u) / math.log(1.0 - p))


def simulate(rng, r_record=R_RECORD, p_logs=P_LOGS):
    pi = [P_MAX / (k + 1) ** ZIPF_S for k in range(N_PATTERNS)]
    lag = [rng.randint(*LAG_HOURS) for _ in range(N_PATTERNS)]
    logs = [rng.random() < p_logs for _ in range(N_PATTERNS)]
    state = [UNGUARDED] * N_PATTERNS
    ver = [0] * N_PATTERNS
    incidents = [[] for _ in range(N_PATTERNS)]     # (instance, occurrence_known, delay_s)
    refusals = [[] for _ in range(N_PATTERNS)]      # instance
    first = [None] * N_PATTERNS                     # first RECORDED occurrence (instance)
    guard_at = [None] * N_PATTERNS
    snapshots = {0: (list(pi), list(state))}        # window start -> (pi, state) in force
    att = [(_geom(rng, 0, pi[k]), k, 0) for k in range(N_PATTERNS)]
    heapq.heapify(att)
    guards = []
    while True:
        t = att[0][0] if att else N_INSTANCES
        if guards and guards[0][0] <= t and guards[0][0] < N_INSTANCES:
            gs, k = heapq.heappop(guards)
            guard_at[k] = gs
            state[k] = LOGGING if logs[k] else SILENT
            for j, f in ((k, GUARD_SELF), (k - 1, GUARD_NEIGHBOUR), (k + 1, GUARD_NEIGHBOUR)):
                if 0 <= j < N_PATTERNS:
                    pi[j] = min(PI_CAP, pi[j] * f)
                    ver[j] += 1
                    heapq.heappush(att, (_geom(rng, gs, pi[j]), j, ver[j]))
            snapshots[gs] = (list(pi), list(state))
            continue
        if t >= N_INSTANCES:
            break
        t, k, v = heapq.heappop(att)
        if v != ver[k]:
            continue
        if state[k] == UNGUARDED:
            if rng.random() < r_record:
                known = rng.random() >= P_UNKNOWN
                if first[k] is None:
                    first[k] = t
                    heapq.heappush(guards, (t + lag[k], k))
                    delay = rng.randint(0, lag[k] * 3600)        # detected before the guard
                else:
                    delay = rng.randint(0, DETECT_MAX_HOURS * 3600)
                incidents[k].append((t, known, delay))
        elif state[k] == LOGGING:
            refusals[k].append(t)
        heapq.heappush(att, (_geom(rng, t + 1, pi[k]), k, v))
    return {"snapshots": snapshots, "incidents": incidents, "refusals": refusals,
            "first": first, "lag": lag, "logs": logs, "guard_at": guard_at,
            "r_record": r_record}


def _windows(sim):
    starts = sorted(sim["snapshots"])
    return [(b, (starts[i + 1] if i + 1 < len(starts) else N_INSTANCES))
            for i, b in enumerate(starts)]


def _omega(sim, pi, state):
    f = {UNGUARDED: sim["r_record"], LOGGING: 1.0, SILENT: 0.0}
    return [pi[k] * f[state[k]] for k in range(N_PATTERNS)]


def _obs_instances(sim, k):
    return [t for t, _, _ in sim["incidents"][k]] + sim["refusals"][k]


def score_windows(sim):
    out = []
    obs = [_obs_instances(sim, k) for k in range(N_PATTERNS)]
    for b, e in _windows(sim):
        omega = _omega(sim, *sim["snapshots"][b])
        counts = {}
        for k in range(N_PATTERNS):
            c = sum(1 for t in obs[k] if b <= t < e)
            if c:
                counts[k] = c
        res = core.unseen_estimate(counts, e - b)
        res["truth_in_window"] = sum(omega[k] for k in range(N_PATTERNS) if k not in counts)
        res["truth_never"] = sum(omega[k] for k in range(N_PATTERNS)
                                 if sim["first"][k] is None or sim["first"][k] >= e)
        out.append(res)
    return out


def _evidence(sim, k):
    """First evidence time and whether every occurrence time is known, as measure() sees it."""
    ev, known = [], True
    for t, kn, delay in sim["incidents"][k]:
        occ = T0 + t * HOUR
        ev.append(occ if kn else occ + timedelta(seconds=delay))
        known = known and kn
    ev += [T0 + t * HOUR for t in sim["refusals"][k]]
    return min(ev), known


def score_ttg(sim):
    vals, injected = [], []
    for k in range(N_PATTERNS):
        if sim["guard_at"][k] is None:
            continue
        ev, known = _evidence(sim, k)
        v = core.time_to_guard(ev, known, T0 + sim["guard_at"][k] * HOUR)
        v["injected_seconds"] = sim["lag"][k] * 3600.0
        v["pattern"] = k
        vals.append(v)
        injected.append(v["injected_seconds"])
    med = core.median_of_exact(vals)
    return vals, med, (statistics.median(injected) if injected else None)


# ----------------------------------------------------------------- end-to-end replicate
def _pid(k):
    return "gitrobot.read.synth-p%02d" % (k + 1)


def materialise(sim):
    """Replicate as audit rows, register, manifest and instance map, in the real input
    formats. Each simulated instance logs its calls under its own session too, so instances
    and sessions coincide here; the measurement counts the instances."""
    vers = {"gitrobot_commit": "synthetic", "gitrobot_dirty": False,
            "client_name": "synthetic", "client_version": "1", "consumer_hook_commit": None}
    by_instance = {}
    for k in range(N_PATTERNS):
        for t in sim["refusals"][k]:
            by_instance.setdefault(t, []).append(k)
    rows, imap = [], {}
    for t in range(N_INSTANCES):
        ts = (T0 + t * HOUR).isoformat()
        base = {"ts": ts, "surface": "mcp", "session": "s%05d" % t, "versions": vers}
        calls = [dict(base, op="status", decision="allowed", refusal_class=None, args={})]
        for k in by_instance.get(t, ()):
            calls.append(dict(base, op="read", decision="refused", refusal_class="policy",
                              args={"op": "synth-p%02d" % (k + 1)}))
        for j, c in enumerate(calls):
            c["client_call_id"] = "c%05d-%d" % (t, j)
            imap[c["client_call_id"]] = "i%05d" % t
            rows.append(c)
    entries, guards = [], [{"id": "gitrobot", "repo": "synthetic",
                            "entry_point": "gitrobot-mcp/cli", "logs_refusals": True,
                            "version": "synthetic-base", "version_at": T0.isoformat(),
                            "pattern_ids": [], "regression_test": {}}]
    for k in range(N_PATTERNS):
        g = sim["guard_at"][k]
        gts = None if g is None else (T0 + g * HOUR).isoformat()
        if g is not None:
            guards.append({"id": "synthetic-guard-%02d" % (k + 1), "repo": "synthetic",
                           "entry_point": "gitrobot-mcp/cli", "logs_refusals": sim["logs"][k],
                           "version": "v%02d" % (k + 1), "version_at": gts,
                           "pattern_ids": [_pid(k)],
                           "regression_test": {_pid(k): {"test": "synthetic",
                                                         "guard_commit": "c%02d" % (k + 1),
                                                         "guarded_at": gts}}})
        for i, (t, known, delay) in enumerate(sim["incidents"][k]):
            occ = T0 + t * HOUR
            entries.append({
                "id": "SYN-%02d-%03d" % (k + 1, i), "pattern_id": _pid(k),
                "status": "guarded" if g is not None else "open",
                "observed_at": occ.isoformat() if known else None,
                "detected_at": (occ + timedelta(seconds=delay)).isoformat(),
                "session": "s%05d" % t, "instance": "i%05d" % t,
                "tool": "synthetic:gitrobot",
                "guard_commit": None if g is None else "c%02d" % (k + 1),
                "regression_test": None if g is None else "synthetic",
                "guarded_at": gts})
    register = {"collections": {"incidents": {"schema_version": "1", "pattern_rule": "1",
                                              "entries": entries}}}
    manifest = {"manifest_version": "1", "guards": guards, "agent_clients": ["synthetic"],
                "instance_source": {"client": "synthetic"}}
    return rows, register, manifest, imap


def end_to_end(sim):
    rows, register, manifest, imap = materialise(sim)
    rep = core.measure(rows, register, manifest, "1", instance_map=imap)
    fast_w = [(w["n"], w["Q1"], w["Q2"], w["U_hat"]) for w in score_windows(sim)]
    slow_w = [(w["n"], w["Q1"], w["Q2"], w["U_hat"]) for w in rep["item4"]["windows"]]
    vals, _, _ = score_ttg(sim)
    fast_t = sorted((_pid(v["pattern"]), v["seconds"], v["lower_bound"],
                     v["guarded_before_first_observation"]) for v in vals)
    slow_t = sorted((v["pattern_id"], v["seconds"], v["lower_bound"],
                     v["guarded_before_first_observation"]) for v in rep["item2"]["values"])
    return {"windows_agree": fast_w == slow_w, "time_to_guard_agree": fast_t == slow_t,
            "windows": len(slow_w), "refusal_rows": sum(1 for r in rows
                                                        if r["decision"] == "refused"),
            "incidents": len(register["collections"]["incidents"]["entries"])}


# ----------------------------------------------------------------- run and report
def _mean(xs):
    return statistics.fmean(xs) if xs else None


# Per replicate and target: (covered, truth_positive, sum_err, sum_sq_err, reported,
# sum_rel_err). Windows within one replicate share a history, so intervals resample
# REPLICATES (a cluster bootstrap), never windows.
_COV, _POS, _ERR, _SQ, _N, _REL = range(6)


def _ratios(tot):
    return {"bias": tot[_ERR] / tot[_N] if tot[_N] else None,
            "coverage": tot[_COV] / tot[_POS] if tot[_POS] else None}


def _summarise(per_rep, rng):
    tot = [sum(x[i] for x in per_rep) for i in range(6)]
    point = _ratios(tot)
    boots = {"bias": [], "coverage": []}
    n = len(per_rep)
    for _ in range(BOOTSTRAP):
        t = [0.0] * 6
        for i in rng.choices(range(n), k=n):
            row = per_rep[i]
            for j in range(6):
                t[j] += row[j]
        for k, v in _ratios(t).items():
            if v is not None:
                boots[k].append(v)
    ci = {}
    for k, xs in boots.items():
        xs.sort()
        ci[k] = ([xs[int(0.025 * len(xs))], xs[min(len(xs) - 1, int(0.975 * len(xs)))]]
                 if xs else [None, None])
    return {"bias": point["bias"], "bias_ci95": ci["bias"],
            "rmse": math.sqrt(tot[_SQ] / tot[_N]) if tot[_N] else None,
            "mean_relative_error": tot[_REL] / tot[_POS] if tot[_POS] else None,
            "coverage": point["coverage"], "coverage_ci95": ci["coverage"],
            "windows": int(tot[_N]), "windows_truth_positive": int(tot[_POS]),
            "windows_truth_zero": int(tot[_N] - tot[_POS])}


def run(seed: int, replicates: int, r_record: float = R_RECORD, p_logs: float = P_LOGS) -> dict:
    win_all = win_rep = inst_withheld = 0
    lengths, uhat = [], []
    per = {"U_n_in_window": [], "never_observed": []}
    n_exact, shortfall, med_diff, injected_all = 0, [], [], []
    med_withheld = 0
    e2e = None
    for r in range(replicates):
        sim = simulate(random.Random("%d:%d" % (seed, r)), r_record, p_logs)
        acc = {k: [0.0] * 6 for k in per}
        for w in score_windows(sim):
            win_all += 1
            lengths.append(w["n"])
            if w["U_hat"] is None:
                inst_withheld += w["n"]
                continue
            win_rep += 1
            uhat.append(w["U_hat"])
            for key, truth in (("U_n_in_window", w["truth_in_window"]),
                               ("never_observed", w["truth_never"])):
                a, err = acc[key], w["U_hat"] - truth
                a[_ERR] += err
                a[_SQ] += err * err
                a[_N] += 1
                if truth > 0:
                    a[_POS] += 1
                    a[_COV] += w["U_hat"] >= truth
                    a[_REL] += err / truth
        for k in per:
            per[k].append(tuple(acc[k]))
        vals, med, med_inj = score_ttg(sim)
        for v in vals:
            injected_all.append(v["injected_seconds"] / 3600.0)
            if v["lower_bound"]:
                shortfall.append((v["injected_seconds"] - v["seconds"]) / 3600.0)
            elif not v["guarded_before_first_observation"]:
                n_exact += 1
        if med["median_seconds"] is None:
            med_withheld += 1
        else:
            med_diff.append((med["median_seconds"] - med_inj) / 3600.0)
        if r == 0:
            e2e = end_to_end(sim)
    boot = random.Random("bootstrap:%d" % seed)
    targets = {k: _summarise(v, boot) for k, v in per.items()}
    return {
        "synthetic": True, "seed": seed, "replicates": replicates,
        "unit": "agent instance", "retries_modelled": False,
        "params": {"patterns": N_PATTERNS, "instances": N_INSTANCES, "zipf_s": ZIPF_S,
                   "p_max": P_MAX, "lag_hours": list(LAG_HOURS), "r_record": r_record,
                   "p_logs": p_logs, "p_unknown": P_UNKNOWN,
                   "guard_self": GUARD_SELF, "guard_neighbour": GUARD_NEIGHBOUR,
                   "bootstrap": BOOTSTRAP},
        "windows": {"total": win_all, "withheld": win_all - win_rep,
                    "withhold_rate": (win_all - win_rep) / win_all,
                    "instances_in_withheld_windows": inst_withheld / (replicates * N_INSTANCES),
                    "median_window_instances": statistics.median(lengths),
                    "reported": win_rep, "mean_U_hat": _mean(uhat)},
        "targets": targets,
        "time_to_guard": {"exact": n_exact,
                          "lower_bounds": len(shortfall),
                          "mean_shortfall_hours": _mean(shortfall),
                          "median_injected_hours": (statistics.median(injected_all)
                                                    if injected_all else None),
                          "median_minus_injected_hours": _mean(med_diff),
                          "median_withheld_replicates": med_withheld},
        "end_to_end_replicate_0": e2e,
    }


def _f(x, fmt="%.4f"):
    return "n/a" if x is None else fmt % x


def render(res: dict) -> str:
    p, w, t = res["params"], res["windows"], res["time_to_guard"]
    e = res["end_to_end_replicate_0"]
    L = [
        "SYNTHETIC REPLAY: simulated data, not observations",
        "seed %d, %d replicates; %d patterns, %d agent instances, Zipf s=%.1f, p_max=%.2f"
        % (res["seed"], res["replicates"], p["patterns"], p["instances"], p["zipf_s"],
           p["p_max"]),
        "unit: agent instance; retries are not modelled (an instance attempts a pattern at "
        "most once)",
        "recording: before a guard, an attempt is a recorded incident with r=%.2f "
        "(occurrence time unknown for %.0f%%);" % (p["r_record"], 100 * p["p_unknown"]),
        "  after a logging guard (%.0f%% of guards) it is a policy refusal; "
        "after a non-logging guard, nothing" % (100 * p["p_logs"]),
        "injected lag uniform %d-%d h from first recorded occurrence; at each guard: pi x%.1f,"
        " rank neighbours x%.1f; window restarts"
        % (p["lag_hours"][0], p["lag_hours"][1], p["guard_self"], p["guard_neighbour"]),
        "",
        "SYNTHETIC item 4, unseen-pattern estimate U_hat = Q1/n:",
        "  windows %d; withheld at n < 100: %d = %.1f%% of windows, %.1f%% of instances"
        % (w["total"], w["withheld"], 100 * w["withhold_rate"],
           100 * w["instances_in_withheld_windows"]),
        "  why withheld: a window ends at every guard change (median %d instances); on Zipf data"
        % w["median_window_instances"],
        "  the frequent patterns are seen and guarded early, so only later, quieter stretches"
        " reach n >= 100",
        "  reported %d windows (n >= 100 only), mean U_hat %s; 95%% CIs: cluster bootstrap over"
        " replicates, %d resamples" % (w["reported"], _f(w["mean_U_hat"]), p["bootstrap"]),
    ]
    for key, label in (("U_n_in_window", "vs U_n (in-window), the target"),
                       ("never_observed", "vs never observed at all (secondary)")):
        g = res["targets"][key]
        L += [
            "  %s: bias %s (95%% CI %s to %s), RMSE %s, mean relative error %s"
            % (label, _f(g["bias"], "%+.4f"), _f(g["bias_ci95"][0], "%+.4f"),
               _f(g["bias_ci95"][1], "%+.4f"), _f(g["rmse"]),
               _f(g["mean_relative_error"], "%+.3f")),
            "    secondary: coverage P(U_hat >= truth | truth > 0) %s (95%% CI %s-%s, %d windows);"
            " truth = 0 in %d"
            % (_f(g["coverage"], "%.3f"), _f(g["coverage_ci95"][0], "%.3f"),
               _f(g["coverage_ci95"][1], "%.3f"), g["windows_truth_positive"],
               g["windows_truth_zero"]),
        ]
    L += [
        "  (Q1 is skewed and discrete, so an unbiased estimate need not cover half the time)",
        "SYNTHETIC item 2, time to guard vs injected lag (median injected %s h):"
        % _f(t["median_injected_hours"], "%.0f"),
        "  exact values %d (equal to the injected lag by construction)" % t["exact"],
        "  lower bounds %d, mean shortfall %s h"
        % (t["lower_bounds"], _f(t["mean_shortfall_hours"], "%.1f")),
        "  median (exact only) minus median injected, mean over replicates: %s h; "
        "median withheld in %d replicates"
        % (_f(t["median_minus_injected_hours"], "%+.1f"), t["median_withheld_replicates"]),
        "end-to-end (replicate 0 through measure(): %d refusal rows, %d incidents): windows "
        "agree %s, time to guard agree %s"
        % (e["refusal_rows"], e["incidents"], "yes" if e["windows_agree"] else "NO",
           "yes" if e["time_to_guard_agree"] else "NO"),
    ]
    return "\n".join(L) + "\n"
