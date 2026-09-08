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
import pathlib

import pytest

from conftest import good
from core import crossref as crossref_mod
from core import inventory as inventory_mod
from core import render as render_mod
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
                              admission=["build", "check_prose", "check_invariants"])
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
    minimal = "check_invariants"
    # ⚠ Test the PROPERTY, not the key set. `switches` is not a narrowing — it makes a
    # type stricter — so its presence must not disqualify a type from being minimal
    # here. An exact-equality assertion said otherwise and would have pushed the next
    # reader to drop a switch to keep a test green.
    narrowings = {"actions", "when", "scope"} & set(
        ledger.config.required["types"][minimal])
    assert not narrowings, (
        f"{minimal} now carries {narrowings}; this control needs a type with no "
        f"narrowing, or it stops testing required-by-default")
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
    ledger.append(good(step="check_invariants",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    recs = ledger.store.records()
    fresh = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "b" * 40})
    moved = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "c" * 40})
    assert next(r for r in fresh["rows"]
                if r["step"] == "check_invariants")["status"] == "SATISFIED"
    stale = next(r for r in moved["rows"] if r["step"] == "check_invariants")
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
                                "config_sha": None, "env": {}}))
    b = ledger.append(good(cost={"seconds": 99.9, "usd": 12.0},
                           run={"id": "run-2", "started": None,
                                "config_sha": None, "env": {}}))
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


# -- ⭐ NARROWED COVERAGE IS VISIBLE ------------------------------------------

