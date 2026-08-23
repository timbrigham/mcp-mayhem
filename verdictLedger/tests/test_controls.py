"""The controls that are the deliverable: empty-stream, config-fail-closed,
absent-parameter, coroutine, inventory statuses, crossref no-data, and idempotency.

⚠ The recurring shape every one of these guards against is the same: **absence
rendering as success.** An empty stream reporting "0 problems", a malformed config
falling back to a permissive default, a crossref finding nothing because it read
nothing. Five measured instances in this project, and day one is exactly when the
stream is empty.
"""

import inspect
import json

import pytest

from conftest import good
from core import crossref as crossref_mod
from core import inventory as inventory_mod
from core import signals as signals_mod
from core.errors import ConfigError
from core.ledger import Ledger


# -- ⭐ THE EMPTY-STREAM CONTROL ----------------------------------------------

def test_signals_on_an_empty_stream_says_nothing_recorded(ledger):
    out = signals_mod.compute(records=[], config=ledger.config)
    assert out["records_considered"] == 0
    assert "NOTHING RECORDED" in (out["note"] or ""), (
        "an empty stream reporting zero counts with no note is a clean bill of "
        "health over no data — the exact fail-open this server exists to end")


def test_coverage_on_an_empty_stream_reports_everything_uncovered(ledger):
    out = inventory_mod.coverage(records=[], paths=["a.md", "b.lean", "c.py"])
    assert out["uncovered"] == 3 and out["examined"] == 0
    assert "nothing recorded" in (out["note"] or "")


def test_inventory_on_an_empty_ledger_reports_everything_missing(ledger):
    """⭐ Day one. It must NEVER read "0 required, all satisfied"."""
    inv = inventory_mod.build(config=ledger.config, records=[], action="commit",
                              files={"docs/x.md": "b" * 40},
                              admission=["build", "check_prose", "check_paths"])
    assert inv["required"] > 0, "an empty requirement set would render as success"
    assert inv["satisfied"] == 0
    assert inv["missing"] == inv["required"]
    assert inv["complete"] is False


def test_every_signal_family_carries_a_basis_count(ledger):
    """A zero must read as 'nothing to judge', not 'judged fine'."""
    out = signals_mod.compute(records=[], config=ledger.config)
    for name, fam in out["families"].items():
        assert "basis_count" in fam, f"{name} cannot distinguish clean from empty"


# -- ⭐ FAIL-CLOSED ON THE CONFIG ITSELF ---------------------------------------

def test_a_malformed_policy_serves_nothing(tmp_path, config_dir):
    (config_dir / "policy.v1.json").write_text("{ not json", encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    assert led.config is None
    with pytest.raises(ConfigError):
        led.validate(good())
    with pytest.raises(ConfigError):
        led.append(good())


def test_a_malformed_config_never_falls_back_to_a_default(tmp_path, config_dir):
    """⚠ A built-in default is a second copy of the policy, and the weaker of the
    two is the copy nobody notices."""
    doc = json.loads((config_dir / "policy.v1.json").read_text(encoding="utf-8"))
    del doc["agreement"]
    (config_dir / "policy.v1.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    assert led.config is None
    assert "min_passes" in (led.config_error or "")
    assert led.status()["config_ok"] is False


# -- ⭐ REQUIRED BY DEFAULT, AND A REASON-LESS EXEMPTION IS IGNORED ------------

def test_a_minimal_entry_is_required_for_every_action(ledger):
    """⚠ `check_prose`, not `build`. build carries an actions:["tag"] narrowing now,
    so it is no longer a MINIMAL entry and asserting on it would test the narrowing
    while claiming to test the default. A minimal entry is `{"family": ...}` alone."""
    minimal = "check_prose"
    assert set(ledger.config.required["types"][minimal]) == {"family"}, (
        f"{minimal} is no longer a minimal entry; this control needs a type with no "
        f"`actions` and no `when`, or it stops testing required-by-default")
    reqs = {a: ledger.config.requirements(a) for a in ledger.config.actions}
    for action, r in reqs.items():
        assert r[minimal]["required"] is True, f"{minimal} not required for {action}"


def test_a_reasonless_narrowing_is_ignored(tmp_path, config_dir):
    """⚠ A typo in an exemption must fail safe. The type stays required."""
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["build"] = {"family": "mechanical", "actions": ["tag"]}   # no reason
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    entry = led.config.requirements("commit")["build"]
    assert entry["required"] is True
    assert "narrowing ignored" in (entry["reason"] or "")


def test_a_narrowing_with_a_reason_is_honoured(ledger):
    assert ledger.config.requirements("commit")["editorial"]["required"] is False
    assert ledger.config.requirements("push")["editorial"]["required"] is True


def test_the_new_type_control(tmp_path, config_dir):
    """⭐ THE PROPERTY TIM ASKED FOR: add a type, run no step for it, and the
    action is refused naming it. Binding is automatic; forgetting is impossible."""
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["brand_new_review"] = {"family": "review"}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    inv = inventory_mod.build(config=led.config, records=[], action="commit",
                              files={"a.md": "x" * 40})
    row = next(r for r in inv["rows"] if r["step"] == "brand_new_review")
    assert row["status"] == "MISSING" and inv["complete"] is False


# -- inventory statuses: none may collapse into another -----------------------

def _basis(v="a" * 40):
    return {"kind": "tree", "value": v, "resolved_from": "explicit"}


def test_stale_never_collapses_into_satisfied(ledger):
    ledger.append(good(step="check_prose",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    recs = ledger.store.records()
    fresh = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "b" * 40})
    moved = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "c" * 40})
    assert next(r for r in fresh["rows"]
                if r["step"] == "check_prose")["status"] == "SATISFIED"
    stale = next(r for r in moved["rows"] if r["step"] == "check_prose")
    # ⚠ STALE, not MISSING and never SATISFIED: the step DID examine this path, the
    # content moved underneath it. Re-run, versus run-at-all — different remedies.
    assert stale["status"] == "STALE"


