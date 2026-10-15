"""CLI exit codes, the public fixture, redaction, the synthetic replay and the README."""

import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from guard_coverage import measure, synthetic
from guard_coverage.cli import main
from guard_coverage.inputs import load_audit, load_calls, load_instance_map, load_json

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "guard-coverage"
FIX = EX / "fixture"
ARGS = ["measure", "--audit", str(FIX / "audit.jsonl"), "--calls", str(FIX / "calls.jsonl"),
        "--instances", str(FIX / "instances.json"), "--register",
        str(FIX / "register.json"), "--manifest", str(FIX / "manifest.json")]


def run_cli(args):
    p = subprocess.run([sys.executable, "-m", "guard_coverage"] + args, cwd=ROOT,
                       capture_output=True)
    return p.returncode, p.stdout.decode("utf-8").replace("\r\n", "\n")


# ------------------------------------------------------------------ CLI
def test_cli_measures_fixture_exit_0(capsys):
    assert main(ARGS) == 0
    assert "guarded share" in capsys.readouterr().out


def test_cli_json(capsys):
    assert main(ARGS + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["item1"]["K"] == 4


def test_cli_missing_input_exit_2(tmp_path):
    a = list(ARGS)
    a[2] = str(tmp_path / "missing.jsonl")
    assert main(a) == 2


def test_cli_unknown_rule_exit_2():
    assert main(ARGS + ["--rule", "9"]) == 2


def test_cli_invalid_json_exit_2(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_bytes(b"{not json")
    a = list(ARGS)
    a[a.index("--register") + 1] = str(bad)
    assert main(a) == 2


def test_cli_needs_an_instance_source_exit_64():
    a = [x for x in ARGS]
    i = a.index("--instances")
    del a[i:i + 2]
    with pytest.raises(SystemExit) as e:
        main(a)
    assert e.value.code == 64


def test_cli_usage_error_exit_64():
    with pytest.raises(SystemExit) as e:
        main(["measure", "--audit", "x"])
    assert e.value.code == 64


# ------------------------------------------------------------------ fixture
def test_checksums_match():
    lines = (FIX / "CHECKSUMS.sha256").read_bytes().decode("utf-8").splitlines()
    assert len(lines) == 7
    for line in lines:
        digest, name = line.split("  ")
        assert hashlib.sha256((FIX / name).read_bytes()).hexdigest() == digest, name


def test_fixture_reproduces_documented_numbers():
    rep = fixture_report()
    expected = json.loads((FIX / "expected_report.json").read_bytes().decode("utf-8"))
    assert rep == expected
    # the documented numbers, stated outright so a regenerated fixture cannot drift silently.
    # 4/4: gitrobot.worktree-target.any joined K (a policy refusal, 2026-10-14) already in G.
    assert (rep["item1"]["K"], rep["item1"]["G"]) == (4, 4)
    assert rep["item1"]["unguarded"] == []
    assert rep["inputs"]["policy_refusal_observations"] == 1
    v = {x["pattern_id"]: x for x in rep["item2"]["values"]}
    assert v["gitrobot.worktree-target.any"]["guarded_before_first_observation"]
    assert all(x["lower_bound"] for p, x in v.items() if p != "gitrobot.worktree-target.any")
    assert rep["item2"]["median_days"] is None
    # item 4 reports once the unit is an agent instance: one window, n = 301 >= 100
    assert rep["unit"] == "agent instance"
    # 404 instances for item 3; the 103 seen only before version fields are in no window
    assert rep["inputs"]["agent_instances"] == 404
    assert rep["item4"]["instances_in_no_window"] == 103
    w = rep["item4"]["windows"]
    assert [(x["n"], x["Q1"], x["Q2"]) for x in w] == [(301, 1, 0)]
    assert w[0]["U_hat"] == pytest.approx(1 / 301)


def fixture_report():
    imap, ambiguous = load_instance_map(FIX / "instances.json")
    return measure(load_audit(FIX / "audit.jsonl"), load_json(FIX / "register.json", "r"),
                   load_json(FIX / "manifest.json", "m"),
                   calls=load_calls([FIX / "calls.jsonl"]),
                   instance_map=imap, ambiguous_ids=ambiguous)


def test_readme_prose_numbers_match_the_fixture():
    """The figures the README states in prose, checked against the run, so prose cannot drift
    from the output block above it. Whitespace is normalised: line wrapping is not content."""
    text = " ".join((EX / "README.md").read_bytes().decode("utf-8").split())
    rep = fixture_report()
    w = rep["item4"]["windows"][0]
    i = rep["inputs"]
    no_inst = {x["reason"].split(" rows ", 1)[1]: x["count"]
               for x in i["agent_rows_without_instance"]}
    unplaced_calls = sum(x["count"] for x in i["agent_rows_without_instance"]
                         if x["reason"].startswith("call rows"))
    for phrase in (
            "K is %d patterns" % rep["item1"]["K"],
            "one window of %d agent instances: Q1 = %d, Q2 = %d, Û = %.4f"
            % (w["n"], w["Q1"], w["Q2"], w["U_hat"]),
            "all %d instances in the version window" % w["n"],
            "All %d incidents lack an instance" % i["incident_observations"],
            "The report counts %d instances for item 3. %d of them"
            % (i["agent_instances"], rep["item4"]["instances_in_no_window"]),
            "%d calls are not placed in an instance" % unplaced_calls,
            "%d call ids appear in several subagent transcripts"
            % no_inst["whose call id is in several transcripts (a forked subagent's copy of "
                      "its parent's history): no instance"],
            "%d is in no transcript" % no_inst["whose call id is in no transcript: no instance"],
            "%d agent audit rows carry no call id" % no_inst["lacking client_call_id (before "
                                                            "it existed): no instance"]):
        assert phrase in text, phrase
    # figures computed from the fixture files rather than the report
    from datetime import datetime
    calls = load_calls([FIX / "calls.jsonl"])
    backfilled = sum(1 for c in calls if c.get("source") == "http_calls backfill")
    assert "%s of the %s call rows were recovered" % (format(backfilled, ","),
                                                      format(len(calls), ",")) in text
    lo = datetime.fromisoformat("2026-10-14T22:46:58+00:00")
    hi = datetime.fromisoformat("2026-10-15T10:32:14+00:00")
    gap = [r for r in load_audit(FIX / "audit.jsonl")
           if lo < datetime.fromisoformat(r["ts"]) < hi]
    agent = sum(1 for r in gap if (r.get("versions") or {}).get("client_name") == "claude-code")
    assert "The audit log has %d rows strictly between them, %d of them" % (len(gap), agent) in text


def test_fixture_has_no_crlf_or_bom():
    for f in FIX.iterdir():
        data = f.read_bytes()
        assert b"\r\n" not in data and not data.startswith(b"\xef\xbb\xbf"), f.name


def test_redaction():
    texts = {f.name: f.read_bytes().decode("utf-8") for f in FIX.iterdir()}
    assert len(texts) >= 8
    for name, t in texts.items():
        for frag in ("C:\\", "C:/", "\\\\", "Users", ".claude", "Workspace", ".lean",
                     "tools/verify", "ZeroParadox/", "harm", "notes"):
            assert frag not in t, (name, frag)
    # source fields that carry prose or paths must not survive into the extract
    for name in ("audit.jsonl", "calls.jsonl", "instances.json", "register.json"):
        for frag in ("\"detail\"", "\"reason\"", "\"paths\"", "\"repo\"", "\"head\"",
                     "\"branch\": \"i", "\"text\"", "toolu_", "subagents", "agent-a"):
            assert frag not in texts[name], (name, frag)
    # call rows: only these keys, and every id a 16-hex-digit hash
    calls = [json.loads(x) for x in texts["calls.jsonl"].splitlines()]
    assert len(calls) > 3000
    for c in calls:
        assert set(c) <= {"ts", "surface", "session", "client_call_id", "versions", "source"}, c
        assert c.get("source", "http_calls backfill") == "http_calls backfill"
        for k in ("session", "client_call_id"):
            assert c[k] is None or re.fullmatch(r"[0-9a-f]{16}", c[k]), c
    imap = json.loads(texts["instances.json"])["map"]
    assert len(imap) > 1000
    assert all(re.fullmatch(r"[0-9a-f]{16}", x) for kv in imap.items() for x in kv)
    amb = json.loads(texts["instances.json"])["ambiguous"]
    assert all(re.fullmatch(r"[0-9a-f]{16}", x) for x in amb) and not set(amb) & set(imap)
    # no raw session ids: hashed ids are 16 hex digits, raw MCP ids are 32
    audit = [json.loads(x) for x in texts["audit.jsonl"].splitlines()]
    assert len(audit) > 6000
    sess = {r["session"] for r in audit if r.get("session")}
    assert sess and all(re.fullmatch(r"[0-9a-f]{16}", s) for s in sess)
    # only the pattern feature survives in args
    for r in audit:
        assert set(r) <= {"ts", "op", "decision", "refusal_class", "surface", "session",
                          "client_call_id", "versions", "args"}
        if r.get("client_call_id"):
            assert re.fullmatch(r"[0-9a-f]{16}", r["client_call_id"]), r
        if "args" in r:
            assert r["decision"] == "refused" and r["op"] in ("read", "push")
            assert set(r["args"]) <= {"op", "branch"} and len(r["args"]) == 1
    reg = json.loads(texts["register.json"])["collections"]["incidents"]["entries"]
    assert len(reg) == 5
    for e in reg:
        assert set(e) <= {"id", "pattern_id", "status", "observed_at", "detected_at",
                          "guarded_at", "guard_commit", "has_regression_test", "tool",
                          "session_known", "session", "instance", "guard_history"}
        assert e["tool"] in ("agent-shell", "gitrobot-mcp/cli")
        assert isinstance(e["has_regression_test"], bool)
    assert "sha256:" not in texts["register.json"]


def test_redaction_scan_catches_harm_text():
    import make_fixture
    reg = {"collections": {"incidents": {"entries": [
        {"harm": "an agent wrote a secret file into the shared checkout", "notes": []}]}}}
    found = make_fixture.scan({"x": "... wrote a secret file into the shared ..."}, reg)
    assert found
    assert not make_fixture.scan({"x": "nothing here"}, reg)


# ------------------------------------------------------------------ synthetic
def test_synthetic_is_deterministic_for_a_seed():
    a = synthetic.run(3, 20)
    b = synthetic.run(3, 20)
    assert a == b and synthetic.render(a) == synthetic.render(b)
    assert synthetic.run(4, 20) != a


def test_synthetic_end_to_end_agrees_and_is_labelled():
    res = synthetic.run(11, 3)
    assert res["synthetic"] is True
    assert res["end_to_end_replicate_0"]["windows_agree"]
    assert res["end_to_end_replicate_0"]["time_to_guard_agree"]
    assert res["end_to_end_replicate_0"]["windows"] > 5
    text = synthetic.render(res)
    assert text.startswith("SYNTHETIC REPLAY")
    assert res["time_to_guard"]["exact"] > 0


# ------------------------------------------------------------------ README
def readme_blocks():
    text = (EX / "README.md").read_bytes().decode("utf-8")
    blocks = re.findall(r"```console\n\$ python3 -m guard_coverage (.*?)\n(.*?)```", text, re.S)
    assert len(blocks) == 2
    return blocks


def test_readme_scope_sentence():
    text = (EX / "README.md").read_bytes().decode("utf-8")
    assert ("This is a single-author proof of concept, built for and used in one dedicated "
            "environment. It demonstrates the measurement; it is not a production or "
            "complete tool.") in text


@pytest.mark.parametrize("i", [0, 1])
def test_readme_output_blocks_match_real_runs(i):
    cmd, documented = readme_blocks()[i]
    rc, out = run_cli(shlex.split(cmd))
    assert rc == 0
    want, got = documented.splitlines(), out.splitlines()
    assert len(want) > 10
    for n, (w, g) in enumerate(zip(want, got), 1):
        assert w == g, "line %d differs" % n
    assert len(want) == len(got)