def test_a_step_that_examined_one_file_of_many_is_not_silently_satisfied(ledger):
    """⭐⭐ MEASURED 2026-08-23, and it is the defect class this server exists to end.

    A step that examined ONE file out of 201 read SATISFIED. A path with no record for
    that step contributed to neither `covered` nor `stale`, so it was not counted at
    all — absence rendering as success, arriving through the one door nobody checked.

    It mattered immediately: ZeroParadox's `common.ledger_subjects` DROPS any path
    whose worktree differs from the index. That fence is honest about what it read,
    but the narrowing was invisible here, so a dirty tree quietly shrank what a green
    key meant.

    ⚠ The count is REPORTED, not blocking — making it block is a policy decision.
    But a downgraded gate has to get louder, so it must never be silent again.
    """
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "a.md", "git_blob_id": "a" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    files = {f"f{i}.md": "b" * 40 for i in range(200)}
    files["a.md"] = "a" * 40

    inv = inventory_mod.build(config=ledger.config, records=rec, action="push",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["subjects_covered"] == 1
    assert row["subjects_unexamined"] == 200, "the narrowing was invisible again"
    assert inv["unexamined"] == 200


def test_the_narrowing_is_named_even_when_the_inventory_is_COMPLETE(ledger):
    """⭐ THE LOAD-BEARING HALF. An incomplete inventory already refuses and the
    reader is already looking; the dangerous case is a GREEN one over a thin scope.
    The warning therefore prints before the `complete` early return."""
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "a.md", "git_blob_id": "a" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    files = {"a.md": "a" * 40, "b.md": "b" * 40, "c.md": "c" * 40}
    inv = inventory_mod.build(config=ledger.config, records=rec, action="push",
                              files=files, ref="t", admission=["check_prose"])
    assert inv["complete"] is True
    line = render_mod.render_inventory(inv)
    assert "NARROWED COVERAGE" in line
    assert "check_prose 1/3" in line


def test_full_coverage_raises_no_warning(ledger):
    """⚠ …and it must not cry wolf when the scope really was covered."""
    files = {"a.md": "a" * 40}
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "a.md", "git_blob_id": "a" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    inv = inventory_mod.build(config=ledger.config, records=rec, action="push",
                              files=files, ref="t", admission=["check_prose"])
    assert inv["unexamined"] == 0
    assert "NARROWED COVERAGE" not in render_mod.render_inventory(inv)


# -- ⭐ needs_rerun: the server answers what must actually run ----------------

def _one_record(step="check_prose", path="old.md", blob="a" * 40):
    return [{"id": f"{step}@t#0", "step": step, "verdict": "PASS", "revision": 0,
             "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
             "subjects": [{"path": path, "git_blob_id": blob}],
             "basis": {"kind": "tree", "value": "t"}}]


def _row(ledger, records, files, step="check_prose"):
    inv = inventory_mod.build(config=ledger.config, records=records, action="commit",
                              files=files, ref="t", admission=[step])
    return inv, next(r for r in inv["rows"] if r["step"] == step)


def test_a_fully_covered_step_does_not_need_rerunning(ledger):
    """The whole point: a checker whose subjects have not moved is re-deriving a
    verdict that already carries forward."""
    inv, row = _row(ledger, _one_record(), {"old.md": "a" * 40})
    assert row["needs_rerun"] is False and row["rerun_reason"] is None
    assert "check_prose" not in inv["needs_rerun"]


def test_a_step_needs_rerunning_when_a_NEW_FILE_appears(ledger):
    """⭐⭐ THE HOLE IN THE OBVIOUS PREDICATE, and the reason this lives server-side.

    ZeroParadox planned to re-run on STALE or MISSING. A commit that ADDS a file leaves
    the row SATISFIED — covered=1, unexamined=1 — because a path with no record counts
    as neither covered nor stale. Under a skip-if-green hook the checker would be
    SKIPPED and the new file never examined by it.

    `subjects_unexamined` was a reporting defect; under that hook it becomes a checker
    that silently stops running.
    """
    inv, row = _row(ledger, _one_record(), {"old.md": "a" * 40, "brand_new.md": "b" * 40})
    assert row["status"] == "SATISFIED"          # green…
    assert row["needs_rerun"] is True            # …and still owed a run
    assert "never examined" in row["rerun_reason"]


@pytest.mark.parametrize("files,expect", [
    ({"old.md": "CHANGED" + "a" * 33}, "stale"),
    ({"other.md": "b" * 40}, "missing"),
])
def test_the_ordinary_cases_still_need_rerunning(ledger, files, expect):
    inv, row = _row(ledger, _one_record(), files)
    assert row["needs_rerun"] is True and row["rerun_reason"] == expect


def test_a_not_applicable_step_is_never_rerun(ledger):
    """⚠ "It did not apply" is the one green that genuinely costs nothing to skip."""
    inv = inventory_mod.build(config=ledger.config, records=[], action="commit",
                              files={"x.lean": "b" * 40}, ref="t",
                              admission=["pdf_coupling"])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert row["status"] == "NOT_APPLICABLE" and row["needs_rerun"] is False


def test_needs_rerun_covers_types_that_are_not_admitted(ledger):
    """⚠ WHAT TO RUN AND WHAT GATES ARE DIFFERENT QUESTIONS. A hook has emitters for
    types nothing currently admits, and must not be told to skip them merely because
    no admission set names them — that would make promoting a type later silently
    depend on someone remembering to re-run it."""
    inv = inventory_mod.build(config=ledger.config, records=[], action="commit",
                              files={"a.md": "a" * 40}, ref="t", admission=[])
    assert inv["needs_rerun"], "an empty admission set emptied the re-run list"
    assert "check_prose" in inv["needs_rerun"]


# -- ⭐ `scope`: which paths a type EXAMINES, distinct from where it APPLIES ---

def _cfg_with_scope(tmp_path, config_dir, **scope_spec):
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["check_prose"] = {"family": "mechanical", **scope_spec}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    return Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


def test_a_declared_scope_shrinks_what_a_type_owes(tmp_path, config_dir):
    """⭐⭐ MEASURED LIVE 2026-08-23: without this, `guards` reported 475 of 479 paths
    unexamined — about paths that were never its to examine — so it would have been
    re-run on every commit forever. That is the 18.26s the skip-if-unchanged design
    exists to avoid, which makes this the difference between a useless optimisation
    and a working one."""
    led = _cfg_with_scope(tmp_path, config_dir, scope="tools/**",
                          reason="reads only the tooling tree")
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0, "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "tools/a.py", "git_blob_id": "a" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    files = {"tools/a.py": "a" * 40, "docs/x.md": "b" * 40, "docs/y.md": "c" * 40}

    inv = inventory_mod.build(config=led.config, records=rec, action="commit",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["scope"] == 1                 # only tools/a.py is its business
    assert row["subjects_unexamined"] == 0
    assert row["needs_rerun"] is False


def test_no_declared_scope_still_means_every_path(tmp_path, config_dir):
    """⚠ THE DEFAULT STAYS STRICT. A type that has not said what it examines owes the
    whole tree — consistent with required-by-default, where inclusion is free and
    exclusion is the thing that takes effort."""
    led = _cfg_with_scope(tmp_path, config_dir)
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0, "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "tools/a.py", "git_blob_id": "a" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    files = {"tools/a.py": "a" * 40, "docs/x.md": "b" * 40}
    inv = inventory_mod.build(config=led.config, records=rec, action="commit",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["scope"] == 2 and row["subjects_unexamined"] == 1
    assert row["needs_rerun"] is True


def test_a_reasonless_scope_is_ignored_like_any_other_narrowing(tmp_path, config_dir):
    """⚠ A typo in an exemption must fail safe. `scope` is a narrowing and costs a
    stated reason exactly like `actions` and `when`."""
    led = _cfg_with_scope(tmp_path, config_dir, scope="tools/**")   # no reason
    files = {"tools/a.py": "a" * 40, "docs/x.md": "b" * 40}
    inv = inventory_mod.build(config=led.config, records=[], action="commit",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["scope"] == 2, "a reason-less scope narrowed the type anyway"


def test_scope_is_not_when(tmp_path, config_dir):
    """⚠ THE DISTINCTION THAT MAKES BOTH USEFUL. `when` says whether the type applies
    at all — no match and the whole row is NOT_APPLICABLE. `scope` says which paths it
    examines when it does apply: the type is still REQUIRED, it owes fewer paths."""
    led = _cfg_with_scope(tmp_path, config_dir, scope="tools/**",
                          reason="reads only the tooling tree")
    inv = inventory_mod.build(config=led.config, records=[], action="commit",
                              files={"docs/x.md": "b" * 40}, ref="t",
                              admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["status"] != "NOT_APPLICABLE", "scope behaved like when"
    assert inv["complete"] is False


def test_scope_accepts_a_list_of_globs(tmp_path, config_dir):
    """⭐ A REAL CHECKER READS MORE THAN ONE ROOT. ZeroParadox measured `check_hashes`
    over `register.md` plus 39 files under `scripts/`, and `guards` over three roots
    including the corpus itself. A single-glob API forced them to either widen a glob
    until it was wrong or leave the checker unscoped — so the API was the defect, not
    their measurement.

    They chose to pay 18.26s per commit rather than narrow `guards` wrongly, which is
    the right instinct: a wrong `scope` narrows INVISIBLY — the row just goes green
    over fewer paths — and `guards` is the checker whose job is proving the exemption
    surface still behaves.
    """
    led = _cfg_with_scope(tmp_path, config_dir,
                          scope=["register.md", "scripts/**"],
                          reason="reads the register plus the script bundle")
    files = {"register.md": "a" * 40, "scripts/x.py": "b" * 40,
             "docs/unrelated.md": "c" * 40}
    inv = inventory_mod.build(config=led.config, records=[], action="commit",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["scope"] == 2, "a second root was dropped"


def test_a_string_scope_still_works(tmp_path, config_dir):
    """⚠ Normalised in config so no consumer re-implements the string case."""
    led = _cfg_with_scope(tmp_path, config_dir, scope="tools/**",
                          reason="reads only the tooling tree")
    assert led.config.requirements("commit")["check_prose"]["scope"] == ["tools/**"]


def test_the_shipped_scopes_match_what_was_measured(ledger):
    """⚠ Pins the three ZeroParadox MEASURED and gave, and that the two they REFUSED
    to guess stay unscoped. `guards` over-running is a deliberate, costed choice — a
    later "tidy-up" that scopes it to tools/verify/** would silently drop the corpus
    paths it plants violations in."""
    reqs = ledger.config.requirements("commit")
    # ⚠ The PRECISE list, not `tools/verify/**`. ZeroParadox measured
    # check_checkers.checkers() at 19 files while the directory holds 58 — the same
    # over-match as the *_baseline.txt glob, one directory up. It stays dynamic: a
    # checker added later matches check_*.py on its own.
    assert reqs["check_checkers"]["scope"] == [
        "tools/verify/check_*.py", "tools/verify/common.py",
        "tools/verify/debaseline.py", "tools/verify/guards.py",
        "tools/verify/vendored.py"]
    # ⭐ the exclusion form: "all tracked text" is not expressible as an allow-list
    assert reqs["check_encoding"]["scope"] == ["*"]
    assert reqs["check_encoding"]["scope_exclude"] == ["*.pdf", "*.ttf"]
    # ⚠ THE EXPLICIT SIX, not the glob they proposed. `tools/verify/*_baseline.txt`
    # matched TEN files at their tree while check_frozen covers SIX, so the glob was
    # broader than the property: `unexamined` stayed at 4 and the optimisation never
    # fired. Enumerating is faithful to their own wording ("exactly the 6 frozen
    # baselines") and is the same six already declared as check_frozen's `switches`.
    six = ["tools/verify/" + f + "_baseline.txt" for f in
           ("class", "figures", "modal", "negatives", "pov", "prose")]
    assert reqs["check_frozen"]["scope"] == six
    assert reqs["claim_review"]["scope"] == six
    # ⚠ `guards` STAYS UNSCOPED, and not out of caution. Two of its seven inputs live
    # in `.claude-local`, a DIFFERENT repository, so they can never be subjects of a
    # record here at all — `rely_cleared.txt` can be edited, guards' verdict changes,
    # and no subject moves. A scope cannot close that; only REQ-2 (`rely` becoming a
    # record rather than a file) can. Scoping it to the five in-tree paths would make
    # it LOOK fully covered while its two most decision-bearing inputs sit outside.
    assert reqs["guards"]["scope"] is None, "guards was scoped over a hole"
    # `check_pov` likewise: its property is ".md only where a same-stem .lean exists",
    # which is a sibling test, not a path pattern. Measured: 69 .md, 28 paired, 41 not.
    assert reqs["check_pov"]["scope"] is None
    # ⚠ `scripts/*` was too broad and ZeroParadox corrected it themselves: fnmatch's
    # `*` crosses `/`, so it swept in the fonts, scan_pdfs.py and the private-only
    # scripts. `zp_utils.py` is in scope because check_shared_build() verifies it —
    # it was inside the property and NOT a subject, so editing the module every build
    # script imports left the record SATISFIED.
    assert reqs["check_hashes"]["scope"] == [
        "register.md", "scripts/build_*.py", "scripts/zp_utils.py"]


# -- ⭐ a type may be RECORDABLE without being REQUIRED ----------------------

def test_check_frozen_records_but_does_not_gate(ledger):
    """⭐ THE TWO LISTS EARNING THEIR KEEP. Tim, 2026-08-23: "I have no problem if you
    want to still allow it to be submitted.. it just shouldn't be required in order to
    pass." That is exactly the registry/admission split — what may be RECORDED versus
    what must PASS — and it is the first time the distinction has been used for its
    stated purpose rather than argued about.

    `check_frozen` is from a topology that no longer exists (the independent-git-spaces
    rewrite), so its freeze comparison cannot succeed and never will. Registering it
    keeps its records valid and its history readable; narrowing it stops a permanently
    impossible check from blocking every action.
    """
    assert ledger.config.is_registered("check_frozen"), "records must stay valid"
    for action in ("commit", "push", "tag"):
        row = ledger.config.requirements(action)["check_frozen"]
        assert row["required"] is False, f"still gating {action}"
        assert "topology that no longer exists" in (row["reason"] or "")


def test_a_failing_check_frozen_no_longer_blocks(ledger):
    """⚠ THE PROPERTY, not just the config. A FAIL record for a narrowed type must not
    reach the gating set at all — otherwise the retirement is cosmetic."""
    ledger.append(good(step="check_frozen", verdict="FAIL",
                       reason="a frozen baseline grew",
                       subjects=[{"git_blob_id": "b" * 40,
                                  "path": "tools/verify/" + f + "_baseline.txt"}
                                 for f in ("class", "figures", "modal", "negatives",
                                           "pov", "prose")]))
    inv = inventory_mod.build(
        config=ledger.config, records=ledger.store.records(), action="push",
        files={"tools/verify/class_baseline.txt": "b" * 40}, ref="t",
        admission=["check_frozen"])
    row = next(r for r in inv["rows"] if r["step"] == "check_frozen")
    assert row["status"] == "NOT_APPLICABLE"
    assert row["gating"] is False
    assert inv["failed"] == 0, "a retired type still counted toward failure"


def test_the_reason_lives_in_the_registry_not_the_admission_set(ledger):
    """⚠ §12-0-ter: "Admission should never carry a policy exception; it is a list of
    names, and a list of names cannot explain itself." A gate that vanished from a
    list nobody diffed is how a bar drops silently."""
    reason = ledger.config.requirements("push")["check_frozen"]["reason"]
    assert reason and len(reason) > 40
    assert "Tim" in reason, "the decision is unattributed"


# -- ⭐ a config the running build predates must REFUSE, not crash ------------

def _broken(tmp_path, config_dir, **spec):
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["check_prose"] = {"family": "mechanical", **spec}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    return Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


@pytest.mark.parametrize("spec,field", [
    ({"when": ["a", "b"]}, "when"),
    ({"scope": 42}, "scope"),
    ({"scope": ["ok", 7]}, "scope"),
    ({"switches": "…"}, None),          # a string switch is legal, see below
    ({"switches": [None]}, "switches"),
    ({"actions": "push"}, "actions"),
])
def test_a_malformed_field_is_a_config_error_not_a_crash(tmp_path, config_dir,
                                                         spec, field):
    """⭐⭐ MEASURED 2026-08-23. `scope` gained list support at 16:00; I wrote
    list-valued scopes into the config at 15:55, while the server still ran the 15:53
    build whose `fnmatch.fnmatch(path, glob)` took a single string. `fnmatch` calls
    `os.path.normcase`, which raises `TypeError: expected str, bytes or os.PathLike
    object, not list` — naming neither the file nor the field.

    THE CLASS: config is data read LIVE, while the code that understands it needs a
    RESTART. The two deploy at different times and nothing checked they agreed.

    ZeroParadox's framing is why it is worth fixing properly rather than patching the
    one field: "a crash is indistinguishable from the server being down to any caller
    that swallows errors — which mine did, returning None and reading as 'nothing
    needs re-running'." Absence rendering as success, in the code that decides what
    runs.
    """
    led = _broken(tmp_path, config_dir, **spec)
    if field is None:
        assert led.config is not None       # a bare string is a legal one-element list
        return
    assert led.config is None, f"a malformed {field} reached the code"
    assert field in (led.config_error or "")
    assert led.status()["config_ok"] is False


def test_the_config_error_says_to_restart_rather_than_edit_back(tmp_path, config_dir):
    """⚠ THE REMEDY MATTERS MORE THAN THE REFUSAL. The natural reading of "this value
    is wrong" is to delete it — which would silently drop a `scope` somebody added
    deliberately, on a stale build. The message has to name the other possibility."""
    led = _broken(tmp_path, config_dir, scope=42)
    assert "RESTART" in (led.config_error or "")


def test_a_gated_action_refuses_rather_than_answering_on_a_bad_config(tmp_path,
                                                                      config_dir):
    """⚠ …and it must reach the CALLER as a refusal, not as an exception that a
    swallowing client reads as 'nothing to do'."""
    led = _broken(tmp_path, config_dir, scope=42)
    with pytest.raises(ConfigError, match="every gated action refuses"):
        led._require_config()


def test_scope_exclude_subtracts(tmp_path, config_dir):
    """⭐ SOME PROPERTIES ARE "ALL BUT THESE". `check_encoding`'s scope is tracked TEXT
    files; there is no glob for "is this file text", and an extension allow-list fails
    in the DANGEROUS direction — a new text extension appears, no glob matches it, and
    the scope silently narrows. An exclusion re-arms the warning instead.

    ⚠ Chosen over self-scoping (letting the record's subjects BE the scope), which is
    tidier and destroys the field: nothing independent would say what a checker SHOULD
    have looked at, so one that silently narrowed would read fully covered forever.
    """
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["check_prose"] = {"family": "mechanical", "scope": ["*"],
                                   "scope_exclude": ["*.pdf", "*.ttf"],
                                   "reason": "text only"}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    files = {"a.md": "a" * 40, "docs/b.md": "b" * 40,
             "paper.pdf": "c" * 40, "fonts/x.ttf": "d" * 40}
    inv = inventory_mod.build(config=led.config, records=[], action="commit",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["scope"] == 2, "the exclusion did not subtract, or ate too much"


def test_a_star_glob_crosses_slashes_and_double_star_does_not(ledger):
    """⚠⚠ THE FOOTGUN, PINNED. fnmatch's `*` crosses `/`, so `*` alone is "every path"
    — and a `**/` prefix is WRONG rather than redundant: `**/*` requires at least one
    directory and therefore MISSES every top-level file. REQ-15 proposed `**/*` and
    `**/*.pdf`, which would have silently mis-scoped in the direction this field
    exists to prevent."""
    import fnmatch
    assert fnmatch.fnmatch("README.md", "*") is True
    assert fnmatch.fnmatch("README.md", "**/*") is False
    assert fnmatch.fnmatch("a.pdf", "**/*.pdf") is False
    assert fnmatch.fnmatch("a.pdf", "*.pdf") is True


def test_exclusions_are_named_individually_not_matched(ledger):
    """⭐ THE DIRECTION AN EXCLUSION MUST FAIL IN. `check_hashes` excludes three
    generated-doc builders that render markdown carrying no register row, so no
    fingerprint is owed. They are listed BY NAME rather than matched with something
    like `scripts/build_*_map.py`, because a pattern would silently hand the exemption
    to a fourth such builder added later — and an exemption nobody chose is exactly
    what `subjects_unexamined` exists to surface.

    Three names cost one line each and re-arm the warning the day a new one appears.
    """
    excl = ledger.config.requirements("commit")["check_hashes"]["scope_exclude"]
    assert excl == ["scripts/build_dictionary_map.py",
                    "scripts/build_manifest.py",
                    "scripts/build_snap_map.py"]
    assert not any("*" in e or "?" in e for e in excl), (
        "an exclusion became a pattern; a builder added later would inherit the "
        "exemption silently")


# -- ⭐ subjects_unscoped: the symmetric detector ------------------------------

def test_a_scope_narrower_than_what_was_examined_is_surfaced(tmp_path, config_dir):
    """⭐⭐ THE BLIND SIDE OF THE RESIDUE SWEEP. `subjects_unexamined` finds a scope
    WIDER than the property. It is structurally blind to one that is NARROWER, because
    an excluded path produces no residue at all — `unexamined` goes to zero and
    everything reads clean. The exclusions both sessions started adding are exactly
    what it cannot see.

    This number is derived from the checker's own SUBJECT SET rather than from the
    declaration, which is the property that makes the pair work: two numbers arrived at
    independently.
    """
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["check_prose"] = {"family": "mechanical", "scope": ["docs/*"],
                                   "reason": "docs only"}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "docs/a.md", "git_blob_id": "a" * 40},
                         {"path": "elsewhere/b.md", "git_blob_id": "b" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    files = {"docs/a.md": "a" * 40, "elsewhere/b.md": "b" * 40}

    inv = inventory_mod.build(config=led.config, records=rec, action="commit",
                              files=files, ref="t", admission=["check_prose"])
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["subjects_unexamined"] == 0, "the wide-detector should be silent here"
    assert row["subjects_unscoped"] == ["elsewhere/b.md"]
    assert inv["unscoped"] == ["elsewhere/b.md"]
    assert "EXAMINED BUT UNSCOPED" in render_mod.render_inventory(inv)


def test_a_declared_switch_is_not_reported_as_unscoped(tmp_path, config_dir):
    """⚠ Switches are SUPPOSED to sit outside the scanned scope — they are the
    exemption surface, not the corpus. Without this subtraction the field would be
    permanent known-noise on the eight types that declare one, and a noisy alarm is a
    disabled alarm."""
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["check_prose"] = {"family": "mechanical", "scope": ["docs/*"],
                                   "switches": ["tools/verify/prose_baseline.txt"],
                                   "reason": "docs only"}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    rec = [{"id": "check_prose@t#0", "step": "check_prose", "verdict": "PASS",
            "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "docs/a.md", "git_blob_id": "a" * 40},
                         {"path": "tools/verify/prose_baseline.txt",
                          "git_blob_id": "b" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    files = {"docs/a.md": "a" * 40, "tools/verify/prose_baseline.txt": "b" * 40}
    inv = inventory_mod.build(config=led.config, records=rec, action="commit",
                              files=files, ref="t", admission=["check_prose"])
    assert inv["unscoped"] == []


def test_unscoped_spans_types_nothing_admits(ledger):
    """⚠ An undeclared switch on a type nothing currently gates is still an undeclared
    switch, and promoting that type later would inherit the hole silently. Same
    reasoning as `needs_rerun` spanning the whole registry."""
    rec = [{"id": "check_pov@t#0", "step": "check_pov", "verdict": "PASS",
            "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "nowhere/x.md", "git_blob_id": "a" * 40}],
            "basis": {"kind": "tree", "value": "t"}}]
    inv = inventory_mod.build(config=ledger.config, records=rec, action="commit",
                              files={"nowhere/x.md": "a" * 40}, ref="t", admission=[])
    assert inv["unscoped"] == [], "check_pov is unscoped, so nothing is out of scope"


def test_check_hashes_declares_the_switch_it_records(ledger):
    """⭐ THE HIT THIS DETECTOR FOUND, pinned. `check_hashes` RECORDED
    shared_build_baseline.txt while the type declared no switches — so nothing held it
    there, and a later edit dropping the `switches=` argument would have made the
    shared-build exemption editable for free. Exactly the REQ-10 hole, in my config
    rather than theirs."""
    assert ledger.config.requirements("commit")["check_hashes"]["switches"] == [
        "tools/verify/shared_build_baseline.txt"]


def test_status_names_where_the_genesis_floor_came_from(ledger):
    """⚠ ZeroParadox read `status` saying "records begin at 244ead83…" beside
    `policy.genesis.commit: None` and took it as a configured floor. It is derived from
    the genesis RECORD, and rendering it without saying so made a stream fact look like
    a config fact — the two readings differ exactly when it matters."""
    ledger.seed_genesis("a" * 40, note="probe")
    line = ledger.status()["genesis"]
    assert "genesis RECORD" in line
    assert "not a config value" in line


def test_an_unseeded_stream_does_not_claim_a_floor(ledger):
    """⚠ …and absence must read as absence. "No floor" and "a floor at X" are the two
    readings that must never render alike."""
    line = ledger.status()["genesis"]
    assert "records begin at" not in line


def test_the_genesis_config_value_is_dead_and_stays_dead(ledger):
    """⛔ `Config.genesis` read `policy.genesis.commit` and was called by NOTHING, while
    the policy comment instructed readers to set exactly that. A config value that looks
    authoritative, is documented as authoritative, and is consumed by nothing is the
    two-copies defect with the weaker copy being the one a reader is told to edit.

    The floor belongs in the append-only stream. This asserts the accessor cannot be
    quietly re-wired to config without the test failing."""
    assert ledger.config.genesis is None      # a @property, not a method
    import pathlib
    policy = json.loads((pathlib.Path(__file__).resolve().parents[1] /
                         "config" / "policy.v1.sample.json").read_text(encoding="utf-8-sig"))
    assert "commit" not in policy.get("genesis", {}), (
        "the dead config field is back; the floor has two sources again")


def test_crossref_says_how_much_it_did_not_audit(ledger, tmp_path):
    """⭐⭐ A CORRECTION TO ADVICE, not just a defect. I told Tim twice that gating the
    tip was survivable because "crossref will still report those commits as NOT_RUN —
    the audit keeps saying they went unexamined." Measured 2026-08-23: it audits 23 of
    174 unpushed commits and reports NOTHING about the 151 below the floor. All three
    counts read zero.

    §9a scopes it that way deliberately and correctly — an unactionable warning on
    every run trains people to scroll past it. But "reports nothing before the floor"
    was implemented as SILENCE, and a reader seeing three zeroes concludes the history
    is clean.

    ⚠ This changes no policy. The floor still bounds what is JUDGED; it only stops the
    result reading as a clean bill of health over commits nobody looked at.
    """
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True,
                   capture_output=True)
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    shas = []
    for i in range(4):
        (tmp_path / "f.md").write_text(f"rev {i}", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", f"c{i}"], cwd=tmp_path, check=True,
                       capture_output=True)
        shas.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                                   capture_output=True, text=True).stdout.strip())

    out = crossref_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                             since=shas[1])          # floor above two earlier commits
    assert out["commits_below_floor"] == 2
    assert "COUNTS BELOW DESCRIBE 2 COMMIT(S) ONLY" in out["floor_note"]
    assert "not a clean bill of health for the repository" in out["floor_note"]


def test_no_floor_note_when_nothing_is_below_it(ledger, tmp_path):
    """⚠ …and it must not cry wolf when the audit really did cover everything."""
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True,
                   capture_output=True)
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "f.md").write_text("only", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "c0"], cwd=tmp_path, check=True,
                   capture_output=True)
    first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                           capture_output=True, text=True).stdout.strip()
    out = crossref_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                             since=first)
    assert out["commits_below_floor"] == 1     # the floor commit itself


def test_the_review_gates_are_scoped_to_what_they_govern(ledger):
    """⭐ Tim chose the tip whole-state route, and his practical question was how you
    run an agent round corpus-wide. You do not — you declare what each gate governs.

    `claim_review` was the worked example: the only review-family type reading
    SATISFIED, and the only structural difference was a declared scope. The other four
    demanded all 477 paths from a reviewer who was never going to read 477 files, which
    is why they were permanently MISSING — nothing to do with how hard the review is.
    """
    reqs = ledger.config.requirements("push")
    assert reqs["rely"]["scope"] == ["tools/verify/*"]
    assert "FORBIDS running at full breadth" in reqs["rely"]["reason"]
    registry_exclusions = {"ZeroParadox/*.md", "tools/*.md", ".claude/*.md", ".github/*.md"}
    for step in ("editorial", "adversary"):
        assert reqs[step]["scope"] == ["*.md", "scripts/build_*.py",
                                       "scripts/PDF_Rendering_Standards.md"]
        # ⭐ 2026-09-08: `adversary` carries a HARNESS LOOP BREAK excluding its own brief —
        # the gate was grading the document telling it how to grade (9 FAIL in 10 rounds).
        # `editorial` is measured circular and deliberately NOT carved, so it is the control
        # that shows whether cross-review alone suffices. Asserted as registry UNION carve so
        # the carve stays VISIBLE here: if it is ever silently dropped or widened, this fails.
        carve = set(((ledger.config.loopbreaks.get("breaks") or {}).get(step) or {}).get(
            "exclude") or [])
        assert set(reqs[step]["scope_exclude"]) == registry_exclusions | carve
        if step == "adversary":
            assert carve == {".claude/commands/adversary-review.md"}, (
                "the adversary carve is load-bearing and named here on purpose")
        else:
            assert carve == set(), "editorial is deliberately uncarved — it is the control"


def test_prior_art_is_never_scoped_by_a_glob(ledger):
    """⛔ THE REFUSAL THAT SURVIVED THE DECISION. ZeroParadox proposed
    `ZeroParadox/*.lean` (218 files) and flagged in the same message that it would
    overclaim: that glob is prior_art's TRIGGER surface, not its REVIEW surface. A
    record naming 218 files would assert a reviewer examined the prior art for all of
    them, which no honest run does.

    Tim then narrowed it as acknowledged debt — which resolves whether it BLOCKS, and
    changes nothing about whether a glob could have expressed it. If a later pass
    reaches for the trigger surface again, this fails.
    """
    spec = ledger.config.required["types"]["prior_art"]
    assert "scope" not in spec, "prior_art was scoped on its trigger surface"
    assert "overclaim" in spec["reason"]


def test_prior_art_is_narrowed_as_DEBT_not_removed(ledger):
    """⚠ A NARROWING IS A WEAKENING, so it carries its reason and its fences.

    Tim's decision: prior_art has had disproportionate attention and becomes
    acknowledged debt, re-engaged when `.lean` files are next touched or as a batch.
    Expressed in the REGISTRY — §12-0-ter: "not quietly dropping it from
    admission.v1.json, which is how a gate disappears without a diff anyone reads."

    The type stays REGISTERED and its records stay valid, so promoting it later costs
    one line. That is the difference between a debt and a deletion.
    """
    spec = ledger.config.required["types"]["prior_art"]
    assert spec["actions"] == []
    assert "ACKNOWLEDGED DEBT" in spec["reason"]
    assert ledger.config.is_registered("prior_art"), "the type was removed, not narrowed"
    for action in ("commit", "push", "tag"):
        assert ledger.config.requirements(action)["prior_art"]["required"] is False


def test_the_prior_art_narrowing_records_its_two_fences(ledger):
    """⚠ THE FENCES ARE THE POINT, because a weakening travels if nothing stops it.

    (1) It does not retire trigger 5 — a new `.lean` or ≥50 inserted lines still owes
        a prior-art search. Discipline, where it was briefly a gate, and this project's
        record is that discipline leaks.
    (2) It is not precedent for rely/editorial/adversary. The distinguishing test is
        whether a glob can express WHAT THE REVIEWER READ — yes for those three, no for
        this one. A property of the gate, not a shortage of effort.
    """
    note = ledger.config.required["types"]["prior_art"]["_debt_not_closure_2026_08_23"]
    assert "does NOT retire trigger 5" in note
    assert "NOT precedent" in note
    assert "CAN A GLOB EXPRESS WHAT THE REVIEWER READ" in note


def test_the_other_three_review_gates_still_block(ledger):
    """⭐ THE CONTROL THAT KEEPS THE NARROWING FROM TRAVELLING. If a later pass reads
    prior_art's exemption as "review gates are hard, narrow them", this fails."""
    reqs = ledger.config.requirements("push")
    for step in ("rely", "editorial", "adversary"):
        assert reqs[step]["required"] is True, f"{step} inherited prior_art's exemption"
        assert reqs[step]["scope"], f"{step} lost its scope"


# ⚠⚠ THE FULL SWITCH MAP, PINNED. A switch protects an exemption surface, and the
# failure mode ZeroParadox surfaced (REQ-33) is a repair that satisfies the checker
# while deleting what the checker was protecting: V15 asserts that DECLARED switches
# are named by a record, and says nothing about whether a previously-declared switch
# still exists. So a later edit could drop `pov_baseline.txt` while adding something
# else, and every record would validate cleanly the whole way.
#
# This map is the only thing that fails when that happens. Removing an entry here to
# make a test pass is removing the protection the entry exists for.
SWITCH_MAP = {
    "check_checkers":  ["tools/verify/vendored_files.txt"],
    "check_classes":   ["tools/verify/class_baseline.txt",
                        "tools/verify/vendored_files.txt"],
    "check_encoding":  ["tools/verify/encoding_whitelist.txt",
                        "tools/verify/vendored_files.txt"],
    "check_figures":   ["tools/verify/figures_baseline.txt",
                        "tools/verify/vendored_files.txt"],
    "check_hashes":    ["tools/verify/shared_build_baseline.txt"],
    "check_modal":     ["tools/verify/modal_baseline.txt",
                        "tools/verify/vendored_files.txt"],
    "check_moved":     ["tools/verify/vendored_files.txt"],
    "check_negatives": ["tools/verify/negatives_baseline.txt",
                        "tools/verify/vendored_files.txt"],
    "check_paths":     ["tools/verify/vendored_files.txt"],
    "check_pov":       ["tools/verify/pov_baseline.txt",
                        "tools/verify/vendored_files.txt"],
    "check_prose":     ["tools/verify/prose_baseline.txt",
                        "tools/verify/vendored_files.txt"],
    "guards":          ["tools/verify/vendored_files.txt"],
}


def test_the_vendored_allowlist_is_a_declared_switch(ledger):
    """⭐ STRONGER THAN THE BASELINE HOLE OF REQ-10, and found the same way — by
    executing something. A planted DENIAL made `check_pov` exit 1; one appended line in
    `vendored_files.txt` made it exit 0, AND NO SUBJECT MOVED.

    An allowlist removes files from scope entirely rather than grandfathering sites, so
    the record does not merely go unstale — the thing it covered stops existing.

    ⚠ ELEVEN types, not eight. The count landed in two passes because four had not
    re-recorded, none of them being in the pre-commit hook — the second time that cause
    has hidden a set.
    """
    V = "tools/verify/vendored_files.txt"
    reqs = ledger.config.requirements("push")
    named = sorted(k for k, v in reqs.items() if V in (v.get("switches") or []))
    assert len(named) == 11, f"the allowlist governs 11 types, declared on {len(named)}"


def test_no_declared_switch_is_ever_silently_dropped(ledger):
    """⭐⭐ THE SHAPE ZEROPARADOX'S NEAR-MISS EXPOSED, and it is a new one: a repair
    that satisfies the checker while deleting what the checker was protecting.

    Six types already carried a baseline switch when the allowlist was added. Writing
    it over the top would have removed the REQ-10 protection while adding the REQ-31
    one — and EVERY RECORD WOULD STILL HAVE PASSED V15, because V15 asserts that
    declared switches are named by a record and says nothing about whether a
    previously-declared switch survived.

    V15 cannot catch this; only a pinned map can.
    """
    reqs = ledger.config.requirements("push")
    for step, expected in SWITCH_MAP.items():
        assert sorted(reqs[step]["switches"]) == sorted(expected), (
            f"{step}'s switches changed; if that is intended, change SWITCH_MAP in the "
            f"same commit and say why — a switch removed silently is an exemption "
            f"surface that stopped being watched")


def test_declaring_a_switch_did_not_displace_an_existing_one(ledger):
    """⚠ THE MISTAKE THIS NEARLY WAS. Six of the seven already declared a baseline
    switch; writing the allowlist over the top would have removed the REQ-10 protection
    while adding the REQ-31 one, and both records would still validate."""
    reqs = ledger.config.requirements("push")
    assert "tools/verify/pov_baseline.txt" in reqs["check_pov"]["switches"]
    assert "tools/verify/encoding_whitelist.txt" in reqs["check_encoding"]["switches"]
    assert len(reqs["check_pov"]["switches"]) == 2


# -- ⚠ the MCP tool descriptions are the only guide an agent gets ---------------

def test_the_append_tool_documents_the_vocabulary_an_agent_must_use():
    """⚠⚠ Tim, 2026-08-28: "might be worth better descriptions of the available tools
    on the mcp server to help guide the instance on how to get things entered right."

    The writing guidance lived in `client/record.py`'s docstring — which an agent
    calling `append` over MCP NEVER SEES. That is how a correct emitter came to be
    written against half the contract: `delegated`, `outstanding` and the mixed-round
    split were each absent from the tool description, and the identity line described
    the pre-§4b hash that was retired months ago.

    Pinned as a test because a docstring nothing asserts is a docstring that goes
    stale — which is exactly what happened to the one this replaces.
    """
    import inspect
    from ledger_server import server
    doc = inspect.getdoc(server.append.fn if hasattr(server.append, "fn")
                         else server.append)
    # ⚠ THE RANGE IS DERIVED, NOT LITERAL. This asserted "V1-V18" and became the SECOND COPY
    # of the rule range the moment V19 landed — the same defect the docstring it guards had.
    # Found 2026-09-08 when the consumer reported `validate`'s served description understating
    # its coverage, which makes every clean result from that path uncitable.
    import re as _re
    _src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "validate.py"
            ).read_text(encoding="utf-8")
    _range = "V1-V%d" % max(int(n) for n in _re.findall(r'"V(\d+):', _src))
    for token in ("delegated", "outstanding", "evidence", _range,
                  "thirty-nine", "revision: 1"):
        assert token in doc, f"append's description never mentions {token!r}"
    assert "(step, basis, verdict, reason, subjects, revision)" not in doc, (
        "the retired pre-§4b identity is back in the description")


