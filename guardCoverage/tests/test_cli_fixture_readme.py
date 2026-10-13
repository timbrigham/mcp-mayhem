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
from guard_coverage.inputs import load_audit, load_json

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "guard-coverage"
FIX = EX / "fixture"
ARGS = ["measure", "--audit", str(FIX / "audit.jsonl"), "--register",
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
    assert json.loads(capsys.readouterr().out)["item1"]["K"] == 3


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
    a[4] = str(bad)
    assert main(a) == 2


def test_cli_usage_error_exit_64():
    with pytest.raises(SystemExit) as e:
        main(["measure", "--audit", "x"])
    assert e.value.code == 64


# ------------------------------------------------------------------ fixture
def test_checksums_match():
    lines = (FIX / "CHECKSUMS.sha256").read_bytes().decode("utf-8").splitlines()
    assert len(lines) == 5
    for line in lines:
        digest, name = line.split("  ")
        assert hashlib.sha256((FIX / name).read_bytes()).hexdigest() == digest, name


def test_fixture_reproduces_documented_numbers():
    rep = measure(load_audit(FIX / "audit.jsonl"), load_json(FIX / "register.json", "r"),
                  load_json(FIX / "manifest.json", "m"))
    expected = json.loads((FIX / "expected_report.json").read_bytes().decode("utf-8"))
    assert rep == expected
    # the documented numbers, stated outright so a regenerated fixture cannot drift silently
    assert (rep["item1"]["K"], rep["item1"]["G"]) == (3, 2)
    assert rep["item1"]["unguarded"] == ["git.reset.work-destroying"]
    assert all(v["lower_bound"] for v in rep["item2"]["values"])
    assert rep["item2"]["median_days"] is None
    assert rep["inputs"]["policy_refusal_observations"] == 0
    assert rep["item4"]["current"] is None and "n = 0" in rep["item4"]["withheld"]


def test_fixture_has_no_crlf_or_bom():
    for f in FIX.iterdir():
        data = f.read_bytes()
        assert b"\r\n" not in data and not data.startswith(b"\xef\xbb\xbf"), f.name


def test_redaction():
    texts = {f.name: f.read_bytes().decode("utf-8") for f in FIX.iterdir()}
    assert len(texts) >= 6
    for name, t in texts.items():
        for frag in ("C:\\", "C:/", "\\\\", "Users", ".claude", "Workspace", ".lean",
                     "tools/verify", "ZeroParadox/", "harm", "notes"):
            assert frag not in t, (name, frag)
    # source fields that carry prose or paths must not survive into the extract
    for name in ("audit.jsonl", "register.json"):
        for frag in ("\"detail\"", "\"reason\"", "\"paths\"", "\"repo\"", "\"head\"",
                     "\"branch\": \"i", "\"text\""):
            assert frag not in texts[name], (name, frag)
    # no raw session ids: hashed ids are 16 hex digits, raw MCP ids are 32
    audit = [json.loads(x) for x in texts["audit.jsonl"].splitlines()]
    assert len(audit) > 6000
    sess = {r["session"] for r in audit if r.get("session")}
    assert sess and all(re.fullmatch(r"[0-9a-f]{16}", s) for s in sess)
    # only the pattern feature survives in args
    for r in audit:
        assert set(r) <= {"ts", "op", "decision", "refusal_class", "surface", "session",
                          "versions", "args"}
        if "args" in r:
            assert r["decision"] == "refused" and r["op"] in ("read", "push")
            assert set(r["args"]) <= {"op", "branch"} and len(r["args"]) == 1
    reg = json.loads(texts["register.json"])["collections"]["incidents"]["entries"]
    assert len(reg) == 5
    for e in reg:
        assert set(e) <= {"id", "pattern_id", "status", "observed_at", "detected_at",
                          "guarded_at", "guard_commit", "has_regression_test", "tool",
                          "session_known", "session", "guard_history"}
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
