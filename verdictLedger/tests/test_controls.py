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
                              files={"docs/x.md": "b" * 40})
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
    reqs = {a: ledger.config.requirements(a) for a in ledger.config.actions}
    for action, r in reqs.items():
        assert r["build"]["required"] is True, f"build not required for {action}"


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
    ledger.append(good(step="build", subjects=[{"sha256": "b" * 40, "path": "x.lean"}]))
    recs = ledger.store.records()
    fresh = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "b" * 40})
    moved = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "c" * 40})
    assert next(r for r in fresh["rows"] if r["step"] == "build")["status"] == "SATISFIED"
    stale = next(r for r in moved["rows"] if r["step"] == "build")
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
    inv = inventory_mod.build(config=ledger.config, records=[], action="commit",
                              files={"x.lean": "b" * 40})
    assert inv["not_applicable"] > 0
    assert inv["required"] == len([r for r in inv["rows"]
                                   if r["status"] != "NOT_APPLICABLE"])


# -- ⭐ CROSSREF: NO DATA IS A FINDING, NOT A PASS -----------------------------

def test_crossref_on_a_missing_audit_stream_is_a_finding(tmp_path):
    out = crossref_mod.check(records=[], gitops_path=tmp_path / "nope.jsonl")
    assert out["no_data"] is True and out["ok"] is False
    assert "NOT PRESENT" in out["note"]


def test_crossref_on_an_empty_audit_stream_is_a_finding(tmp_path):
    p = tmp_path / "git_ops.jsonl"
    p.write_text("", encoding="utf-8")
    out = crossref_mod.check(records=[], gitops_path=p)
    assert out["no_data"] is True and out["ok"] is False
    assert "zero data" in out["note"]


def test_crossref_p1_finds_a_commit_no_step_examined(tmp_path):
    p = tmp_path / "git_ops.jsonl"
    p.write_text(json.dumps({"ts": "2026-08-22T00:00:00Z", "op": "commit",
                             "decision": "allowed", "head": "d" * 40,
                             "args": {"tree": "e" * 40}}) + "\n", encoding="utf-8")
    out = crossref_mod.check(records=[], gitops_path=p)
    assert any(v["property"] == "P1" for v in out["violations"])


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


def test_identity_ignores_timing_and_run(ledger):
    a = ledger.append(good(cost={"seconds": 0.1, "usd": 0.0},
                           run={"id": "run-1", "started": None,
                                "policy_sha": None, "env": {}}))
    b = ledger.append(good(cost={"seconds": 99.9, "usd": 12.0},
                           run={"id": "run-2", "started": None,
                                "policy_sha": None, "env": {}}))
    assert a["id"] == b["id"], "wall clock or run id leaked into the identity hash"


def test_subject_order_does_not_change_identity(ledger):
    s = [{"sha256": "1" * 40, "path": "a.md"}, {"sha256": "2" * 40, "path": "b.md"}]
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