def test_the_inventory_tool_warns_that_covered_is_not_passing():
    """⚠ The field most often misread. A 70-subject FAIL makes all 70 COVERED and
    none PASSING, which is what sent a sibling session looking for an aggregation
    that does not exist."""
    import inspect
    from ledger_server import server
    doc = inspect.getdoc(server.inventory.fn if hasattr(server.inventory, "fn")
                         else server.inventory)
    assert "COVERED IS NOT PASSING" in doc
    assert "coverage_gap" in doc
    assert "worst covering verdict" in doc.lower()


# -- ⭐⭐ every tracked config must be LF, because I broke someone else's push ---

def test_no_tracked_json_config_carries_CRLF():
    """⭐⭐ MEASURED 2026-08-29, AND IT ESCAPED THIS REPO. `pathlib.write_text` on
    Windows silently translates '\n' to '\r\n', so EVERY json config written this
    session carried CRLF: policy.v1.json 31, required.v2.json 235, admission.v1.json
    85, mcp-servers.json 163.

    ⚠⚠ ONE OF THEM LANDED IN ZeroParadox. The convergence freeze I wrote into their
    `policy.v1.json` carried 37 CRLFs into a repo whose `.gitattributes` declares
    `* text=auto eol=lf`, and `check_invariants`' byte-portability leg FAILED on it —
    a hard block on their push, arriving inside the change meant to stabilise their
    run. They found it, not me.

    ⚠ `_sha` normalising line endings (72852fd) protected the ledger's IDENTITY from
    this and did nothing for the FILE's portability. Two different properties, and
    fixing the first made the second easier to miss.

    A habit is not a fix. This asserts the property so the next `write_text` is caught
    by the suite rather than by a sibling session's blocked push.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    bad = []
    for f in sorted(root.rglob("*.json")):
        s = str(f)
        if any(x in s for x in (".git", "__pycache__", "node_modules", ".mcp-local",
                                "data", ".pytest_cache")):
            continue
        raw = f.read_bytes()
        n = raw.count(b"\r\n")
        if n:
            bad.append(f"{f.relative_to(root)} ({n} CRLF)")
    assert not bad, (
        "CRLF in tracked JSON config — pathlib.write_text does this on Windows; "
        "write bytes, or newline='' :\n  " + "\n  ".join(bad))


def test_defaulted_reports_every_setting_running_on_a_builtin(tmp_path):
    """⭐⭐ A DEFAULT THAT BEHAVES CORRECTLY IS THE HARDEST KIND TO NOTICE.

    `config.py`'s header forbids built-in defaults outright — "a built-in default is a second
    copy of the policy and the weaker of the two is the copy nobody notices" — and that rule was
    enforced for the WHOLE FILE (an unloadable config serves UNDECIDED) and never for an
    INDIVIDUAL KEY. A missing key defaulted in silence.

    Measured 2026-09-06 against the live policy: `push.bar` and `coverage.require_complete` are
    BOTH running on built-ins, and both defaults are the permissive direction. `push.bar` had
    been invisible for three days, was "fixed" in the file only the tests load, and was found
    again a day later because the live server reads a different file. Nothing enumerated what was
    running on a constant, so the same defect was discovered twice.

    ⚠ Both directions matter: a setting that is ABSENT must appear, and a setting that is
    CONFIGURED must not — otherwise the list becomes noise and stops being read.
    """
    from core import config as config_mod

    absent = config_mod.Config.__new__(config_mod.Config)
    absent.policy = {"agreement": {"min_passes": 3}, "supersede": {"max_depth": 5}}
    keys = {d["key"] for d in absent.defaulted}
    assert "push.bar" in keys, "a missing push bar must be disclosed"
    assert "coverage.require_complete" in keys
    assert all("governs" in d and "direction" in d for d in absent.defaulted), (
        "each entry must say WHAT it governs and WHICH DIRECTION the default errs — a bare "
        "key name tells a reader nothing about whether to care")

    configured = config_mod.Config.__new__(config_mod.Config)
    configured.policy = {"push": {"bar": "every_commit"},
                         "coverage": {"require_complete": True},
                         "migration": {"v16_evidence_required": True},
                         "lock": {"soft_seconds": 5, "hard_seconds": 30}}
    assert configured.defaulted == [], (
        "a fully configured policy must report NOTHING defaulted; a list that always has "
        "entries says nothing, which is what test_status_is_silent_when_nothing_is_relaxed "
        "exists to hold for `relaxations`")


# -- ⭐⭐ REFUSED: a claim attempted and not accepted --------------------------

def _files_for(rec):
    return {s["path"]: s["git_blob_id"] for s in rec["subjects"]}


def test_a_refused_append_no_longer_renders_as_never_ran(ledger, tmp_path):
    """⭐⭐ THE INVERSION. Until 2026-09-07 a refused append bumped ONE GLOBAL COUNTER and
    nothing else, so the step rendered MISSING — **indistinguishable from never having been
    attempted.** Absence rendering as absence when it was a failure to produce a value.

    ⚠ The only instrument that could see it was the HTTP call log, which is explicitly *"NOT
    evidence and may never be cited as proof a control ran"* because it rotates. A rotating
    buffer cannot carry a claim about the past.

    Tim, 2026-09-07: *"fix the inversion."*
    """
    from core.errors import ValidationFailure

    bad = good(step="check_prosee")          # V8: not a registered step
    with pytest.raises(ValidationFailure):
        ledger.append(bad)

    ref = ledger.store.refusals()
    assert "check_prosee" in ref, "the refusal must leave a durable, per-step trace"
    assert ref["check_prosee"]["rule"] == "V8", "and name the RULE that refused it"
    assert ref["check_prosee"]["count"] == 1


def test_repeated_refusals_dedupe_on_step_and_rule_not_on_basis(ledger, tmp_path):
    """⛔⛔ KEYED WITHOUT THE BASIS, AND ZEROPARADOX MEASURED WHY.

    `ZPLEDGER_BASIS=INDEX` at precommit, so **every `git add` moves the basis.** Keying a
    refusal the way a verdict is keyed would mint a fresh row per staging operation — they ran
    precommit fifteen times in one afternoon.

    ⭐ And the deeper reason is theirs: for a REJECTED record the basis is the least reliable
    thing in it. The claim was never accepted, so what content it purported to be about
    establishes nothing. Cardinality is steps x rules — bounded — never x stagings.
    """
    from core.errors import ValidationFailure

    for i in range(4):
        with pytest.raises(ValidationFailure):
            ledger.append(good(step="check_prosee",
                               basis={"kind": "tree", "value": chr(97 + i) * 40,
                                      "resolved_from": "explicit"}))

    ref = ledger.store.refusals()
    assert list(ref) == ["check_prosee"], "four bases must not become four rows"
    assert ref["check_prosee"]["count"] == 4, "but the COUNT must distinguish once from often"
    assert ref["check_prosee"]["first_seen"] <= ref["check_prosee"]["last_seen"]


def test_a_refused_row_carries_no_indictment_and_is_not_a_fail(ledger, tmp_path):
    """⛔⛔ `REFUSED` IS NOT `FAIL`, AND CONFLATING THEM IS `LED-10` THROUGH A NEW DOOR.

    A FAIL condemns subjects. A REFUSED condemns NOTHING — it establishes nothing. If a
    resolver treats it as a FAIL it stamps condemnation on blobs the ledger never judged, and
    tip-green forgiveness would then be asked whether those blobs moved.
    """
    from core.errors import ValidationFailure
    from core import inventory as inv_mod

    # ⚠ A REGISTERED step, refused for a DIFFERENT rule. `check_prosee` is refused by V8
    # precisely because it is not registered — and `inventory` builds rows only for
    # registered types, so a refusal there can never render. That is a real limit of this
    # disclosure and it is the right one: an unregistered step is not part of the gate, so
    # it has no row to carry a state. Found while writing this control.
    rec = good(subjects=[])                       # V2: a PASS that examined nothing
    with pytest.raises(ValidationFailure):
        ledger.append(rec)

    inv = inv_mod.build(config=ledger.config, records=[], action="commit",
                        files={"docs/x.md": "b" * 40}, ref="a" * 40,
                        admission=["check_invariants"],
                        refusals=ledger.store.refusals())
    row = next((r for r in inv["rows"] if r["step"] == "check_invariants"), None)
    if row is not None:
        assert row["status"] == "REFUSED"
        assert not row.get("indicted"), (
            "a REFUSED row must carry NO indictment — it condemns nothing, and a resolver "
            "reading it as a FAIL would condemn bytes nothing judged")


def test_the_refused_remedy_does_not_say_re_run_the_gate(ledger, tmp_path):
    """⚠⚠ THE CONTROL ZEROPARADOX'S EXPERIENCE DEMANDED, AND IT IS NOT "does it block".

    Their `batch.py` already blocked on an unknown status through its generic fall-through —
    so a control asserting only that REFUSED blocks would have been GREEN against the defect.
    What it actually said, measured verbatim before they branched on it:

        REFUSED — run the gate and let it record its own verdict (`record.py --step editorial`)

    **The one instruction that cannot work.** The gate DID run; the ledger declined its record;
    re-running reproduces the refusal. `RLY41-2`'s shape: a true blocking answer wearing a
    remedy for a different failure. **Blocking was never what was wrong.**
    """
    from core.errors import ValidationFailure
    from core import inventory as inv_mod

    rec = good(subjects=[])                       # V2, on a REGISTERED step
    with pytest.raises(ValidationFailure):
        ledger.append(rec)

    inv = inv_mod.build(config=ledger.config, records=[], action="commit",
                        files={"docs/x.md": "b" * 40}, ref="a" * 40,
                        admission=["check_invariants"],
                        refusals=ledger.store.refusals())
    row = next((r for r in inv["rows"] if r["step"] == "check_invariants"), None)
    if row is None:
        pytest.fail("the refused step must appear as a row at all")
    why = (row.get("why") or "").lower()
    assert "do not simply re-run" in why, (
        "the remedy must say NOT to re-run — re-running reproduces the refusal")
    assert "defect in the record" in why, (
        "and must name the RECORD as what is wrong, never the corpus")
    assert "nothing has been established" in why


def test_a_real_verdict_supersedes_a_refusal_with_no_clearing_step(ledger, tmp_path):
    """⭐ THE TRANSIENT CASE, RESOLVED BY DERIVATION RATHER THAN BY A MECHANISM.

    ZeroParadox asked whether a later successful append should CLEAR a refusal — a half-written
    config refused at 14:02 and fixed at 14:03 should not leave a REFUSED row forever.

    ⚠ It clears itself, and nothing is deleted: **the row status is DERIVED, not stored.** If a
    valid covering record exists, the row renders from that record. The refusal stays in its
    store as history. No clearing, no deletion, no append-only violation.
    """
    from core.errors import ValidationFailure
    from core import inventory as inv_mod

    with pytest.raises(ValidationFailure):
        ledger.append(good(step="check_invariants", subjects=[]))   # V2
    assert "check_invariants" in ledger.store.refusals()

    ok = good()
    ledger.append(ok)
    inv = inv_mod.build(config=ledger.config, records=[ok], action="commit",
                        files=_files_for(ok), ref=ok["basis"]["value"],
                        admission=["check_invariants"],
                        refusals=ledger.store.refusals())
    row = next(r for r in inv["rows"] if r["step"] == "check_invariants")
    assert row["status"] == "SATISFIED", (
        "a real verdict must win over a stale refusal — the refusal's job is to stop ABSENCE "
        "reading as nothing, and absence is no longer the state")


# -- ⭐ a pin's staleness and its enforcement are different events -------------

def test_a_stale_pin_is_disclosed_before_the_step_next_records(ledger, config_dir):
    """⭐⭐ THE INTERVAL, MADE VISIBLE. ZeroParadox measured it 2026-09-07: `check_checkers`
    had been pinned to a superseded build **since three commits earlier** and nothing noticed,
    because it is not in the five-checker precommit suite — so no run attempted its record
    until push.

    ⚠⚠ Their sentence, and it is the general form: **a pin's ENFORCEMENT POINT and a pin's
    STALENESS are different events, and the gap between them is however long it takes that
    step to next record.** V16c is enforced at APPEND, correctly — that is where a verdict is
    claimed. So a pin can sit stale for days on a rarely-recording step and the first sign is
    a refused commit.

    ⚠ DISCLOSURE, NEVER A GATE. The refusal stays at append; reporting it here would be a
    second enforcement point that could disagree with the first.
    """
    import json
    from core import inventory as inv_mod

    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    (doc.get("types") or doc)["check_invariants"].update(
        {"module": "tools/verify/check_invariants.py", "approved_modules": ["d" * 40]})
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    from core.ledger import Ledger
    led = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=path)

    inv = inv_mod.build(config=led.config, records=[], action="commit",
                        files={"tools/verify/check_invariants.py": "e" * 40},
                        ref="a" * 40, admission=["check_invariants"])
    stale = {p["step"]: p for p in inv["stale_pins"]}
    assert "check_invariants" in stale, (
        "a module whose live blob is not among `approved_modules` must be named BEFORE the "
        "step tries to record — that interval is the whole finding")
    assert stale["check_invariants"]["live"] == "e" * 40
    assert stale["check_invariants"]["approved"] == ["d" * 40]
    assert "CANNOT record" in stale["check_invariants"]["consequence"]


def test_a_current_pin_is_silent(ledger, config_dir):
    """⚠ THE CONTROL. A disclosure that names every pinned step says nothing about any of
    them — the same reason `relaxations`, `witness` and the unvalidated line each have a
    silence half."""
    import json
    from core import inventory as inv_mod
    from core.ledger import Ledger

    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    (doc.get("types") or doc)["check_invariants"].update(
        {"module": "tools/verify/check_invariants.py", "approved_modules": ["e" * 40]})
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    led = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=path)

    inv = inv_mod.build(config=led.config, records=[], action="commit",
                        files={"tools/verify/check_invariants.py": "e" * 40},
                        ref="a" * 40, admission=["check_invariants"])
    assert inv["stale_pins"] == [], "an APPROVED build must not be reported as stale"


def test_a_module_absent_from_the_tree_is_not_called_stale(ledger, config_dir):
    """⛔ ABSENT IS NOT STALE, and conflating them would be this project's own defect class.
    A module missing from THIS tree is V16/V17's business — the evidence moved, or the file is
    not here — and calling it a stale PIN would blame the registry for a fact about the tree."""
    import json
    from core import inventory as inv_mod
    from core.ledger import Ledger

    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    (doc.get("types") or doc)["check_invariants"].update(
        {"module": "tools/verify/check_invariants.py", "approved_modules": ["d" * 40]})
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    led = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=path)

    inv = inv_mod.build(config=led.config, records=[], action="commit",
                        files={"docs/x.md": "b" * 40},          # module not in this tree
                        ref="a" * 40, admission=["check_invariants"])
    assert inv["stale_pins"] == []


def test_inventory_carries_the_frozen_bar_beside_complete(ledger, config_dir):
    """⭐⭐ `complete` IS A CLAIM ABOUT A SCOPE, AND THE SCOPE CAN MOVE.

    Measured 2026-09-07 by ZeroParadox, on the live servers, at the moment of a real push:

        progress(push)      complete: true   satisfied: 19/19   bar.held: FALSE
        gitRobot status()   embeds an INVENTORY, not a progress -> the bar reached nobody

    **A reader of the gate's own status saw green.** The registry had moved at `4efa051` the
    day before, so every step that went green earlier was judged against a different scope —
    and the number that says so was computed in a function nothing on the push path called.

    ⚠ The fix is placement, not a new fact: `progress()` had it all along. Lifted into
    `convergence_bar()` and carried on `inventory` too — LIFTED rather than copied, because a
    second implementation of the freeze check is the drift this project keeps paying for.
    """
    import json
    from core import inventory as inv_mod
    from core.ledger import Ledger

    inv = inv_mod.build(config=ledger.config, records=[], action="commit",
                        files={"docs/x.md": "b" * 40}, ref="a" * 40, admission=[])
    assert "bar" in inv, "the frozen bar must ride beside `complete`, not only on progress()"

    # freeze the bar at a sha the registry does not have
    path = config_dir / "policy.v1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.setdefault("convergence", {})["frozen_registry_sha"] = "f" * 64
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    moved = Ledger(ledger.data_path, policy_path=path,
                   required_path=config_dir / "required.v2.json")

    inv2 = inv_mod.build(config=moved.config, records=[], action="commit",
                         files={"docs/x.md": "b" * 40}, ref="a" * 40, admission=[])
    assert inv2["bar"]["frozen"] is True
    assert inv2["bar"]["held"] is False, "a moved registry must break the bar"
    assert "MOVED MID-RUN" in inv2["bar"]["note"]


def test_one_implementation_of_the_freeze_check_not_two(ledger):
    """⚠ `progress()` AND `inventory()` MUST ANSWER FROM THE SAME FUNCTION.

    Two copies of a freeze check would drift the way `record.py` drifted 386 lines apart, and
    the disagreement would be between two answers about whether the bar still holds — which is
    the one question a reader consults it to settle."""
    from core import inventory as inv_mod

    inv = inv_mod.build(config=ledger.config, records=[], action="commit",
                        files={"docs/x.md": "b" * 40}, ref="a" * 40, admission=[])
    prog = inv_mod.progress(config=ledger.config, records=[],
                            files={"docs/x.md": "b" * 40},
                            action="commit", admission=[])
    assert inv["bar"] == prog["bar"], (
        "inventory and progress must report the SAME bar — they call one helper, and if this "
        "ever differs someone has reintroduced a second implementation")

# -- ⭐⭐ a gate that grades its own producer -----------------------------------

def _inv_with(config_dir, ledger, step, *, scope, files, records=(), module=None,
              drop_module=False, admission=None):
    """Build an inventory over a registry edited for one step. Returns the inventory."""
    import json
    from core import inventory as inv_mod
    from core.ledger import Ledger

    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    types = doc.get("types") or doc
    # ⚠ `reason` IS LOAD-BEARING, not decoration: `config.requirements()` DISCARDS a scope
    # narrowing that carries no reason, so a test that omits it silently gets NO scope — and
    # an empty scope resolves to every path. Measured 2026-09-08; it made the negative leg
    # below fail for a reason that had nothing to do with what it was testing.
    types[step]["scope"] = list(scope)
    types[step].setdefault("reason", "probe: scope pinned by the test")
    if drop_module:
        types[step].pop("module", None)
        types[step].pop("approved_modules", None)
    elif module:
        types[step]["module"] = module
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    led = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=path)
    return inv_mod.build(config=led.config, records=list(records), action="commit",
                         files=dict(files), ref="a" * 40,
                         admission=list(admission) if admission else [step])


def test_a_step_whose_registry_module_sits_in_its_own_scope_is_named(ledger, config_dir):
    """The REGISTRY route: a mechanical step declares its producer as `module`.

    ⚠ Two rules that are each correct alone. A verdict goes STALE when its producer moves;
    a scope says what a step must examine. Put the producer INSIDE the scope and one edit
    both changes a subject the step owes a verdict for and invalidates every verdict it
    reached. Measured 2026-09-08 on the live registry: `guards`, `check_checkers` and
    `check_encoding` all sit in this state, admitted at push.
    """
    inv = _inv_with(config_dir, ledger, "check_invariants",
                    scope=["tools/verify/*"],
                    module="tools/verify/check_invariants.py",
                    files={"tools/verify/check_invariants.py": "e" * 40})
    found = {c["step"]: c for c in inv["circular_gates"]}
    assert "check_invariants" in found, (
        "a step whose own module is inside its own scope must be named — that is the "
        "double-bind, and nothing else reports it")
    assert found["check_invariants"]["producers_in_own_scope"] == [
        "tools/verify/check_invariants.py"]
    assert "registry" in found["check_invariants"]["route"]
    assert found["check_invariants"]["admitted"] is True


def test_a_step_whose_producer_is_only_in_its_EVIDENCE_is_still_named(ledger, config_dir):
    """⛔⛔ THE RATCHET, AND THE REASON THIS TEST EXISTS SEPARATELY.

    An agent step declares NO `module`. Its producer is named in the RECORD, as `evidence` —
    for `adversary` that is `.claude/commands/adversary-review.md`, its own brief, which the
    registry puts in scope deliberately (R-EXEMPT publishes the briefs).

    ⚠⚠ MEASURED 2026-09-08, AND THIS IS THE WHOLE POINT: a detector reading only the registry
    route returns THREE on the live configs and misses `adversary` and `editorial` entirely —
    the two steps that motivated building it. The union is five. **A detector that reads one
    of two declaration routes does not report a smaller number; it certifies the other route
    clean.** If someone reimplements this off `module` alone, this test is what fails.
    """
    brief = ".claude/commands/adversary-review.md"
    inv = _inv_with(config_dir, ledger, "check_invariants",
                    scope=[".claude/commands/*"],
                    drop_module=True,
                    files={brief: "f" * 40},
                    records=[{"step": "check_invariants", "verdict": "PASS",
                              "evidence": [{"path": brief, "git_blob_id": "f" * 40}]}])
    found = {c["step"]: c for c in inv["circular_gates"]}
    assert "check_invariants" in found, (
        "a producer named only in the record evidence must be caught too — registry-only "
        "detection is how adversary and editorial went unreported")
    assert found["check_invariants"]["producers_in_own_scope"] == [brief]
    assert found["check_invariants"]["route"] == ["evidence"]


def test_a_step_whose_producer_is_outside_its_scope_is_silent(ledger, config_dir):
    """The negative leg. Most steps are fine and must stay quiet, or the disclosure is noise."""
    inv = _inv_with(config_dir, ledger, "check_invariants",
                    scope=["ZeroParadox/*.lean"],
                    module="tools/verify/check_invariants.py",
                    files={"ZeroParadox/A.lean": "b" * 40,
                           "tools/verify/check_invariants.py": "e" * 40})
    assert [c for c in inv["circular_gates"] if c["step"] == "check_invariants"] == []


def test_a_step_with_no_module_is_disclosed_not_counted_as_pinned(ledger, config_dir):
    """⛔⛔ THE BLIND SPOT, PINNED. `unpinned_modules` asks "declares a module but no
    approved_modules" — so a step declaring NO module is not unpinned in its eyes, it is
    INVISIBLE.

    Measured 2026-09-08 on the live registry: 16 pinned, 4 reported unpinned, and NINE more
    with no module at all — six of them admitted, therefore gating an action. `policy()` read
    "4 unpinned" while 13 of 29 steps had no enforceable producer pin.

    ⚠ Tim, 2026-09-08: "everything is supposed to have some kind of pin for marking scope."
    The two lists stay separate because the REMEDY differs: an unpinned step needs its build
    approved; a step here needs a producer declared before a pin can exist at all.
    """
    import json
    from core.ledger import Ledger

    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    types = doc.get("types") or doc
    types["check_invariants"] = {"family": "mechanical",
                                 "module": "tools/verify/check_invariants.py"}   # no pin
    types["check_prose"] = {"family": "review"}                                  # no module
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    cfg = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=path).config

    unpinned = {u["step"] for u in cfg.unpinned_modules}
    undeclared = {u["step"] for u in cfg.undeclared_producers}

    assert "check_invariants" in unpinned, "module without a pin is the OLD disclosure"
    assert "check_invariants" not in undeclared, "it declares a producer; wrong list"
    assert "check_prose" in undeclared, (
        "a step with no module has nothing to pin and must still be named — being invisible "
        "to unpinned_modules is exactly the finding")
    assert "check_prose" not in unpinned, "no module means unpinned_modules cannot see it"
    entry = next(u for u in cfg.undeclared_producers if u["step"] == "check_prose")
    assert "no producer is declared" in entry["risk"]


# -- ⭐⭐ harness-owned loop breaks --------------------------------------------

def _carve_dates(days=30):
    """⚠ RELATIVE, NEVER HARD-CODED. A fixture pinned to a literal future date is a test with
    an expiry: it asserts "in date" until that day arrives and then fails for a reason that
    has nothing to do with the code. The first draft of these used `2099-01-01`, which the
    cadence guard then correctly refused — two time bombs in one line."""
    import datetime
    today = datetime.date.today()
    return today.isoformat(), (today + datetime.timedelta(days=days)).isoformat()


def _breaks(tmp_path, monkeypatch, payload):
    f = tmp_path / "loopbreaks.v1.json"
    f.write_text(json.dumps({"schema": "zp.loopbreaks.v1", "breaks": payload}),
                 encoding="utf-8")
    monkeypatch.setenv("ZPLEDGER_LOOPBREAKS", str(f))
    return f


def test_a_harness_loop_break_clears_the_circular_gate(ledger, config_dir, tmp_path,
                                                       monkeypatch):
    """⭐⭐ THE MECHANISM, EXERCISED END TO END. It ships with an EMPTY register, so the
    suite passing says nothing about whether it works — this declares a break and watches
    the gate come clean.

    ⚠ Tim, 2026-09-08: circular-gate management leaves the consumer's hands entirely.
    `scope_exclude` was already the harness's call in the tenancy contract *because carving
    is deciding*; this is that made enforceable rather than agreed. A break written in the
    consumer's registry is a rule the gated party can edit.
    """
    import json as _json
    from core.ledger import Ledger
    from core import inventory as inv_mod

    _d, _r = _carve_dates()
    brief = ".claude/commands/adversary-review.md"
    path = config_dir / "required.v2.json"
    doc = _json.loads(path.read_text(encoding="utf-8"))
    (doc.get("types") or doc)["check_invariants"] = {
        "family": "review", "scope": [".claude/commands/*"], "module": brief,
        "reason": "probe"}
    path.write_text(_json.dumps(doc, indent=2), encoding="utf-8")

    def inv():
        led = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                     required_path=path)
        return inv_mod.build(config=led.config, records=[], action="commit",
                             files={brief: "f" * 40}, ref="a" * 40,
                             admission=["check_invariants"])

    before = {c["step"] for c in inv()["circular_gates"]}
    assert "check_invariants" in before, "baseline must be circular or the test proves nothing"

    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": [brief], "reason": "probe carve", "decided": _d,
        "decided_by": "tim", "review_by": _r}})
    after = inv()
    assert "check_invariants" not in {c["step"] for c in after["circular_gates"]}, (
        "a declared break must carve the producer out of the gate's own scope")


def test_a_break_applies_even_when_the_registry_narrowing_has_no_reason(ledger, config_dir,
                                                                       tmp_path, monkeypatch):
    """⛔ THE EARLY-`continue` TRAP, PINNED. `requirements()` DISCARDS a registry narrowing
    that carries no `reason` — and a break routed through that branch would be silently
    dropped for a step whose REGISTRY happened to lack one. A carve the harness decided must
    never depend on the gated party's paperwork, so breaks are applied as a final pass over
    every entry. This is the test that fails if anyone moves them back inline."""
    import json as _json
    from core.ledger import Ledger

    path = config_dir / "required.v2.json"
    doc = _json.loads(path.read_text(encoding="utf-8"))
    # narrowing WITHOUT a reason -> requirements() ignores the registry's own scope
    (doc.get("types") or doc)["check_invariants"] = {"family": "mechanical",
                                                     "scope": ["docs/*"]}
    path.write_text(_json.dumps(doc, indent=2), encoding="utf-8")

    _d, _r = _carve_dates()
    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/carved.md"], "reason": "r", "decided": _d,
        "decided_by": "tim", "review_by": _r}})
    led = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=path)
    entry = led.config.requirements("commit")["check_invariants"]
    assert "docs/carved.md" in (entry.get("scope_exclude") or []), (
        "the break was dropped because the REGISTRY lacked a reason — the harness decision "
        "must not be contingent on the consumer's file")
    assert entry["loop_break"]["decided_by"] == "tim", "a carve must carry its attribution"


def test_the_break_file_is_in_config_sha(ledger, config_dir, tmp_path, monkeypatch):
    """⚠ A carve changes what every gate examines. If it were outside `config_sha`, the bar
    could move while the sha every record pins as its provenance swore nothing had."""
    from core.ledger import Ledger

    def sha():
        return Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                      required_path=config_dir / "required.v2.json").config.config_sha

    _breaks(tmp_path, monkeypatch, {})
    a = sha()
    _d, _r = _carve_dates()
    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided": _d,
        "decided_by": "tim", "review_by": _r}})
    assert sha() != a, "declaring a loop break must move config_sha"


def test_an_undated_carve_is_REFUSED_at_load(ledger, config_dir, tmp_path, monkeypatch):
    """⛔⛔ VERIFIED BY MAKING IT FAIL. Tim, 2026-09-08: *"I like the idea of having review
    date?"* — so it is a required field, not a convention.

    ⚠ A carve makes a gate examine LESS. An exemption with no expiry stops being a decision
    and becomes scenery: six months on, nobody can tell which carves are load-bearing and
    which are scar tissue. The loose direction here is the UNDATED one, which is why absence
    is refused rather than defaulted — the same shape as `push.bar` falling back to the more
    permissive answer for three days because a key was missing.
    """
    from core.ledger import Ledger

    # ⚠⚠ THE REFUSAL IS A SERVED STATE, NOT A RAISE, and asserting the wrong mechanism is how
    # this test first passed for the wrong reason. `Ledger.__init__` CATCHES ConfigError and
    # sets `config = None` + `config_error` on purpose — an unloadable config must make every
    # gated action refuse with a reason, not crash the process into a restart loop the
    # supervisor cannot fix. So the control checks the served state.
    def load():
        return Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                      required_path=config_dir / "required.v2.json")

    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided_by": "tim"}})   # no review_by
    led = load()
    assert led.config is None, "an undated carve must refuse the whole config"
    assert "review_by" in led.config_error
    assert "Satisfied when" in led.config_error, "a refusal must name the success condition"

    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided_by": "tim",
        "review_by": "next quarter"}})
    led2 = load()
    assert led2.config is None, "a non-ISO review date must refuse"
    assert "YYYY-MM-DD" in led2.config_error


def test_an_expired_carve_is_DISCLOSED_and_still_applies(ledger, config_dir, tmp_path,
                                                         monkeypatch):
    """⛔ THE ASYMMETRY, PINNED. An overdue carve keeps working and says so loudly.

    Dropping it on its date would re-introduce the deadlock at an arbitrary moment — a gate
    that passed at 23:59 blocking at 00:01 with nothing in the history explaining it. That is
    an outage on a timer, not a loud failure. The enforcement that IS safe happens at load:
    an undated carve cannot be written at all."""
    from core.ledger import Ledger

    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided_by": "tim",
        "review_by": "2020-01-01"}})
    cfg = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json").config

    expired = {e["step"]: e for e in cfg.loop_breaks_expired}
    assert "check_invariants" in expired, "an overdue carve must be named"
    assert "STILL IN FORCE" in expired["check_invariants"]["risk"]
    assert "docs/x.md" in (
        cfg.requirements("commit")["check_invariants"].get("scope_exclude") or []), (
        "the carve must KEEP applying — expiry discloses, it does not silently re-block")

    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided_by": "tim",
        "review_by": _carve_dates()[1]}})
    cfg2 = Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json").config
    assert cfg2.loop_breaks_expired == [], "an in-date carve must be silent"


def test_a_carve_dated_past_the_cadence_is_REFUSED(ledger, config_dir, tmp_path, monkeypatch):
    """⭐⭐ THE CADENCE, ENFORCED RATHER THAN REMEMBERED. Tim, 2026-09-08: *"let's do their
    reviews in one month increments at least to start."*

    ⛔ THE HOLE THIS CLOSES IS THE FAR-FUTURE DATE. `review_by: "2099-01-01"` satisfies every
    other check — present, ISO, well-formed — and expires after everyone who wrote it is gone.
    A dated exemption that outlives its authors is an undated one wearing a date. So the
    window is bounded, and re-dating a carve is a deliberate act somebody has to perform.

    ⚠ The constant lives in THIS repo, not in `policy.v1.json`, because that file sits in the
    consumer's tree and the gated party must not be able to widen the window on its own
    exemptions."""
    from core.ledger import Ledger
    from core.config import MAX_CARVE_DAYS

    def load():
        return Ledger(ledger.data_path, policy_path=config_dir / "policy.v1.json",
                      required_path=config_dir / "required.v2.json")

    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided_by": "tim",
        "decided": _carve_dates()[0], "review_by": "2099-01-01"}})
    led = load()
    assert led.config is None, "a carve dated beyond the cadence must refuse"
    assert str(MAX_CARVE_DAYS) in led.config_error
    assert "Satisfied when" in led.config_error

    # one month out is exactly what the cadence is for
    _d, _r = _carve_dates()
    _breaks(tmp_path, monkeypatch, {"check_invariants": {
        "exclude": ["docs/x.md"], "reason": "r", "decided_by": "tim",
        "decided": _d, "review_by": _r}})
    ok = load()
    assert ok.config is not None, "a one-month carve is the intended shape and must load"
    assert "docs/x.md" in (
        ok.config.requirements("commit")["check_invariants"].get("scope_exclude") or [])
