"""`evidence-currency`: in-scope subjects with a verdict at their CURRENT bytes, per step.

Requested 2026-10-09 for a NIST AI Metrology submission, which links this command as the code
that calculates the metric. The contract a reviewer will check:
  - current / stale / never_examined are reported SEPARATELY and partition in_scope;
  - an empty scope is NOT_APPLICABLE with currency null, never 100%, and is excluded from totals;
  - the total is over (step, subject) pairs and does not merge stale with never examined.
"""

import json
import subprocess
import sys
from pathlib import Path

from core.cli import evidence_currency

ROOT = Path(__file__).resolve().parents[1]


def _row(step, *, judged, covered, stale, scope=None, status="SATISFIED", unexamined=None):
    return {"step": step, "status": status, "judged": judged, "scope": judged if scope is None else scope,
            "subjects_covered": covered, "subjects_stale": stale,
            "subjects_unexamined": unexamined if unexamined is not None else judged - covered - stale}


def test_counts_partition_the_denominator_per_step():
    out = evidence_currency({"rows": [_row("a", judged=5, covered=2, stale=1)]})
    s = out["steps"][0]
    assert (s["in_scope"], s["current"], s["stale"], s["never_examined"]) == (5, 2, 1, 2)
    assert s["current"] + s["stale"] + s["never_examined"] == s["in_scope"]
    assert s["currency"] == 0.4


def test_an_empty_scope_is_not_applicable_never_100_percent():
    out = evidence_currency({"rows": [
        _row("none", judged=0, covered=0, stale=0, status="NOT_APPLICABLE"),
        _row("a", judged=4, covered=1, stale=0)]})
    na = next(s for s in out["steps"] if s["step"] == "none")
    assert na["status"] == "NOT_APPLICABLE" and na["currency"] is None
    assert out["not_applicable"] == ["none"]
    assert out["total"]["in_scope"] == 4, "a not-applicable step must not enter the totals"
    assert out["total"]["currency"] == 0.25


def test_nothing_applicable_gives_a_null_total_not_100_percent():
    out = evidence_currency({"rows": [_row("none", judged=0, covered=0, stale=0,
                                           status="NOT_APPLICABLE")]})
    assert out["total"]["currency"] is None and out["total"]["in_scope"] == 0


def test_stale_and_never_examined_stay_separate_in_the_total():
    out = evidence_currency({"rows": [_row("a", judged=3, covered=1, stale=2),
                                      _row("b", judged=4, covered=1, stale=0)]})
    t = out["total"]
    assert (t["in_scope"], t["current"], t["stale"], t["never_examined"]) == (7, 2, 2, 3)


def test_never_examined_is_derived_so_switch_files_are_not_lost():
    """The inventory row's own `subjects_unexamined` counts over scope only, while `judged` (the
    denominator) also includes switch files. Deriving never_examined keeps the partition exact."""
    row = _row("a", judged=6, covered=3, stale=1, scope=5, unexamined=1)   # 1 switch never examined
    s = evidence_currency({"rows": [row]})["steps"][0]
    assert s["in_scope"] == 6 and s["never_examined"] == 2


def test_the_shipped_example_runs_and_ends_at_the_documented_numbers():
    """The example a reviewer runs must keep producing what its README says."""
    r = subprocess.run([sys.executable, str(ROOT / "examples" / "evidence-currency" / "run_example.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    tail = r.stdout[r.stdout.index("machine-readable form"):]
    doc = json.loads(tail[tail.index("{"): tail.rindex("}") + 1])
    t = doc["total"]
    assert (t["in_scope"], t["current"], t["stale"], t["never_examined"]) == (5, 4, 0, 1)
    assert doc["not_applicable"] == ["changelog_review"]
    assert "2. after editing docs/usage.md" in r.stdout
    stage2 = r.stdout.split("=== 2.")[1].split("=== 3.")[0]
    assert "spelling                        2        1        1" in stage2, stage2


def _cli(tmp_path, *args, data=None):
    import os
    env = dict(os.environ, ZPLOG_ENABLED="0")
    env.pop("ZPLEDGER_DATA", None)
    cfg = ROOT / "examples" / "evidence-currency" / "config"
    env["ZPLEDGER_POLICY"] = str(cfg / "policy.example.json")
    env["ZPLEDGER_REQUIRED"] = str(cfg / "required.example.json")
    repo = tmp_path / "repo"
    if not repo.exists():
        repo.mkdir()
        for a in (["init", "-q"], ["-c", "user.email=e@e.invalid", "-c", "user.name=e",
                                   "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    pre = ["--repo", str(repo)] + (["--data", str(data)] if data else [])
    return subprocess.run([sys.executable, "-m", "core.cli", *pre, "evidence-currency", *args],
                          cwd=ROOT, env=env, capture_output=True, text=True)


def test_a_missing_stream_is_refused_not_measured_as_zero(tmp_path):
    """Unguarded, an unset ZPLEDGER_DATA read the default stream and printed 0.0% with exit 0."""
    r = _cli(tmp_path, "--ref", "HEAD")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "no verdict stream" in r.stderr and "%" not in r.stdout
    r = _cli(tmp_path, "--ref", "HEAD", data=tmp_path / "absent.jsonl")
    assert r.returncode == 2 and "no verdict stream" in r.stderr


def test_an_unresolvable_ref_is_refused_not_reported_as_not_applicable(tmp_path):
    """Unguarded, `--ref doesnotexist` printed every step n/a with exit 0."""
    data = tmp_path / "records.jsonl"
    data.write_bytes(b"")
    r = _cli(tmp_path, "--ref", "doesnotexist", data=data)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "does not resolve" in r.stderr and "n/a" not in r.stdout
    ok = _cli(tmp_path, "--ref", "HEAD", data=data)       # the control: same setup, real ref
    assert ok.returncode == 0, ok.stderr
    assert "TOTAL" in ok.stdout