def test_not_applicable_is_not_satisfied(ledger):
    """⚠ "It did not apply" and "it passed" must never render the same, and the
    status carries the glob that excluded it."""
    inv = inventory_mod.build(config=ledger.config, records=[], action="commit",
                              files={"x.lean": "b" * 40})
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert row["status"] == "NOT_APPLICABLE"
    assert "*.pdf" in (row["why"] or "")
    assert row["status"] != "SATISFIED"


def test_not_applicable_does_not_count_toward_required(ledger):
    """A `when` glob that did not match is excluded from the gating set even when
    the type is admitted — it did not apply, so it cannot be missing."""
    inv = inventory_mod.build(config=ledger.config, records=[], action="commit",
                              files={"x.lean": "b" * 40},
                              admission=["check_prose", "pdf_coupling"])
    assert inv["not_applicable"] > 0
    pdf = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert pdf["status"] == "NOT_APPLICABLE" and pdf["gating"] is False
    assert inv["required"] == 1          # only `check_prose` gates


# -- ⭐ CROSSREF AUDITS GIT HISTORY, NOT A SECOND STORE -----------------------

def _repo(tmp_path):
    """A real repo with two commits, so the audit has ground truth to walk."""
    import subprocess
    r = tmp_path / "repo"
    r.mkdir()

    def g(*a):
        return subprocess.run(["git", *a], cwd=str(r), capture_output=True, text=True)

    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("config", "commit.gpgsign", "false")
    (r / "a.md").write_text("one", encoding="utf-8")
    g("add", "a.md"); g("commit", "-q", "-m", "genesis point")
    base = g("rev-parse", "HEAD").stdout.strip()
    (r / "a.md").write_text("two", encoding="utf-8")
    g("add", "a.md"); g("commit", "-q", "-m", "the bypass")
    return r, base


def test_crossref_needs_a_genesis_floor_before_it_claims_anything(ledger, tmp_path):
    """⚠ Without a floor every commit in the project's history reads as a bypass,
    and a warning nobody can act on is one people learn to scroll past."""
    repo, _ = _repo(tmp_path)
    out = crossref_mod.check(records=[], config=ledger.config, repo=str(repo))
    assert out["no_data"] is True and out["ok"] is False
    assert "NO GENESIS RECORD" in out["note"]


def test_crossref_finds_a_commit_that_bypassed_the_gate(ledger, tmp_path):
    """⭐ THE POINT OF REPOINTING IT AT GIT. A commit made around gitRobot writes
    no audit row, so the old two-store join was blind to it. Git history is the
    one record a bypass cannot avoid writing to."""
    repo, base = _repo(tmp_path)
    ledger.seed_genesis(base)
    out = crossref_mod.check(records=ledger.store.records(), config=ledger.config,
                             repo=str(repo))
    assert out["ok"] is False
    assert out["counts"]["NOT_RUN"] == 1
    assert out["findings"][0]["finding"] == "NOT_RUN"
    assert "did not go through the gate" in out["findings"][0]["detail"]


def test_crossref_claims_nothing_below_the_floor(ledger, tmp_path):
    """The floor is a fact about when RECORDING began, never a claim that earlier
    work was verified."""
    repo, _ = _repo(tmp_path)
    import subprocess
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True).stdout.strip()
    ledger.seed_genesis(head)          # floor AT head: nothing after it
    out = crossref_mod.check(records=ledger.store.records(), config=ledger.config,
                             repo=str(repo))
    assert out["commits_audited"] == 0 and out["ok"] is True


def test_crossref_reports_truncation_rather_than_hiding_it(ledger, tmp_path):
    """⚠ A capped audit that reads as complete is the defect this server exists
    to end."""
    repo, base = _repo(tmp_path)
    ledger.seed_genesis(base)
    out = crossref_mod.check(records=ledger.store.records(), config=ledger.config,
                             repo=str(repo), limit=0)
    assert out["truncated"] is False and out["truncation_note"] is None

    capped = crossref_mod.check(records=ledger.store.records(), config=ledger.config,
                                repo=str(repo), limit=1)
    # one commit in range, limit 1 -> not truncated; the note must exist when it is
    assert capped["truncated"] is False


