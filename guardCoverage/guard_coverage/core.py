"""Incident-Driven Guard Coverage: the measurement.

`measure(rows, register, manifest, ...)` is pure: it reads only its arguments (no clock, no
files) and returns a JSON-serialisable report. "Now" is the latest timestamp in the inputs
unless `as_of` is given, so the same inputs always give the same report.

The small functions below (`unseen_estimate`, `time_to_guard`, `median_of_exact`) are the ones
the synthetic replay calls too, so the replay tests this code rather than a copy of it.
"""

from __future__ import annotations

import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime

from . import inputs as I
from .rule import refusal_pattern, require_rule

MIN_SESSIONS = 100           # item 4 is reported only when n >= this
DEFAULT_BATCH = 10           # item 3 batch size, in sessions

DAY = 86400.0


# --------------------------------------------------------------------- shared primitives
def unseen_estimate(sessions_per_pattern: dict, n: int, min_sessions: int = MIN_SESSIONS) -> dict:
    """Item 4 for one window. `sessions_per_pattern` maps pattern -> number of distinct
    sessions in the window that showed it (each session counted once per pattern)."""
    q1 = sum(1 for c in sessions_per_pattern.values() if c == 1)
    q2 = sum(1 for c in sessions_per_pattern.values() if c == 2)
    out = {"n": n, "Q1": q1, "Q2": q2, "U_hat": None, "withheld": None}
    if n >= min_sessions:
        out["U_hat"] = q1 / n
    else:
        out["withheld"] = ("n = %d sessions in this window; U_hat needs n >= %d "
                           "(sessions with no observation count toward n)" % (n, min_sessions))
    return out


def time_to_guard(first_evidence: datetime, occurrence_known: bool, guarded_at: datetime) -> dict:
    """Item 2 for one pattern. When the occurrence time is unknown the value runs from the
    earliest evidence (a detection) and is a lower bound on the true time to guard.
    A guard in place BEFORE the first observation (seconds < 0) is not a time to guard at
    all: it is flagged and kept out of the median, never counted as an exact value."""
    seconds = (guarded_at - first_evidence).total_seconds()
    return {"seconds": seconds, "lower_bound": not occurrence_known,
            "guarded_before_first_observation": seconds < 0}


def median_of_exact(values: list) -> dict:
    exact = [v["seconds"] for v in values
             if not v["lower_bound"] and not v["guarded_before_first_observation"]]
    if exact:
        return {"median_seconds": statistics.median(exact), "median_of": len(exact),
                "withheld": None}
    if not values:
        why = "no pattern is in G, so there is no time to guard"
    elif all(v["lower_bound"] for v in values):
        why = ("every value (%d) is a lower bound: no occurrence time is known, so a median "
               "would describe detection, not occurrence" % len(values))
    else:
        why = ("none of the %d value(s) is exact: each is a lower bound or guarded before "
               "first observation" % len(values))
    return {"median_seconds": None, "median_of": 0, "withheld": why}


# --------------------------------------------------------------------- windows
_SERVER_FIELDS = ("gitrobot_commit", "gitrobot_dirty")
_CONNECTION_FIELDS = ("client_name", "client_version", "consumer_hook_commit")


def _guard_versions_at(guards, ts):
    """The version of every guard in force at ts, from its optional version_history plus its
    current version. Before a guard's earliest dated version the key is "before:<it>"."""
    key = []
    for g in guards:
        hist = g["versions"]
        if not hist:
            continue                      # reported as a caveat; cannot place it in time
        now = "before:%s" % (hist[0][1],)
        for at, version in hist:
            if at <= ts:
                now = version
        key.append((g["id"], now))
    return tuple(key)


