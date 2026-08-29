"""Two defects found by the FIRST REAL RECORD through the new plumbing, 2026-08-25.

⚠⚠ NEITHER WAS REACHABLE FROM THE EXISTING SUITE, AND THAT IS THE POINT OF THIS FILE.
Every inventory test passes a `files` dict straight in, so `server._files` — the one
function that BUILDS that dict in production — had no coverage at all. And every
mechanical step's evidence files were already among its subjects, so evidence being
double-counted as coverage was invisible until a step arrived whose subjects and
evidence were disjoint.

`pdf_coupling` was that step: 40 root-level PDFs, evidence `batch.py` + `common.py`.
It reported `subjects_covered: 42` against `scope: 40`, and `STALE, covered 0` over
subjects that matched the index EXACTLY.
"""

import subprocess

import pytest

from conftest import good, set_policy
from core import inventory as inventory_mod


def _git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def tiny_repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@e.invalid")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("alpha\n", encoding="utf-8")
    (r / "b.txt").write_text("beta\n", encoding="utf-8")
    _git(r, "add", "a.txt", "b.txt")
    _git(r, "commit", "-q", "-m", "one")
    return r


# -- ⭐⭐ the staged basis returned the STAGE column, not the blob ---------------

def test_staged_returns_blob_ids_not_the_stage_column(tiny_repo, monkeypatch):
    """⭐⭐ `git ls-files -s` prints `<mode> <blob> <stage> TAB <path>` and
    `git ls-tree -r` prints `<mode> blob <sha> TAB <path>`. The blob is field 1 in one
    and field 2 in the other. Reading field 2 for both returned the STAGE — `0` for
    every unconflicted entry — so `ref="staged"` mapped all 503 tracked files to "0",
    no subject could ever match, and EVERY key at the staged basis read STALE for
    ever.

    ⚠ It failed CLOSED, which is exactly why it survived: an unsatisfiable gate and a
    correctly-blocking gate are indistinguishable from outside.
    """
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))

    staged = server._files("staged")
    assert set(staged) == {"a.txt", "b.txt"}
    assert len(set(staged.values())) == 2, f"stage column leaked: {staged}"
    for path, blob in staged.items():
        assert blob == _git(tiny_repo, "hash-object", "--", path).strip()
        assert blob not in ("0", "100644")


def test_staged_and_head_agree_when_nothing_is_staged(tiny_repo, monkeypatch):
    """⚠ THE CROSS-CHECK. Two commands, two layouts, one answer — a clean tree must
    give identical maps or one of the two parsers is wrong."""
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))
    assert server._files("staged") == server._files("HEAD")


