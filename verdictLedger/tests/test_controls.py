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
    minimal = "check_paths"
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
    ledger.append(good(step="check_paths",
                       subjects=[{"git_blob_id": "b" * 40, "path": "x.lean"}]))
    recs = ledger.store.records()
    fresh = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "b" * 40})
    moved = inventory_mod.build(config=ledger.config, records=recs, action="commit",
                                files={"x.lean": "c" * 40})
    assert next(r for r in fresh["rows"]
                if r["step"] == "check_paths")["status"] == "SATISFIED"
    stale = next(r for r in moved["rows"] if r["step"] == "check_paths")
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
                         "config" / "policy.v1.json").read_text(encoding="utf-8-sig"))
    assert "commit" not in policy.get("genesis", {}), (
        "the dead config field is back; the floor has two sources again")