def derive_windows(rows, tss, guards):
    """Window id per row (None when the row cannot be placed), plus skip counts.

    A window holds agent, tool and guard versions fixed:
      server epoch    contiguous run (in time) of gitrobot_commit, gitrobot_dirty and the
                      manifest guard versions in force. The server is one process, so a change
                      here is a restart: a new epoch, even if a later value repeats an old one.
      connection      client_name, client_version, consumer_hook_commit, grouped by identity
                      within an epoch. Two clients connected at once are two windows rather
                      than restarting each other on every interleaved row.
    Rows without `versions` predate the field and are NOT placed: absent is not a value.
    Rows whose gitrobot_commit is null ran outside a git checkout: version unknown, not placed.
    """
    order = sorted(range(len(rows)), key=lambda i: tss[i])
    win = [None] * len(rows)
    skips = Counter()
    epoch, last = 0, None
    for i in order:
        r = rows[i]
        v = r.get("versions")
        if v is None:
            skips["no versions field: before it existed"] += 1
            continue
        if v.get("gitrobot_commit") is None:
            skips["gitrobot_commit null: not run from a git checkout"] += 1
            continue
        server = tuple(v.get(k) for k in _SERVER_FIELDS) + _guard_versions_at(guards, tss[i])
        if server != last:
            epoch += 1
            last = server
        win[i] = (epoch,) + tuple(v.get(k) for k in _CONNECTION_FIELDS)
    return win, skips


def explicit_windows(rows, tss, boundaries):
    """Window per row from caller-given boundaries: [b0,b1), [b1,b2), ..., [bk, inf).
    Rows before b0 are not placed. Version constancy inside each window is the caller's
    assertion, not checked here."""
    win = [None] * len(rows)
    skips = Counter()
    for i, ts in enumerate(tss):
        k = bisect_right(boundaries, ts)
        if k == 0:
            skips["before the first explicit boundary"] += 1
        else:
            win[i] = (k,)
    return win, skips


# --------------------------------------------------------------------- measure
def _iso(ts):
    return None if ts is None else ts.isoformat()


def _days(seconds):
    return None if seconds is None else round(seconds / DAY, 2)


