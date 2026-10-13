"""Items 1-4 on small hand-built inputs."""

import pytest

from guard_coverage import measure
from guard_coverage.inputs import InputError
from guard_coverage.rule import UnknownRule
from helpers import (VERS, guard, incident, manifest, refusal, register, row, sessions)

GR = "gitrobot-mcp/cli"
SH = "agent-shell"
SHELL_TOOL = "PowerShell (agent shell, not gitRobot)"


def m(rows, reg=None, man=None, **kw):
    return measure(rows, reg or register(), man or manifest(), "1", **kw)


def patterns(rep):
    return {p["pattern_id"]: p for p in rep["item1"]["patterns"]}


# ------------------------------------------------------------------ observations
def test_policy_refusal_is_an_observation_with_rule_1_pattern():
    rep = m(sessions(3) + [refusal(5, sub="reset")])
    assert rep["item1"]["K"] == 1
    assert "gitrobot.read.reset" in patterns(rep)


def test_attest_policy_refusal_is_excluded_and_counted():
    rep = m(sessions(3) + [refusal(5, op="attest")])
    assert rep["item1"]["K"] == 0
    assert any("attest" in s["reason"] and s["count"] == 1 for s in rep["skipped"])


@pytest.mark.parametrize("cls", ["gate", "operational", "allowlist", None])
def test_non_policy_refusals_are_not_observations(cls):
    rep = m(sessions(3) + [refusal(5, cls=cls)])
    assert rep["item1"]["K"] == 0
    assert any("not policy" in s["reason"] for s in rep["skipped"])


def test_rows_lacking_fields_are_skipped_and_counted_not_treated_as_null():
    legacy_refused = row(1, "read", "refused", args={"op": "reset"}, legacy=True)
    legacy_allowed = row(2, legacy=True)
    rep = m([legacy_refused, legacy_allowed] + sessions(2, start=10))
    assert rep["item1"]["K"] == 0
    reasons = {s["reason"]: s["count"] for s in rep["skipped"]}
    assert reasons["refused rows lacking refusal_class (before it existed): "
                   "cannot be observations"] == 1
    assert reasons["rows lacking the surface/session fields (before they existed): "
                   "cannot be sessions"] == 2
    assert rep["inputs"]["mcp_sessions"] == 2


def test_policy_refusal_lacking_session_field_is_skipped():
    r = refusal(5)
    del r["session"]
    del r["surface"]
    rep = m(sessions(2) + [r])
    assert rep["item1"]["K"] == 0
    assert any("lacking the session field" in s["reason"] for s in rep["skipped"])


def test_refusals_from_a_guard_that_does_not_log_contribute_nothing():
    man = manifest(guard("gitrobot", GR, {}, logs=False, version_at=-1000))
    rep = m(sessions(2) + [refusal(5)], man=man)
    assert rep["item1"]["K"] == 0
    assert any("does not log refusals" in c for c in rep["caveats"])


def test_unknown_rule_is_refused():
    with pytest.raises(UnknownRule):
        measure(sessions(2), register(), manifest(), "2")


def test_register_under_another_rule_is_refused():
    with pytest.raises(InputError):
        measure(sessions(2), register(rule="2"), manifest(), "1")


def test_empty_audit_is_refused_not_measured_as_clean():
    with pytest.raises(InputError):
        measure([], register(), manifest(), "1")


# ------------------------------------------------------------------ item 1
def test_entry_point_mismatch_keeps_pattern_out_of_G():
    # The INC-0001 shape: happened in a shell; recorded guard is gitRobot's.
    inc = incident("I1", "git.reset.work-destroying", tool="git (direct, before gitRobot)",
                   commit="c77")
    man = manifest(guard("gitrobot", GR, {"git.reset.work-destroying": ("c77", 10)},
                         version_at=-1000),
                   guard("shellhook", SH, {"git.reset.work-destroying": None}))
    rep = m(sessions(2), register(inc), man)
    p = patterns(rep)["git.reset.work-destroying"]
    assert rep["item1"]["K"] == 1 and rep["item1"]["G"] == 0
    assert not p["in_G"]
    assert any("gitrobot's, at gitrobot-mcp/cli, not at agent-shell" in w
               for w in p["why_not_in_G"])
    assert any("shellhook at agent-shell has no regression test" in w
               for w in p["why_not_in_G"])
    assert p["age_is_lower_bound"] is True


