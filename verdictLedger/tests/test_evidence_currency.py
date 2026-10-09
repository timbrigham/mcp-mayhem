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


# The numbers each stage of the shipped example must print. The README states them, and an external
# specification quotes the safety_eval figures, so a change here is a change to a published claim.
#                stage  (in_scope, current, stale, never_examined, currency)
EXAMPLE_STAGES = {"1": (4, 4, 0, 0, "100.0%"),
                  "2": (4, 3, 1, 0, "75.0%"),
                  "3": (5, 3, 1, 1, "60.0%"),
                  "4": (5, 5, 0, 0, "100.0%")}


def _run_example():
    r = subprocess.run([sys.executable, str(ROOT / "examples" / "evidence-currency" / "run_example.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return r.stdout


def test_the_shipped_example_prints_the_documented_numbers_at_every_stage():
    """The example a reviewer runs must keep producing what its README says, stage by stage."""
    out = _run_example()
    stages = out.split("=== Stage ")[1:]
    assert len(stages) == len(EXAMPLE_STAGES), "a stage vanished, so its numbers were never checked"
    for chunk in stages:
        n = chunk[0]
        row = next(l for l in chunk.splitlines() if l.startswith("safety_eval "))
        total = next(l for l in chunk.splitlines() if l.startswith("TOTAL"))
        want = [str(x) for x in EXAMPLE_STAGES[n]]
        assert row.split()[1:] == want, (n, row)
        assert total.split()[3:] == want, (n, total)
        assert "model_card_review (empty scope)" in chunk, (n, chunk)
    stage3 = stages[2]
    assert "pass-only view of the same records: 4 of 4 recorded results PASS" in stage3
    tail = out[out.index("machine-readable form"):]
    doc = json.loads(tail[tail.index("{"): tail.rindex("}") + 1])
    assert doc["not_applicable"] == ["model_card_review"]
    na = next(s for s in doc["steps"] if s["step"] == "model_card_review")
    assert na["currency"] is None and na["not_applicable_because"] == "empty_scope"


def test_not_applicable_rows_carry_their_cause_and_an_unknown_one_is_shown_not_guessed():
    out = evidence_currency({"rows": [
        {"step": "a", "status": "NOT_APPLICABLE", "not_applicable_because": "when_matched_no_file"},
        {"step": "b", "status": "NOT_APPLICABLE", "not_applicable_because": "not_required_for_action"},
        {"step": "c", "status": "NOT_APPLICABLE"},
        _row("d", judged=0, covered=0, stale=0, status="MISSING")]})
    got = {s["step"]: s["not_applicable_because"] for s in out["steps"]}
    assert got == {"a": "when_matched_no_file", "b": "not_required_for_action",
                   "c": "unclassified", "d": "empty_scope"}


# --- end-to-end, through the real inventory -------------------------------------------------

def _scenario(tmp_path, required: dict):
    """A repo, a stream and a config of the caller's choosing; returns (record, measure, repo)."""
    import os
    sys.path.insert(0, str(ROOT / "examples" / "evidence-currency"))
    import run_example as rx
    work = tmp_path / "w"
    repo = work / "repo"
    repo.mkdir(parents=True)
    (work / "records.jsonl").write_bytes(b"")
    req = work / "required.json"
    req.write_bytes(json.dumps(required).encode("utf-8"))
    env = dict(os.environ, ZPLEDGER_REPO=str(repo), ZPLEDGER_DATA=str(work / "records.jsonl"),
               ZPLEDGER_POLICY=str(rx.CONFIG / "policy.example.json"),
               ZPLEDGER_REQUIRED=str(req), ZPLOG_ENABLED="0")
    rx.git(repo, "init", "-q", "-b", "main")
    rx.git(repo, "config", "user.email", "e@e.invalid")
    rx.git(repo, "config", "user.name", "e")
    for p in ("a.txt", "b.txt", "c.txt", "d.txt", "harness.py"):
        rx.write(repo, p, p + "\n")
    rx.commit(repo, "init")

    def record(paths, verdict, **extra):
        rx.record(env, repo, rx.git(repo, "rev-parse", "HEAD"), "s", "harness.py", paths, work,
                  verdict, extra)

    def measure(*args):
        doc = json.loads(rx.ledger(env, "evidence-currency", "--ref", "HEAD", "--json", *args))
        return {s["step"]: s for s in doc["steps"]}

    return record, measure, repo, rx


def _req(**types):
    return {"schema": "zp.required.v2", "default": "REQUIRED_FOR_ALL_ACTIONS",
            "types": {k: {"family": "mechanical", "reason": "test", "module": "harness.py", **v}
                      for k, v in types.items()}}


def test_a_current_verdict_counts_whatever_it_recorded(tmp_path):
    """PASS, FAIL and UNDECIDED at the current bytes are all current evidence. The index that
    decides it is keyed (step, path, blob) and never reads the verdict; this pins that."""
    record, measure, _, _ = _scenario(tmp_path, _req(s={"scope": ["*.txt"]}))
    record(["a.txt"], "UNDECIDED")
    record(["b.txt"], "FAIL", failing=["b.txt"], revision=1)
    record(["c.txt"], "PASS", revision=2)
    s = measure()["s"]
    assert (s["in_scope"], s["current"], s["stale"], s["never_examined"]) == (4, 3, 0, 1)


def test_editing_the_harness_does_not_change_currency(tmp_path):
    """Measured 2026-10-09 and stated in the README: only the SUBJECT bytes decide current vs
    stale. The harness named as a record's `evidence` moving leaves currency at 100% while the
    ledger's own status for the step turns STALE. If this ever changes, the README and the
    published definition must change with it."""
    record, measure, repo, rx = _scenario(tmp_path, _req(s={"scope": ["*.txt"]}))
    record(["a.txt", "b.txt", "c.txt", "d.txt"], "PASS")
    assert measure()["s"]["currency"] == 1.0
    rx.write(repo, "harness.py", "changed\n")
    rx.commit(repo, "edit harness")
    s = measure()["s"]
    assert s["currency"] == 1.0 and s["stale"] == 0
    assert s["status"] == "STALE", "the control: the ledger DID notice the harness moved"


def test_each_not_applicable_cause_is_reported_from_the_real_inventory(tmp_path):
    _, measure, _, _ = _scenario(tmp_path, _req(
        empty={"scope": ["absent/*.md"]},
        gated={"when": "*.pdf", "scope": ["*.txt"]},
        tag_only={"scope": ["*.txt"], "actions": ["tag"]},
        live={"scope": ["*.txt"]}))
    got = {k: v.get("not_applicable_because") for k, v in measure("--action", "push").items()}
    assert got == {"empty": "empty_scope", "gated": "when_matched_no_file",
                   "tag_only": "not_required_for_action", "live": None}, got

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

def test_an_inconsistent_row_is_refused_rather_than_printed_with_a_negative_count():
    import pytest
    from core.errors import LedgerError
    with pytest.raises(LedgerError, match="exceeds in_scope"):
        evidence_currency({"rows": [_row("a", judged=2, covered=2, stale=1)]})


def test_declaring_the_harness_as_a_switch_makes_its_edit_count(tmp_path):
    """The README's remedy for a harness edit not counting, measured end to end. A declared
    switch must also be listed among each record's subjects (rule V15), and then counts in
    in_scope like any other file."""
    record, measure, repo, rx = _scenario(tmp_path, _req(
        s={"scope": ["*.txt"], "switches": ["harness.py"]}))
    try:
        record(["a.txt", "b.txt", "c.txt", "d.txt"], "PASS")
        raise AssertionError("a record omitting a declared switch was accepted")
    except SystemExit as refused:
        assert "V15" in str(refused)
    record(["a.txt", "b.txt", "c.txt", "d.txt", "harness.py"], "PASS")
    s = measure()["s"]
    assert (s["in_scope"], s["current"]) == (5, 5)
    rx.write(repo, "harness.py", "changed\n")
    rx.commit(repo, "edit harness")
    s = measure()["s"]
    assert (s["in_scope"], s["current"], s["stale"], s["currency"]) == (5, 4, 1, 0.8)