def measure(rows, register, manifest, rule="1", *, audit_guard="gitrobot", boundaries=None,
            batch_size=DEFAULT_BATCH, as_of=None, min_sessions=MIN_SESSIONS) -> dict:
    """rows: audit log rows (dicts, as parsed from JSONL). register: the register document.
    manifest: the guard-set manifest document. boundaries: optional explicit window
    boundaries (sorted datetimes); otherwise windows are derived from the versions fields.
    Raises rule.UnknownRule or inputs.InputError when it cannot measure."""
    require_rule(rule)
    if not rows:
        raise I.InputError("audit log has no rows")
    if batch_size < 1:
        raise I.InputError("batch size must be at least 1")
    reg = I.validate_register(register)
    if reg["pattern_rule"] != rule:
        raise I.InputError("register patterns were classified under rule %r; asked to measure "
                           "under rule %r" % (reg["pattern_rule"], rule))
    man = I.validate_manifest(manifest)
    guards = sorted(man["guards"], key=lambda g: g["id"])
    by_id = {g["id"]: g for g in guards}
    if audit_guard not in by_id:
        raise I.InputError("the audit log's guard %r is not declared in the manifest"
                           % audit_guard)
    src = by_id[audit_guard]
    tss = [I.validate_row(r, "audit row %d" % (i + 1)) for i, r in enumerate(rows)]

    if boundaries is None:
        win, win_skips = derive_windows(rows, tss, guards)
        window_source = "derived from versions fields and manifest guard versions"
    else:
        win, win_skips = explicit_windows(rows, tss, boundaries)
        window_source = "explicit boundaries"

    skipped = Counter()
    obs = []                        # one dict per observation
    sessions_first = {}             # agent session -> first ts (items 3 and 4)
    window_sessions = defaultdict(set)
    window_span = {}
    unplaced_sessions = set()
    placed_sessions = set()
    agents = man["agent_clients"]
    non_agent_sessions = defaultdict(set)   # reason -> sessions not counted as agent sessions

    for i, r in enumerate(rows):
        ts = tss[i]
        # --- sessions
        if "surface" not in r or "session" not in r:
            skipped["rows lacking the surface/session fields (before they existed): "
                    "cannot be sessions"] += 1
        elif r["surface"] == "mcp":
            s = r["session"]
            client = (r.get("versions") or {}).get("client_name")
            if s is None:
                skipped["mcp rows with a null session id: cannot be sessions"] += 1
            elif agents is None:
                skipped["mcp rows when the manifest declares no agent_clients: "
                        "cannot tell agent sessions, so none count"] += 1
                non_agent_sessions["agent_clients not declared"].add(s)
            elif "versions" not in r:
                skipped["mcp rows without a versions field (before it existed): "
                        "client unknown, not counted as agent sessions"] += 1
                non_agent_sessions["client unknown (no versions field)"].add(s)
            elif client not in agents:
                skipped["mcp rows from a client not declared as an agent: not agent "
                        "sessions"] += 1
                non_agent_sessions["client %s not declared as an agent" % client].add(s)
            else:
                if s not in sessions_first or ts < sessions_first[s]:
                    sessions_first[s] = ts
                if win[i] is None:
                    unplaced_sessions.add(s)
                else:
                    placed_sessions.add(s)
                    window_sessions[win[i]].add(s)
                    lo, hi = window_span.get(win[i], (ts, ts))
                    window_span[win[i]] = (min(lo, ts), max(hi, ts))
        # --- refusal observations
        if r["decision"] != "refused":
            continue
        if "refusal_class" not in r:
            skipped["refused rows lacking refusal_class (before it existed): "
                    "cannot be observations"] += 1
            continue
        if r["refusal_class"] != "policy":
            skipped["refused rows with refusal_class %s: not policy refusals"
                    % (r["refusal_class"] if r["refusal_class"] is not None else "null")] += 1
            continue
        if r["op"] == "attest":
            skipped["policy refusals of op=attest: excluded by definition"] += 1
            continue
        if "session" not in r:
            skipped["policy refusals lacking the session field: cannot be observations"] += 1
            continue
        if r["session"] is None:
            # The definition: a refusal is "logged with its session". A null session cannot
            # be placed in any session, so the row is not an observation.
            skipped["policy refusals with a null session: not logged with a session"] += 1
            continue
        client = (r.get("versions") or {}).get("client_name")
        if agents is None or "versions" not in r or client not in agents:
            skipped["policy refusals outside an agent session (client not declared as an "
                    "agent, or unknown): not observations"] += 1
            continue
        if not src["logs_refusals"]:
            skipped["policy refusals from a guard the manifest says does not log "
                    "refusals"] += 1
            continue
        obs.append({"pattern": refusal_pattern(rule, r["op"], r.get("args")),
                    "entry_point": src["entry_point"], "session": r["session"],
                    "evidence": ts, "occurrence_known": True, "source": "refusal",
                    "window": win[i], "incident": None})

    for e in reg["entries"]:
        known = e["observed_at"] is not None
        obs.append({"pattern": e["pattern_id"], "entry_point": e["entry_point"],
                    "session": e["session"],
                    "evidence": e["observed_at"] if known else e["detected_at"],
                    "occurrence_known": known, "source": "incident", "window": None,
                    "incident": e})

    # as_of: the latest timestamp anywhere in the inputs, so the report is reproducible.
    if as_of is None:
        cands = list(tss)
        for e in reg["entries"]:
            cands += [t for t in (e["observed_at"], e["detected_at"], e["guarded_at"]) if t]
        as_of = max(cands)

    report = {
        "metric": "Incident-Driven Guard Coverage",
        "rule": rule,
        "as_of": _iso(as_of),
        "inputs": {"audit_rows": len(rows), "register_entries": len(reg["entries"]),
                   "manifest_guards": len(guards), "audit_guard": audit_guard,
                   "policy_refusal_observations": sum(1 for o in obs if o["source"] == "refusal"),
                   "incident_observations": len(reg["entries"]),
                   "agent_sessions": len(sessions_first),
                   "agent_clients": None if agents is None else sorted(agents),
                   "sessions_not_counted": [{"count": len(v), "reason": k}
                                            for k, v in sorted(non_agent_sessions.items())]},
        "skipped": [{"count": c, "reason": k} for k, c in sorted(skipped.items())],
        "caveats": _caveats(guards),
    }
    report["item1"], report["item2"] = _items_1_2(obs, guards, as_of)
    report["item3"] = _item3(obs, sessions_first, batch_size)
    report["item4"] = _item4(obs, window_sessions, window_span, win_skips, unplaced_sessions,
                             placed_sessions, window_source, min_sessions)
    return report


