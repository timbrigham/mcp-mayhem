"""Plain-text rendering of a measure() report. Deterministic: same report, same bytes."""

from __future__ import annotations


def _pct(x):
    return "%.1f%%" % (100.0 * x)


def render(report: dict) -> str:
    L = []
    a = L.append
    a("Incident-Driven Guard Coverage (rule %s), as of %s; unit: %s"
      % (report["rule"], report["as_of"], report["unit"]))
    i = report["inputs"]
    a("inputs: %d audit rows, %d call rows, %d instance-map entries, %d register entries, "
      "%d declared guards"
      % (i["audit_rows"], i["call_rows"], i["instance_map_entries"], i["register_entries"],
         i["manifest_guards"]))
    a("observations: %d policy refusals, %d incidents; %d agent instances (in %d agent "
      "sessions, context only)"
      % (i["policy_refusal_observations"], i["incident_observations"], i["agent_instances"],
         i["agent_sessions"]))
    if report["skipped"]:
        a("skipped rows:")
        for s in report["skipped"]:
            a("  %6d  %s" % (s["count"], s["reason"]))
    a("agent clients declared: %s; instances from: %s"
      % (", ".join(i["agent_clients"]) if i["agent_clients"] else "none (no row is an agent's)",
         i["instance_client"] or "nothing declared (no row has an instance)"))
    if i["agent_rows_without_instance"]:
        a("agent rows not placed in an instance:")
        for s in i["agent_rows_without_instance"]:
            a("  %6d  %s" % (s["count"], s["reason"]))
    if i["sessions_not_counted"]:
        a("sessions not counted as agent sessions:")
        for s in i["sessions_not_counted"]:
            a("  %6d  %s" % (s["count"], s["reason"]))
    for c in report["caveats"]:
        a("caveat: %s" % c)

    one = report["item1"]
    a("")
    if one["share"] is None:
        a("1. guarded share: withheld (%s)" % one["withheld"])
    else:
        a("1. guarded share |G|/|K| = %d/%d = %s" % (one["G"], one["K"], _pct(one["share"])))
    for p in one["patterns"]:
        if p["in_G"]:
            a("   in G       %s  (%s)" % (p["pattern_id"], ", ".join(p["entry_points"])))
    for p in one["patterns"]:
        if not p["in_G"]:
            a("   unguarded  %s  (%s), age %s%.2f days"
              % (p["pattern_id"], ", ".join(p["entry_points"]),
                 ">= " if p["age_is_lower_bound"] else "", p["age_days"]))
            for why in p["why_not_in_G"]:
                a("              - %s" % why)

    two = report["item2"]
    a("")
    a("2. time to guard (first occurrence to the commit with guard and test in place)")
    for v in two["values"]:
        if v["guarded_before_first_observation"]:
            a("   %s: guarded before first observation (%.2f days earlier); not a time to "
              "guard, excluded from the median" % (v["pattern_id"], -v["days"]))
            continue
        flags = []
        if v["lower_bound"]:
            flags.append("lower bound: measured from detection")
        if v["detected_at_fix_time"]:
            flags.append("detected at fix time")
        a("   %s: %s%.2f days%s" % (v["pattern_id"], ">= " if v["lower_bound"] else "",
                                    v["days"], "  [%s]" % "; ".join(flags) if flags else ""))
    if two["median_days"] is None:
        a("   median: withheld (%s)" % two["withheld"])
    else:
        a("   median: %.2f days over %d exact value(s); lower bounds and guards before first "
          "observation excluded" % (two["median_days"], two["median_of"]))

    three = report["item3"]
    a("")
    a("3. discovery trend: new patterns per batch of %d agent instances (%d instances)"
      % (three["batch_size"], three["instances"]))
    a("   before the first logged instance: %d" % three["before_first_instance"])
    for b in three["batches"]:
        a("   batch %d (%d instances%s, from %s): %d new"
          % (b["batch"], b["instances"], ", partial" if b["partial"] else "", b["start"],
             b["new_patterns"]))

    four = report["item4"]
    a("")
    a("4. unseen-pattern estimate U_hat = Q1/n (windows %s)" % four["window_source"])
    if four["current"] is None:
        a("   %s" % four["withheld"])
    for w in four["windows"]:
        head = "   %s %s .. %s: n=%d Q1=%d Q2=%d" % (w["window"], w["start"], w["end"], w["n"],
                                                    w["Q1"], w["Q2"])
        if w["U_hat"] is None:
            a(head + "; U_hat withheld (%s)" % w["withheld"])
        else:
            a(head + "; U_hat = Q1/n = %.4f" % w["U_hat"])
    a("   instances in no window: %d" % four["instances_in_no_window"])
    for k, c in four["rows_not_placed_in_a_window"].items():
        a("   rows not placed in a window (%s): %d" % (k, c))
    for e in four["observations_excluded"]:
        a("   excluded from item 4: %d %s" % (e["count"], e["reason"]))
    return "\n".join(L) + "\n"