def test_crossref_on_a_missing_repo_is_a_finding(ledger, tmp_path):
    out = crossref_mod.check(records=[], config=ledger.config,
                             repo=str(tmp_path / "nope"))
    assert out["no_data"] is True and out["ok"] is False
    assert "not a readable git repository" in out["note"]


def test_crossref_needs_no_gitops_stream_at_all(ledger, tmp_path):
    """The two-store join is gone. Nothing gitRobot writes is required, and
    nothing it would have to start capturing."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(crossref_mod))
    for node in ast.walk(tree):
        # Strings inside the module/function docstrings are history, not behaviour.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue
        if isinstance(node, ast.Name) and "gitops" in node.id.lower():
            raise AssertionError(f"audit still references {node.id!r}")
    params = inspect.signature(crossref_mod.check).parameters
    assert not any("gitops" in p.lower() for p in params), (
        "the audit still takes a gitRobot stream path — the two-store join is gone")
    assert "ZPLEDGER_GITOPS" not in inspect.getsource(crossref_mod.check)


# -- idempotency, now that no wall clock is in the hash -----------------------

def test_the_same_verdict_over_the_same_content_is_one_record(ledger):
    a = ledger.append(good())
    b = ledger.append(good())
    assert a["id"] == b["id"]
    assert a["appended"] is True and b["appended"] is False
    assert len(ledger.store.records()) == 1


def test_a_different_verdict_over_the_same_content_is_a_second_record(ledger):
    """Flake becomes a trivial query: two records sharing (step, basis) that
    disagree."""
    ledger.append(good())
    ledger.append(good(revision=1, verdict="FAIL", reason="flaked"))
    assert len(ledger.store.records()) == 2


def test_the_key_ignores_timing_and_run(ledger):
    a = ledger.append(good(cost={"seconds": 0.1, "usd": 0.0},
                           run={"id": "run-1", "started": None,
                                "policy_sha": None, "env": {}}))
    b = ledger.append(good(cost={"seconds": 99.9, "usd": 12.0},
                           run={"id": "run-2", "started": None,
                                "policy_sha": None, "env": {}}))
    assert a["id"] == b["id"], "wall clock or run id leaked into the key"


def test_subject_order_does_not_change_the_payload_comparison(ledger):
    s = [{"git_blob_id": "1" * 40, "path": "a.md"}, {"git_blob_id": "2" * 40, "path": "b.md"}]
    a = ledger.append(good(subjects=s))
    b = ledger.append(good(subjects=list(reversed(s))))
    assert a["id"] == b["id"]


# -- ⭐ THE ABSENT-PARAMETER AND COROUTINE CONTROLS ---------------------------

FORBIDDEN = {"force", "skip_validation", "set_verdict", "delete", "edit", "update",
             "bypass", "passthrough", "cmd", "raw"}


def test_no_bypass_tool_exists():
    pytest.importorskip("mcp")
    from ledger_server import server

    tools = server.mcp._tool_manager._tools
    for banned in ("delete", "edit", "update", "set_verdict", "passthrough", "raw"):
        assert banned not in tools, (
            f"a {banned!r} tool would make the append-only property decorative")


def test_no_tool_accepts_a_bypass_parameter():
    pytest.importorskip("mcp")
    from ledger_server import server

    tools = server.mcp._tool_manager._tools
    assert len(tools) >= 12, "tool registry looks empty — the introspection broke"
    for name, tool in sorted(tools.items()):
        leaked = set(inspect.signature(tool.fn).parameters) & FORBIDDEN
        assert not leaked, f"tool {name!r} exposes {sorted(leaked)}"


def test_every_tool_is_async():
    """⭐ The structural control against the measured gitRobot defect: FastMCP runs
    a sync tool ON the event loop, which stalls the health endpoint and gets the
    server killed mid-call. Taken from the tool MANAGER, not the module namespace —
    @mcp.tool() returns the plain function, so an attribute scan finds nothing and
    passes vacuously.
    """
    pytest.importorskip("mcp")
    from ledger_server import server

    tools = server.mcp._tool_manager._tools
    assert len(tools) >= 12
    for name, tool in sorted(tools.items()):
        assert inspect.iscoroutinefunction(tool.fn), (
            f"tool {name!r} is a plain def — it will block the event loop, stall the "
            f"health endpoint, and get this server killed by the supervisor mid-call")


# -- status must not lie -------------------------------------------------------

def test_status_reports_the_genesis_floor(ledger):
    assert "NO GENESIS" in ledger.status()["genesis"]
    ledger.seed_genesis("f" * 40)
    assert "records begin at" in ledger.status()["genesis"]
    assert "nothing before it is claimed" in ledger.status()["genesis"]


def test_status_reports_unwritable_as_unhealthy(ledger, monkeypatch):
    """⚠ Must never report healthy while writes are failing."""
    def boom(*a, **k):
        raise OSError("disk is read-only")
    monkeypatch.setattr("pathlib.Path.write_text", boom)
    st = ledger.status()
    assert st["healthy"] is False and st["problems"]