def _caveats(guards):
    out = []
    for g in guards:
        if not g["logs_refusals"]:
            out.append("guard %s (%s) does not log refusals: it contributes no refusal "
                       "observations" % (g["id"], g["entry_point"]))
        if g["version"] is None or g["version_at"] is None:
            out.append("guard %s has no declared %s: version windows cannot see its changes"
                       % (g["id"], "version" if g["version"] is None else "version_at"))
    return out


# --------------------------------------------------------------------- items 1 and 2
def _guard_at_entry(pattern, ep, incidents, guards):
    """Is `pattern` guarded with a replaying regression test at entry point `ep`?
    Returns (guarded_at or None, [reasons why not])."""
    here = [(g, g["patterns"][pattern]) for g in guards
            if g["entry_point"] == ep and pattern in g["patterns"]]
    tested = [(g, rec) for g, rec in here if rec is not None]
    reasons = []
    if not here:
        reasons.append("no regression test declared for it at %s" % ep)
    if not tested:
        for g, _ in here:
            reasons.append("guard %s at %s has no regression test replaying it" % (g["id"], ep))
    for inc in incidents:
        if inc["status"] != "guarded":
            reasons.append("%s is %s in the register" % (inc["id"], inc["status"]))
            continue
        if not any(rec["guard_commit"] == inc["guard_commit"] for _, rec in tested):
            elsewhere = [(g["id"], g["entry_point"]) for g in guards
                         for p, rec in g["patterns"].items()
                         if p == pattern and rec and rec["guard_commit"] == inc["guard_commit"]
                         and g["entry_point"] != ep]
            if elsewhere:
                reasons.append("%s's recorded guard %s is %s's, at %s, not at %s"
                               % (inc["id"], inc["guard_commit"][:7], elsewhere[0][0],
                                  elsewhere[0][1], ep))
            else:
                reasons.append("%s's recorded guard %s matches no tested guard at %s"
                               % (inc["id"], inc["guard_commit"][:7], ep))
    if reasons or not tested:
        return None, _dedupe(reasons)
    if incidents:
        return min(inc["guarded_at"] for inc in incidents), []
    return min(rec["guarded_at"] for _, rec in tested), []