def test_matching_entry_point_puts_pattern_in_G():
    inc = incident("I1", "p.x", tool=SHELL_TOOL, commit="cS", guarded=48)
    man = manifest(guard("shellhook", SH, {"p.x": ("cS", 48)}))
    rep = m(sessions(2), register(inc), man)
    assert rep["item1"]["G"] == 1 and rep["item1"]["share"] == 1.0


def test_open_incident_is_not_in_G_even_with_a_tested_guard():
    inc = incident("I1", "p.x", tool=SHELL_TOOL, status="open")
    man = manifest(guard("shellhook", SH, {"p.x": ("cS", 48)}))
    rep = m(sessions(2), register(inc), man)
    assert rep["item1"]["G"] == 0
    assert "I1 is open in the register" in patterns(rep)["p.x"]["why_not_in_G"]


def test_unknown_tool_is_refused_rather_than_guessed():
    inc = incident("I1", "p.x", tool="some new tool")
    with pytest.raises(InputError):
        m(sessions(2), register(inc))


def test_K_zero_withholds_share_with_reason():
    rep = m(sessions(2))
    assert rep["item1"]["share"] is None and "K = 0" in rep["item1"]["withheld"]


# ------------------------------------------------------------------ item 2
def test_time_to_guard_exact_and_median():
    a = incident("I1", "p.a", observed=0, detected=5, commit="ca", guarded=24)
    b = incident("I2", "p.b", observed=0, detected=5, commit="cb", guarded=72)
    man = manifest(guard("gitrobot", GR, {"p.a": ("ca", 24), "p.b": ("cb", 72)},
                         version_at=-1000))
    rep = m(sessions(2), register(a, b), man)
    vals = {v["pattern_id"]: v for v in rep["item2"]["values"]}
    assert vals["p.a"]["days"] == 1.0 and not vals["p.a"]["lower_bound"]
    assert rep["item2"]["median_days"] == 2.0 and rep["item2"]["median_of"] == 2


def test_lower_bound_is_flagged_and_excluded_from_median():
    a = incident("I1", "p.a", observed=0, commit="ca", guarded=24)
    b = incident("I2", "p.b", observed=None, detected=0, commit="cb", guarded=240)
    man = manifest(guard("gitrobot", GR, {"p.a": ("ca", 24), "p.b": ("cb", 240)},
                         version_at=-1000))
    rep = m(sessions(2), register(a, b), man)
    vals = {v["pattern_id"]: v for v in rep["item2"]["values"]}
    assert vals["p.b"]["lower_bound"] is True
    assert vals["p.b"]["measured_from"] == "detection"
    assert rep["item2"]["median_days"] == 1.0 and rep["item2"]["median_of"] == 1


def test_all_lower_bounds_give_null_median_with_reason():
    a = incident("I1", "p.a", detected=0, commit="ca", guarded=24)
    man = manifest(guard("gitrobot", GR, {"p.a": ("ca", 24)}, version_at=-1000))
    rep = m(sessions(2), register(a), man)
    assert rep["item2"]["median_days"] is None
    assert "every value (1) is a lower bound" in rep["item2"]["withheld"]


def test_refusal_pattern_time_to_guard_comes_from_manifest():
    man = manifest(guard("gitrobot", GR, {"gitrobot.read.reset": ("cr", 29)},
                         version_at=-1000))
    rep = m(sessions(2) + [refusal(5)], man=man)
    v = rep["item2"]["values"][0]
    assert v["days"] == 1.0 and v["lower_bound"] is False


# ------------------------------------------------------------------ item 3
def test_discovery_trend_batches():
    rows = sessions(25) + [refusal(3, session="s0003"), refusal(12, session="s0012", sub="push"),
                           refusal(13, session="s0013", sub="push")]
    rep = m(rows, batch_size=10)
    b = rep["item3"]["batches"]
    assert [x["sessions"] for x in b] == [10, 10, 5]
    assert [x["new_patterns"] for x in b] == [1, 1, 0]
    assert b[2]["partial"] is True
    assert rep["item3"]["before_first_session"] == 0


def test_incident_before_first_session_is_counted_before():
    inc = incident("I1", "p.a", detected=-100, commit="c")
    rep = m(sessions(3), register(inc))
    assert rep["item3"]["before_first_session"] == 1


