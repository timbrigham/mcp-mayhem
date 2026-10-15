"""Fixes from the adversarial review: null-session refusals, guards before first observation,
reason wording, detected-at-fix-time, version_history, the boolean test flag in the public
extract, and the synthetic recording rule."""

import random

import pytest

from guard_coverage import synthetic
from helpers import measure
from guard_coverage.inputs import InputError
from helpers import guard, incident, manifest, refusal, register, sessions, ts

GR = "gitrobot-mcp/cli"
SH = "agent-shell"
SHELL_TOOL = "PowerShell (agent shell, not gitRobot)"


def m(rows, reg=None, man=None, **kw):
    return measure(rows, reg or register(), man or manifest(), "1", **kw)


def test_refusal_with_null_session_is_skipped_not_observed():
    rep = m(sessions(2) + [refusal(5, session=None)])
    assert rep["item1"]["K"] == 0
    assert any("null session" in s["reason"] and s["count"] == 1 for s in rep["skipped"])


def test_guard_before_first_observation_is_flagged_and_out_of_median():
    man = manifest(guard("gitrobot", GR, {"gitrobot.read.reset": ("cr", 1),
                                          "gitrobot.read.push": ("cp", 29)}, version_at=-1000))
    rep = m(sessions(2) + [refusal(5), refusal(5, sub="push")], man=man)
    vals = {v["pattern_id"]: v for v in rep["item2"]["values"]}
    v = vals["gitrobot.read.reset"]
    assert v["guarded_before_first_observation"] is True and v["seconds"] < 0
    assert vals["gitrobot.read.push"]["guarded_before_first_observation"] is False
    assert rep["item2"]["median_days"] == 1.0 and rep["item2"]["median_of"] == 1


def test_only_guarded_before_first_observation_withholds_median():
    man = manifest(guard("gitrobot", GR, {"gitrobot.read.reset": ("cr", 1)}, version_at=-1000))
    rep = m(sessions(2) + [refusal(5)], man=man)
    assert rep["item2"]["median_days"] is None and rep["item2"]["withheld"]


def test_refused_pattern_without_declared_test_says_so():
    rep = m(sessions(2) + [refusal(5)])
    why = rep["item1"]["patterns"][0]["why_not_in_G"]
    assert why == ["no regression test declared for it at gitrobot-mcp/cli"]


def test_detected_at_fix_time_is_flagged():
    man = manifest(guard("gitrobot", GR, {"p.a": ("ca", 24)}, version_at=-1000))
    inc = incident("I1", "p.a", detected=24, commit="ca", guarded=24)
    v = m(sessions(2), register(inc), man)["item2"]["values"][0]
    assert v["detected_at_fix_time"] is True and v["days"] == 0.0
    inc = incident("I1", "p.a", detected=0, commit="ca", guarded=24)
    v = m(sessions(2), register(inc), man)["item2"]["values"][0]
    assert v["detected_at_fix_time"] is False


def test_version_history_restarts_windows_at_each_dated_version():
    g = guard("hook", SH, {}, version="h3", version_at=6)
    g["version_history"] = [{"version": "h1", "version_at": ts(-50)},
                            {"version": "h2", "version_at": ts(3)}]
    rep = m(sessions(10), man=manifest(g))
    assert [w["n"] for w in rep["item4"]["windows"]] == [3, 3, 4]


def test_register_extract_with_boolean_test_flag():
    man = manifest(guard("shellhook", SH, {"p.x": ("cS", 48)}))
    inc = incident("I1", "p.x", tool=SHELL_TOOL, commit="cS", guarded=48)
    del inc["regression_test"]
    inc["has_regression_test"] = True
    assert m(sessions(2), register(inc), man)["item1"]["G"] == 1
    inc["has_regression_test"] = False
    with pytest.raises(InputError):
        m(sessions(2), register(inc), man)


def test_synthetic_recording_rule():
    sim = synthetic.simulate(random.Random("rule"), r_record=0.3, p_logs=0.5)
    for k in range(synthetic.N_PATTERNS):
        g = sim["guard_at"][k]
        # incidents only before the guard; refusals only after a LOGGING guard
        assert all(g is None or t < g for t, _, _ in sim["incidents"][k])
        if sim["refusals"][k]:
            assert g is not None and sim["logs"][k] and min(sim["refusals"][k]) >= g
        if g is not None and not sim["logs"][k]:
            assert sim["refusals"][k] == []
    assert sum(len(x) for x in sim["refusals"]) > 0
    assert sum(1 for k in range(synthetic.N_PATTERNS)
               if sim["guard_at"][k] is not None and not sim["logs"][k]) > 0
    none = synthetic.simulate(random.Random("rule"), r_record=0.0, p_logs=1.0)
    assert all(not x for x in none["incidents"]) and all(g is None for g in none["guard_at"])


def test_synthetic_recording_probability_is_applied():
    def n_inc(r):
        return sum(len(x) for x in synthetic.simulate(random.Random("p"), r_record=r)["incidents"])
    assert n_inc(0.9) > n_inc(0.1) > 0


def test_synthetic_reports_both_targets_with_intervals():
    res = synthetic.run(5, 30)
    for key in ("U_n_in_window", "never_observed"):
        g = res["targets"][key]
        assert g["coverage_ci95"][0] <= g["coverage"] <= g["coverage_ci95"][1]
        assert g["bias_ci95"][0] <= g["bias"] <= g["bias_ci95"][1]
        assert g["rmse"] >= abs(g["bias"])
        assert g["windows_truth_positive"] > 0
    assert res["end_to_end_replicate_0"]["windows_agree"]
    assert res["end_to_end_replicate_0"]["time_to_guard_agree"]
    assert res["end_to_end_replicate_0"]["incidents"] > 0


def test_incident_is_placed_in_the_window_containing_its_time():
    # One session spans two windows (gitRobot restarted mid-connection). The incident
    # happened in the SECOND window; it must not be counted in the first.
    from helpers import VERS, row
    v2 = dict(VERS, gitrobot_commit="bbb")
    rows = ([row(i, session="a%d" % i) for i in range(3)] + [row(3, session="s")]
            + [row(10, session="s", versions=v2)]
            + [row(11 + i, session="b%d" % i, versions=v2) for i in range(3)])
    inc = incident("I1", "p.a", session="s", observed=12, detected=12, commit="c", guarded=20)
    ws = m(rows, register(inc))["item4"]["windows"]
    assert [w["n"] for w in ws] == [4, 4]
    assert [w["Q1"] for w in ws] == [0, 1]
    inc = incident("I1", "p.a", session="s", observed=2, detected=2, commit="c", guarded=20)
    ws = m(rows, register(inc))["item4"]["windows"]
    assert [w["Q1"] for w in ws] == [1, 0]