def test_a_staged_edit_shows_the_new_blob_not_the_committed_one(tiny_repo, monkeypatch):
    """⭐ The whole reason the staged basis exists: it must describe what a commit
    WOULD carry, not what HEAD already does."""
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))
    (tiny_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    _git(tiny_repo, "add", "a.txt")
    assert server._files("staged")["a.txt"] != server._files("HEAD")["a.txt"]


# -- ⭐⭐ evidence is not coverage ----------------------------------------------

def _pdfish(ledger, files, subjects, evidence):
    rec = good(step="pdf_coupling", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": p, "git_blob_id": b} for p, b in subjects],
               evidence=[{"path": p, "git_blob_id": b} for p, b in evidence])
    rec["id"] = "pdf_coupling@t#0"
    return inventory_mod.build(config=ledger.config, records=[rec], action="push",
                               files=files, ref="t", admission=["pdf_coupling"])


def test_evidence_paths_are_never_counted_as_covered_subjects(ledger):
    """⭐⭐ FOUND BY ZEROPARADOX FROM ARITHMETIC ALONE: 40 subjects + 2 evidence
    reported `subjects_covered: 42` against `scope: 40`.

    ⚠ `covered > scope` should be impossible, and it rendered as a LARGER number —
    coverage looking better than it is, which is the direction that matters.

    ⚠ It hid everywhere else because for almost every mechanical step the evidence
    files are ALREADY subjects (`check_encoding` covers all tracked text files,
    `batch.py` and `common.py` among them), so the two deduped and the double count
    was invisible. This fixture is the disjoint case on purpose.
    """
    files = {"one.pdf": "p1", "two.pdf": "p2",
             "tools/verify/batch.py": "e1", "tools/verify/common.py": "e2"}
    inv = _pdfish(ledger, files,
                  subjects=[("one.pdf", "p1"), ("two.pdf", "p2")],
                  evidence=[("tools/verify/batch.py", "e1"),
                            ("tools/verify/common.py", "e2")])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert row["subjects_covered"] == 2
    assert row["subjects_covered"] <= row["scope"]
    assert row["status"] == "SATISFIED"


def test_evidence_is_not_reported_as_an_unscoped_subject(ledger):
    """⚠ The symmetric error: having removed evidence from `covered`, it must not
    reappear as "examined but unscoped" — a signal that fires on every mechanical
    record is one people scroll past."""
    files = {"one.pdf": "p1", "tools/verify/batch.py": "e1"}
    inv = _pdfish(ledger, files, subjects=[("one.pdf", "p1")],
                  evidence=[("tools/verify/batch.py", "e1")])
    assert inv["unscoped"] == []


# -- ⭐ the producer moving is a different fact from the corpus moving ----------

def test_a_moved_producer_stales_the_key_and_says_so(ledger):
    """⭐⭐ ZEROPARADOX'S EXACT QUESTION: does editing `common.py` stale a step via its
    EVIDENCE (correct — it is what V16/V17 are for) or via a phantom SUBJECT (wrong,
    and it misreports which content moved)? Merged in one bucket they were
    indistinguishable in the row."""
    files = {"one.pdf": "p1", "tools/verify/common.py": "MOVED"}
    inv = _pdfish(ledger, files, subjects=[("one.pdf", "p1")],
                  evidence=[("tools/verify/common.py", "e2")])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")

    assert row["status"] == "STALE"
    assert row["subjects_stale"] == 0, "no subject moved; the producer did"
    assert row["evidence_stale"] == 1
    assert row["evidence_moved"] == ["tools/verify/common.py"]
    assert "the producer changed" in row["why"]
    assert "re-run the step" in row["why"]


def test_a_moved_subject_is_not_blamed_on_the_producer(ledger):
    """⚠ THE CONTROL, in the other direction: when the CORPUS moves, the row must not
    say the producer did."""
    files = {"one.pdf": "MOVED", "tools/verify/common.py": "e2"}
    inv = _pdfish(ledger, files, subjects=[("one.pdf", "p1")],
                  evidence=[("tools/verify/common.py", "e2")])
    row = next(r for r in inv["rows"] if r["step"] == "pdf_coupling")
    assert row["status"] == "STALE"
    assert row["evidence_stale"] == 0
    assert "producer changed" not in (row["why"] or "")


# -- ⭐ ask git for the field BY NAME ------------------------------------------

def test_a_path_containing_spaces_survives(tiny_repo, monkeypatch):
    """⚠ `--format=%(objectname)%x09%(path)` is TAB-separated on purpose. Splitting
    on whitespace would break the moment a tracked path contained a space — and the
    breakage would look like an untracked file, not like a parse error."""
    from ledger_server import server
    monkeypatch.setattr(server, "REPO", str(tiny_repo))
    (tiny_repo / "a file with spaces.md").write_text("x\n", encoding="utf-8")
    _git(tiny_repo, "add", "a file with spaces.md")

    staged = server._files("staged")
    assert "a file with spaces.md" in staged
    assert staged["a file with spaces.md"] == _git(
        tiny_repo, "hash-object", "--", "a file with spaces.md").strip()


def test_an_empty_file_list_is_refused_not_served(tmp_path, monkeypatch):
    """⚠⚠ THE FAIL-QUIET THIS GUARD EXISTS FOR. An unsupported `--format` prints
    `fatal:` to stderr and NOTHING to stdout, so the parse would yield {} — every key
    MISSING, the gate unsatisfiable, and fail-closed in the way that hides. That is
    exactly how the stage-column bug survived: refused actions and an unsatisfiable
    gate are indistinguishable from outside.

    Simulated with a directory that is not a repository at all, which produces the
    same shape: non-zero exit, empty stdout."""
    from core.errors import Unavailable
    from ledger_server import server
    notrepo = tmp_path / "notrepo"
    notrepo.mkdir()
    monkeypatch.setattr(server, "REPO", str(notrepo))
    with pytest.raises(Unavailable, match="NOT served as an empty repository"):
        server._files("staged")


def test_both_commands_are_parsed_by_the_same_two_columns(tiny_repo, monkeypatch):
    """⭐ THE POINT OF `--format`: there is no per-command field position left to get
    wrong. The parse is identical for ls-files and ls-tree, so the two copies of it
    cannot drift the way they did."""
    import inspect
    from ledger_server import server
    src = inspect.getsource(server._files)
    assert "%(objectname)%x09%(path)" in src
    assert "parts[2]" not in src and "col=" not in src


# -- ⭐⭐ coverage: a green row over a fraction of its own scope -----------------

def _guardsish(ledger, files, examined, admission=("guards",)):
    rec = good(step="guards", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": p, "git_blob_id": files[p]} for p in examined],
               evidence=[{"path": "tools/verify/guards.py", "git_blob_id": "g" * 40}])
    rec["id"] = "guards@t#0"
    return inventory_mod.build(config=ledger.config, records=[rec], action="push",
                               files=files, ref="t", admission=list(admission))


def test_a_step_can_report_satisfied_over_almost_nothing(ledger):
    """⭐⭐ THE MEASURED STATE, 2026-08-25: `guards` recorded a PASS over FOUR subjects
    while declaring no scope — which under the strict default means it owes every
    tracked path — and the row read SATISFIED over 4 of 504.

    ⚠ This test asserts the DEFAULT behaviour, which is that it does NOT block. That
    was deliberate from the start (`subjects_unexamined` is "reported, not blocking")
    and it is why the state survived: the number was right there and nothing acted on
    it. Left as a test rather than a comment so the default is a decision on the
    record, not an omission."""
    files = {f"f{i}.md": f"b{i}" for i in range(50)}
    inv = _guardsish(ledger, files, examined=["f0.md", "f1.md"])
    row = next(r for r in inv["rows"] if r["step"] == "guards")
    assert row["status"] == "SATISFIED"
    assert row["subjects_unexamined"] == 48
    assert inv["complete"] is True, "the default does not block — that is the finding"


def test_enforcing_coverage_refuses_the_same_inventory(ledger, config_dir, tmp_path):
    """⭐⭐ TIM, 2026-08-25: "every file needs a complete set of actual successful gate
    analysis.. not just this historical checkoff." Same records, same tree, one policy
    value, opposite answer — and no restart."""
    from core.ledger import Ledger
    set_policy(config_dir, **{"coverage.require_complete": True})
    led = Ledger(tmp_path / "c.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    files = {f"f{i}.md": f"b{i}" for i in range(50)}
    inv = _guardsish(led, files, examined=["f0.md", "f1.md"])
    assert inv["complete"] is False
    assert next(r for r in inv["rows"]
                if r["step"] == "guards")["subjects_unexamined"] == 48


def test_full_coverage_passes_under_enforcement(ledger, config_dir, tmp_path):
    """⚠ THE CONTROL. Enforcement must be SATISFIABLE — a step that genuinely covers
    its scope still passes, or this is an outage with a policy flag."""
    from core.ledger import Ledger
    set_policy(config_dir, **{"coverage.require_complete": True})
    led = Ledger(tmp_path / "d.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    files = {f"f{i}.md": f"b{i}" for i in range(5)}
    inv = _guardsish(led, files, examined=list(files))
    assert inv["complete"] is True


def test_switches_no_longer_inflate_covered_past_scope(ledger):
    """⚠ `covered` is measured over scope ∪ switches, so reporting it against `scope`
    alone produced `covered > scope` — 22/21 for check_checkers, 43/42 for
    check_hashes, each inflated by its single switch file. The same shape ZeroParadox
    caught on evidence, arriving through the other member of the denominator."""
    files = {"register.md": "a", "tools/verify/shared_build_baseline.txt": "s"}
    rec = good(step="check_hashes", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": "register.md", "git_blob_id": "a"},
                         {"path": "tools/verify/shared_build_baseline.txt",
                          "git_blob_id": "s"}],
               evidence=[{"path": "tools/verify/check_hashes.py",
                          "git_blob_id": "h" * 40}])
    rec["id"] = "check_hashes@t#0"
    inv = inventory_mod.build(config=ledger.config, records=[rec], action="push",
                              files=files, ref="t", admission=["check_hashes"])
    row = next(r for r in inv["rows"] if r["step"] == "check_hashes")
    assert row["subjects_covered"] == 2
    assert row["judged"] == 2, "the number `covered` is actually out of"
    assert row["subjects_covered"] <= row["judged"]


# -- ⭐⭐ coverage_gap: the work order, asked again rather than cached ------------

def _gap(ledger, files, records, admission, **kw):
    return inventory_mod.coverage_gap(config=ledger.config, records=records,
                                      action="push", files=files,
                                      admission=list(admission), **kw)


def test_a_passing_record_at_current_content_discharges_a_path(ledger):
    """The baseline: covered at THESE bytes and PASSING means nothing is owed."""
    files = {"a.md": "b1", "b.md": "b2"}
    rec = good(step="decls", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": p, "git_blob_id": b} for p, b in files.items()])
    rec["id"] = "decls@t#0"
    out = _gap(ledger, files, [rec], ["decls"])
    assert out["total_missing"] == 0
    assert out["complete_steps"] == ["decls"]


def test_a_record_against_moved_bytes_does_not_discharge_it(ledger):
    """⭐⭐ THE DIFFERENCE FROM `coverage()`, and the reason this tool exists. That one
    asks "has ANY step ever named this path?" — which a stale record satisfies. Tim
    asked for everything at HEAD REANALYSED, so the question has to be about the bytes
    that are here now."""
    rec = good(step="decls", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": "a.md", "git_blob_id": "OLD"}])
    rec["id"] = "decls@t#0"
    out = _gap(ledger, {"a.md": "NEW"}, [rec], ["decls"])
    assert out["steps"][0]["missing"] == 1
    assert out["steps"][0]["paths"] == ["a.md"]
    # and the cruder question still says it is covered — which is why it is not this one
    assert inventory_mod.coverage(records=[rec], paths=["a.md"])["uncovered"] == 0


def test_a_failing_record_discharges_nothing_and_says_so(ledger):
    """⭐⭐ MEASURED 2026-08-25: editorial, adversary and rely each covered their whole
    scope and passed NONE of it. Counting a FAILED record as coverage would report
    work as done that must still be fixed — and the remedy is the opposite of the one
    for a stale step."""
    files = {"a.md": "b1"}
    rec = good(step="decls", verdict="FAIL", reason="three findings",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": "a.md", "git_blob_id": "b1"}])
    rec["id"] = "decls@t#0"
    out = _gap(ledger, files, [rec], ["decls"])
    step = out["steps"][0]
    assert step["missing"] == 1 and step["have"] == 0
    assert "fix the findings" in step["remedy"]
    assert "re-running changes nothing" in step["remedy"]


def test_a_stale_step_is_told_to_run_not_to_fix(ledger):
    """⚠ THE CONTROL ON THE REMEDY. The two states need opposite work, and a remedy
    that names the wrong one costs rounds — LED-2's lesson, in the work order."""
    rec = good(step="decls", verdict="PASS",
               basis={"kind": "tree", "value": "t", "resolved_from": "explicit"},
               subjects=[{"path": "a.md", "git_blob_id": "OLD"}])
    rec["id"] = "decls@t#0"
    out = _gap(ledger, {"a.md": "NEW"}, [rec], ["decls"])
    assert "run the step" in out["steps"][0]["remedy"]


def test_truncation_is_reported_never_silent(ledger):
    """⚠ A capped list that renders like a complete one is the failure this whole
    server exists to end."""
    files = {f"f{i}.md": "x" for i in range(30)}
    out = _gap(ledger, files, [], ["decls"], limit=10)
    step = out["steps"][0]
    assert len(step["paths"]) == 10
    assert step["truncated"] == 20
    assert step["missing"] == 30


# -- ⭐⭐ progress: is it converging, or is it a loop? --------------------------

def test_progress_shows_direction_not_just_a_snapshot(ledger):
    """⭐⭐ Tim, 2026-08-29: "my only concern is that you end up in some kind of a loop
    where you're not actually making progress." `inventory` answers "green now" and
    `coverage_gap` answers "which paths owe a PASS"; neither answers "is this getting
    better", and that is where a loop hides — every round looks identical because each
    snapshot is read on its own."""
    files = {"a.md": "b1"}
    mk = lambda v, n, at: dict(
        good(step="decls", verdict=v, reason=(None if v == "PASS" else "found things"),
             basis={"kind": "tree", "value": f"t{n}", "resolved_from": "explicit"},
             subjects=[{"path": "a.md", "git_blob_id": f"old{n}"}],
             run={"id": "r", "started": at, "config_sha": None}),
        id=f"decls@t{n}#0")
    recs = [mk("FAIL", 1, "2026-08-01T00:00"), mk("FAIL", 2, "2026-08-02T00:00"),
            mk("FAIL", 3, "2026-08-03T00:00")]
    out = inventory_mod.progress(config=ledger.config, records=recs, action="push",
                                 files=files, admission=["decls"], rounds=5)
    row = next(b for b in out["blocking"] if b["step"] == "decls")
    assert [h["verdict"] for h in row["history"]] == ["FAIL", "FAIL", "FAIL"]
    assert row["history"][0]["at"] < row["history"][-1]["at"], "newest last"


# -- ⭐⭐ the frozen bar: a scope freeze that is CHECKED, not remembered ---------

def _prog(led, frozen=None):
    if frozen is not None:
        set_policy_raw = led.config.policy
        set_policy_raw["convergence"] = {"frozen_registry_sha": frozen}
    return inventory_mod.progress(
        config=led.config, records=[], action="push",
        files={"a.md": "b1"}, admission=["decls"], rounds=3)


def test_no_freeze_is_reported_as_a_risk_not_as_silence(ledger):
    """⚠ An unfrozen run is not a neutral state: scope can widen mid-run, and a
    widened scope does NOT re-open a green row because coverage is keyed on content.
    Saying nothing would let that read as "nothing to worry about"."""
    out = _prog(ledger)
    assert out["bar"]["frozen"] is False
    assert "NO FROZEN BAR" in out["bar"]["note"]


def test_a_held_freeze_says_so(ledger):
    """⚠ Reported when clean too — "the bar held" is the statement a reader needs
    before trusting the numbers underneath it."""
    out = _prog(ledger, frozen=ledger.config.registry_sha)
    assert out["bar"]["held"] is True
    assert "unchanged since this run was frozen" in out["bar"]["note"]


def test_a_moved_bar_is_loud_and_says_the_numbers_mean_less(ledger):
    """⭐⭐ Tim, 2026-08-29: "no more random ass stuff getting into scope at a later
    point." Stating that as a rule makes it a convention someone remembers; recording
    the sha makes every `progress` call check it. The message must also say what the
    reader most needs: a green row will NOT re-open on its own, so the count below is
    now measuring against a scope nobody agreed to."""
    out = _prog(ledger, frozen="a-registry-that-no-longer-exists")
    assert out["bar"]["held"] is False
    assert "THE BAR MOVED MID-RUN" in out["bar"]["note"]
    assert "will NOT re-open" in out["bar"]["note"]


def test_the_freeze_keys_on_the_registry_not_the_composite(ledger, config_dir,
                                                           tmp_path):
    """⚠⚠ SCOPE LIVES IN THE REGISTRY, so the freeze must not fire on a THRESHOLD
    change. `config_sha` covers policy.v1.json too — keying on it would turn every
    min_passes tweak into "the scope moved", and a freeze that cries wolf gets ignored
    while still reading as protection."""
    from core.ledger import Ledger
    before_registry = ledger.config.registry_sha
    before_config = ledger.config.config_sha
    set_policy(config_dir, **{"agreement.min_passes": 4})
    after = Ledger(tmp_path / "f.jsonl", policy_path=config_dir / "policy.v1.json",
                   required_path=config_dir / "required.v2.json")
    assert after.config.registry_sha == before_registry, "a threshold moved the scope sha"
    assert after.config.config_sha != before_config, "the composite should have moved"