def _dedupe(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _items_1_2(obs, guards, as_of):
    pats = defaultdict(list)
    for o in obs:
        pats[o["pattern"]].append(o)
    rows, ttg = [], []
    for p in sorted(pats):
        os_ = pats[p]
        first = min(o["evidence"] for o in os_)
        known = all(o["occurrence_known"] for o in os_)
        eps = sorted({o["entry_point"] for o in os_})
        times, reasons = [], []
        for ep in eps:
            incs = [o["incident"] for o in os_ if o["incident"] and o["entry_point"] == ep]
            at, why = _guard_at_entry(p, ep, incs, guards)
            times.append(at)
            reasons += why
        in_g = all(t is not None for t in times)
        row = {"pattern_id": p, "entry_points": eps, "first_evidence": _iso(first),
               "occurrence_known": known, "in_G": in_g}
        if in_g:
            v = time_to_guard(first, known, max(times))
            # e.g. a defect found while building the fix's own test harness: detection and
            # guard coincide, so the 0 says nothing about how fast a guard followed harm.
            at_fix = any(o["incident"] is not None and o["incident"]["observed_at"] is None
                         and o["evidence"] == first
                         and o["incident"]["detected_at"] == o["incident"]["guarded_at"]
                         for o in os_)
            v.update(pattern_id=p, guarded_at=_iso(max(times)), days=_days(v["seconds"]),
                     measured_from="occurrence" if known else "detection",
                     detected_at_fix_time=at_fix)
            ttg.append(v)
        else:
            row["age_days"] = _days((as_of - first).total_seconds())
            row["age_is_lower_bound"] = not known
            row["why_not_in_G"] = reasons
        rows.append(row)
    k, g = len(rows), sum(1 for r in rows if r["in_G"])
    item1 = {"K": k, "G": g, "share": (g / k) if k else None,
             "withheld": None if k else "K = 0: no pattern has been observed",
             "patterns": rows,
             "unguarded": [r["pattern_id"] for r in rows if not r["in_G"]]}
    med = median_of_exact(ttg)
    item2 = {"values": sorted(ttg, key=lambda v: v["pattern_id"]),
             "median_days": _days(med["median_seconds"]), "median_of": med["median_of"],
             "withheld": med["withheld"]}
    return item1, item2


# --------------------------------------------------------------------- item 3
def _item3(obs, sessions_first, batch_size):
    first_by_pattern = {}
    for o in obs:
        t = first_by_pattern.get(o["pattern"])
        if t is None or o["evidence"] < t:
            first_by_pattern[o["pattern"]] = o["evidence"]
    order = sorted(sessions_first.items(), key=lambda kv: (kv[1], kv[0]))
    starts = [order[i][1] for i in range(0, len(order), batch_size)]
    batches = []
    for b, start in enumerate(starts):
        size = min(batch_size, len(order) - b * batch_size)
        batches.append({"batch": b + 1, "sessions": size, "start": _iso(start),
                        "partial": size < batch_size, "new_patterns": 0})
    before = 0
    for p, t in first_by_pattern.items():
        k = bisect_right(starts, t)
        if k == 0:
            before += 1
        else:
            batches[k - 1]["new_patterns"] += 1
    return {"batch_size": batch_size, "sessions": len(order),
            "before_first_session": before, "batches": batches,
            "note": "a pattern is placed by its first evidence time (occurrence if known, "
                    "else detection) into the batch whose session interval contains it"}


# --------------------------------------------------------------------- item 4
def _item4(obs, window_sessions, window_span, win_skips, unplaced_sessions, placed_sessions,
           window_source, min_sessions):
    per = defaultdict(lambda: defaultdict(set))      # window -> pattern -> sessions
    excluded = Counter()
    for o in obs:
        if o["session"] is None:
            excluded["%s observation(s) with no known session" % o["source"]] += 1
            continue
        if o["source"] == "refusal":
            w = o["window"]
            if w is None or o["session"] not in window_sessions.get(w, ()):
                excluded["refusal observation(s) whose session is in no window"] += 1
                continue
            per[w][o["pattern"]].add(o["session"])
        else:
            # A session can span windows (its versions changed mid-connection). The incident
            # belongs to exactly ONE: the latest of its session's windows that had started by
            # the incident's time -- never to a window that ended before it happened.
            homes = [w for w, ss in window_sessions.items() if o["session"] in ss]
            if not homes:
                excluded["incident observation(s) whose session is in no window"] += 1
                continue
            started = [w for w in homes if window_span[w][0] <= o["evidence"]]
            if not started:
                excluded["incident observation(s) dated before their session's windows"] += 1
                continue
            w = max(started, key=lambda x: (window_span[x][0], str(x)))
            per[w][o["pattern"]].add(o["session"])
    order = sorted(window_sessions, key=lambda w: (window_span[w][0], str(w)))
    windows = []
    for idx, w in enumerate(order, 1):
        res = unseen_estimate({p: len(s) for p, s in per[w].items()}, len(window_sessions[w]),
                           min_sessions)
        res.update(window="W%d" % idx, start=_iso(window_span[w][0]),
                   end=_iso(window_span[w][1]))
        windows.append(res)
    current = max(windows, key=lambda x: x["end"]) if windows else None
    out = {"window_source": window_source, "min_sessions": min_sessions,
           "windows": windows, "current": current,
           "observations_excluded": [{"count": c, "reason": k}
                                     for k, c in sorted(excluded.items())],
           "sessions_in_no_window": len(unplaced_sessions - placed_sessions),
           "rows_not_placed_in_a_window": dict(sorted(win_skips.items()))}
    if current is None:
        out["withheld"] = ("no window contains a session: n = 0, Q1 = 0, Q2 = 0; U_hat needs "
                           "n >= %d" % min_sessions)
    return out