# ------------------------------------------------------------------ item 4
def test_once_per_session_pattern():
    # the same pattern three times in one session, plus an incident in that session: Q1 = 1
    rows = sessions(5) + [refusal(1, session="s0001"), refusal(1.5, session="s0001"),
                          refusal(2, session="s0001")]
    inc = incident("I1", "gitrobot.read.reset", session="s0001", commit="c")
    rep = m(rows, register(inc))
    w = rep["item4"]["windows"][0]
    assert (w["n"], w["Q1"], w["Q2"]) == (5, 1, 0)


def test_pattern_in_two_sessions_is_Q2():
    rows = sessions(5) + [refusal(1, session="s0001"), refusal(2, session="s0002")]
    w = m(rows)["item4"]["windows"][0]
    assert (w["Q1"], w["Q2"]) == (0, 1)


def test_unknown_session_incident_counts_toward_K_and_G_but_not_item4():
    inc = incident("I1", "p.a", session=None, commit="ca", guarded=24)
    man = manifest(guard("gitrobot", GR, {"p.a": ("ca", 24)}, version_at=-1000))
    rep = m(sessions(120), register(inc), man)
    assert rep["item1"]["K"] == 1 and rep["item1"]["G"] == 1
    w = rep["item4"]["windows"][0]
    assert (w["n"], w["Q1"], w["Q2"]) == (120, 0, 0)
    assert any("no known session" in e["reason"] for e in rep["item4"]["observations_excluded"])


def test_known_session_incident_counts_in_item4():
    inc = incident("I1", "p.a", session="s0007", commit="ca", guarded=24)
    rep = m(sessions(120), register(inc))
    w = rep["item4"]["windows"][0]
    assert w["Q1"] == 1


def test_withheld_below_100_sessions_counting_empty_sessions():
    rows = sessions(99) + [refusal(1, session="s0001")]
    w = m(rows)["item4"]["windows"][0]
    assert w["n"] == 99 and w["U_hat"] is None and "n >= 100" in w["withheld"]
    assert (w["Q1"], w["Q2"]) == (1, 0)
    rows = sessions(100) + [refusal(1, session="s0001")]
    w = m(rows)["item4"]["windows"][0]
    assert w["n"] == 100 and w["U_hat"] == pytest.approx(0.01) and w["withheld"] is None


def test_window_restarts_on_gitrobot_commit_change():
    v2 = dict(VERS, gitrobot_commit="bbb")
    rows = sessions(3) + [row(10 + i, session="t%d" % i, versions=v2) for i in range(4)]
    ws = m(rows)["item4"]["windows"]
    assert [w["n"] for w in ws] == [3, 4]


def test_window_restarts_on_client_version_change():
    v2 = dict(VERS, client_version="2")
    rows = sessions(3) + [row(10 + i, session="t%d" % i, versions=v2) for i in range(4)]
    assert [w["n"] for w in m(rows)["item4"]["windows"]] == [3, 4]


def test_window_restarts_on_manifest_guard_version():
    man = manifest(guard("hook", SH, {}, version="h2", version_at=5))
    rows = sessions(10)
    assert [w["n"] for w in m(rows, man=man)["item4"]["windows"]] == [5, 5]


def test_window_restarts_even_when_a_server_version_returns():
    v2 = dict(VERS, gitrobot_commit="bbb")
    rows = (sessions(2) + [row(10, session="t0", versions=v2)]
            + [row(20 + i, session="u%d" % i) for i in range(3)])
    assert [w["n"] for w in m(rows)["item4"]["windows"]] == [2, 1, 3]


def test_rows_without_versions_are_not_windowed():
    rows = sessions(3, versions=None)
    rep = m(rows)
    assert rep["item4"]["windows"] == [] and rep["item4"]["sessions_in_no_window"] == 3
    assert "n = 0" in rep["item4"]["withheld"]


def test_null_gitrobot_commit_is_not_windowed():
    rows = sessions(3, versions=dict(VERS, gitrobot_commit=None))
    rep = m(rows)
    assert rep["item4"]["windows"] == []
    assert any("not run from a git checkout" in k
               for k in rep["item4"]["rows_not_placed_in_a_window"])


def test_explicit_windows_place_unversioned_sessions():
    from datetime import timedelta
    from helpers import T0
    rows = sessions(6, versions=None)
    rep = m(rows, boundaries=[T0, T0 + timedelta(hours=3)])
    assert [w["n"] for w in rep["item4"]["windows"]] == [3, 3]
