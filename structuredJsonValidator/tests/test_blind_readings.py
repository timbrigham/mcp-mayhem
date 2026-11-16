"""The ``blind_readings`` collection and the ``reconstruct`` verdict (2026-11-15).

The consumer's /reconstruct gate blocks on UNDISPOSITIONED DIFF-1 items, never on
the reader's opinion. These tests pin the three properties that make that safe:

  * the index only ever EXTENDS the append-only JSONL (a rewritten line refuses);
  * every key is checked against the fields beside it (``key_kind`` is a claim);
  * a (path, blob) nobody read is ``never_run``, never an empty PASS.

⚠ Fixtures are synthetic. The consumer's real file carries absolute user paths and
this repository is public; the real file was ingested into a scratch copy of the
live store on 2026-11-15 and matched the producer's counts (1/61/28/1/2).
"""

import json

import pytest

from consumers.readings.views import verdict_for
from consumers.store import build_store
from core.errors import OperationError, ValidationError

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}
RUN = "r1"
A, B, C = "a" * 40, "b" * 40, "c" * 40      # Lean file blob, CLAIMS blob, an unread blob
BRIEF, PROMPT = "e" * 40, "f" * 40


def _store(tmp_path):
    s = build_store(tmp_path / "store.json")
    s.apply("declarations", "import_baseline", {"scanner_output": [
        {"qualified": "A.t", "short": "t", "kind": "theorem", "file": "A.lean",
         "line": 3, "prefix": "A"}], "anchor": ANCHOR})
    return s


def _decl_id(s):
    return s.find("declarations")[0]["id"]


def _run(**over):
    r = {"type": "run", "run_id": RUN, "commit": "1" * 40,
         "brief_path": ".claude/commands/reconstruct.md", "brief_blob": BRIEF,
         "reader_prompt_blob": PROMPT, "reader_prompt_store": "prompts/p.md",
         "reader_model": "m", "started_utc": "2026-11-15T21:00:00+00:00",
         "finished_utc": "2026-11-15T21:05:00+00:00", "diff1_count": 2,
         "examined": [{"path": "A.lean", "git_blob_id": A},
                      {"path": "CLAIMS.md", "git_blob_id": B}]}
    r.update(over)
    return r


def _decl(rid, **over):
    r = {"type": "decl", "run_id": RUN, "path": "A.lean", "git_blob_id": A,
         "decl": "A.t", "key_kind": "registry_id", "registry_id": rid,
         "is_example": False, "elaborated_type": "T", "blind_reading": "reads as T"}
    r.update(over)
    return r


def _diff(n, **over):
    r = {"type": "diff1", "run_id": RUN, "item_id": f"{RUN}#{n}", "path": "CLAIMS.md",
         "git_blob_id": B, "decl": f"row {n}", "line": 10 + n, "key_kind": "prose_line",
         "registry_id": None, "registry_id_reason": "prose, not a declaration",
         "prose": "claims more", "signature": "says less", "kind": "scope_widened",
         "kind_detail": None, "disposition": "open"}
    r.update(over)
    return r


def _disp(n, d, **over):
    r = {"type": "disposition", "run_id": RUN, "item_id": f"{RUN}#{n}", "disposition": d,
         "reason": f"{d} because", "decided_by": "tester", "utc": "2026-11-16T00:00:00+00:00"}
    r.update(over)
    return r


def _write(tmp_path, rows, name="run.jsonl"):
    p = tmp_path / name
    p.write_bytes(("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8"))
    return str(p)


def _base(s):
    return [_run(), _decl(_decl_id(s)), _diff(1), _diff(2)]


def _ingest(s, path):
    return s.apply("blind_readings", "ingest_reconstruct", {"path": path})


def _doc(s):
    return s.load()["collections"]["blind_readings"]


# -- ingest -------------------------------------------------------------------

def test_ingest_counts_every_line_type_and_validates(tmp_path):
    s = _store(tmp_path)
    r = _ingest(s, _write(tmp_path, _base(s) + [_disp(1, "carried")]))
    assert r["lines"] == {"run": 1, "decl": 1, "diff1": 2, "skipped": 0, "disposition": 1}
    assert r["touched_count"] == 4           # 1 run + 1 reading + 2 items
    assert s.validate() == []


def test_reingesting_the_same_bytes_is_a_no_op(tmp_path):
    s = _store(tmp_path)
    p = _write(tmp_path, _base(s))
    _ingest(s, p)
    before = s.load()
    assert _ingest(s, p)["touched_count"] == 0
    assert s.load() == before


def test_an_appended_disposition_extends_the_history(tmp_path):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s)))
    r = _ingest(s, _write(tmp_path, _base(s) + [_disp(2, "applied")], "v2.jsonl"))
    assert r["touched_count"] == 1
    item = next(e for e in _doc(s)["entries"] if e["id"] == f"{RUN}#2")
    assert [e["disposition"] for e in item["dispositions"]] == ["open", "applied"]


def test_a_rewritten_disposition_history_refuses(tmp_path):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s) + [_disp(2, "applied")]))
    with pytest.raises(OperationError, match="does not extend"):
        _ingest(s, _write(tmp_path, _base(s) + [_disp(2, "rejected")], "v2.jsonl"))


def test_a_changed_line_under_an_indexed_id_refuses(tmp_path):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s)))
    rows = _base(s)
    rows[2] = _diff(1, prose="quietly reworded")
    with pytest.raises(OperationError, match="different line"):
        _ingest(s, _write(tmp_path, rows, "v2.jsonl"))


def test_a_changed_run_line_refuses(tmp_path):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s)))
    rows = _base(s)
    rows[0] = _run(reader_model="other")
    with pytest.raises(OperationError, match="already indexed with different content"):
        _ingest(s, _write(tmp_path, rows, "v2.jsonl"))


def test_an_unknown_line_type_refuses_rather_than_skipping(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(OperationError, match="unknown line type"):
        _ingest(s, _write(tmp_path, _base(s) + [{"type": "verdict", "run_id": RUN}]))


def test_an_absent_registry_id_key_refuses_where_null_would_not(tmp_path):
    s = _store(tmp_path)
    rows = _base(s)
    del rows[2]["registry_id"]
    with pytest.raises(OperationError, match="registry_id"):
        _ingest(s, _write(tmp_path, rows))


def test_a_malformed_line_writes_nothing(tmp_path):
    s = _store(tmp_path)
    p = tmp_path / "bad.jsonl"
    good = "\n".join(json.dumps(r) for r in _base(s))
    p.write_bytes((good + "\n{not json\n").encode("utf-8"))
    with pytest.raises(OperationError, match="line 5"):
        _ingest(s, str(p))
    assert (s.load()["collections"].get("blind_readings") or {}).get("entries", []) == []


def test_a_disposition_for_an_unknown_item_refuses(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(OperationError, match="unknown item_id"):
        _ingest(s, _write(tmp_path, _base(s) + [_disp(9, "applied")]))


def test_rows_without_their_run_line_refuse(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(OperationError, match="no RUN line"):
        _ingest(s, _write(tmp_path, _base(s)[1:]))


# -- rules: every key is checked against the fields beside it ------------------

def test_a_dangling_registry_id_fails_validation(tmp_path):
    s = _store(tmp_path)
    rows = _base(s)
    rows[1] = _decl("not-a-real-id")
    with pytest.raises(ValidationError, match="names no declaration"):
        _ingest(s, _write(tmp_path, rows))


@pytest.mark.parametrize("over, match", [
    ({"key_kind": "registry_id", "registry_id": None}, "null registry_id"),
    ({"key_kind": "decl_name", "registry_id": None, "registry_id_reason": None},
     "needs registry_id_reason"),
    ({"line": None}, "keys on \\(path, blob, line\\)"),
])
def test_key_kind_must_agree_with_the_fields(tmp_path, over, match):
    s = _store(tmp_path)
    rows = _base(s)
    rows[2] = _diff(1, **over)
    with pytest.raises(ValidationError, match=match):
        _ingest(s, _write(tmp_path, rows))


def test_a_registry_id_under_a_line_key_is_refused(tmp_path):
    s = _store(tmp_path)
    rows = _base(s)
    rows[2] = _diff(1, registry_id=_decl_id(s))
    with pytest.raises(ValidationError, match="keyed on it"):
        _ingest(s, _write(tmp_path, rows))


def test_a_finding_on_bytes_the_run_did_not_read_is_refused(tmp_path):
    s = _store(tmp_path)
    rows = _base(s)
    rows[2] = _diff(1, git_blob_id=C)
    with pytest.raises(ValidationError, match="not in its run's `examined`"):
        _ingest(s, _write(tmp_path, rows))


def test_diff1_count_must_match_the_items(tmp_path):
    s = _store(tmp_path)
    rows = _base(s)
    rows[0] = _run(diff1_count=5)
    with pytest.raises(ValidationError, match="diff1_count says 5"):
        _ingest(s, _write(tmp_path, rows))


def test_a_decision_without_a_reason_is_refused(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValidationError, match="only 'open' may be"):
        _ingest(s, _write(tmp_path, _base(s) + [_disp(1, "rejected", reason="")]))


# -- the verdict ----------------------------------------------------------------

def _verdict(tmp_path, extra, path="CLAIMS.md", blob=B):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s) + extra))
    return verdict_for(_doc(s), path, blob)


def test_bytes_no_run_read_are_never_run_not_a_pass(tmp_path):
    v = _verdict(tmp_path, [], blob=C)
    assert v["state"] == "never_run" and v["record"] is None


def test_an_open_item_fails_and_names_the_path(tmp_path):
    rec = _verdict(tmp_path, [_disp(2, "carried")])["record"]
    assert rec["verdict"] == "FAIL" and rec["failing"] == ["CLAIMS.md"]
    assert "outstanding" not in rec


def test_an_applied_item_still_fails_its_own_blob(tmp_path):
    rec = _verdict(tmp_path, [_disp(1, "applied"), _disp(2, "rejected")])["record"]
    assert rec["verdict"] == "FAIL" and rec["failing"] == ["CLAIMS.md"]


def test_carried_items_ride_a_pass_as_ordinary(tmp_path):
    v = _verdict(tmp_path, [_disp(1, "carried"), _disp(2, "rejected")])
    rec = v["record"]
    assert rec["verdict"] == "PASS" and "failing" not in rec
    assert [o["severity"] for o in rec["outstanding"]] == ["ordinary"]
    assert f"{RUN}#1" in rec["outstanding"][0]["note"]
    assert f"{RUN}#2" in rec["reason"]                 # rejected: reason only
    assert v["dispositions"] == {"open": 0, "applied": 0, "carried": 1, "rejected": 1}


def test_an_examined_file_with_no_findings_passes(tmp_path):
    rec = _verdict(tmp_path, [], path="A.lean", blob=A)["record"]
    assert rec["verdict"] == "PASS" and "outstanding" not in rec


def test_the_record_is_delegated_and_names_brief_and_prompt(tmp_path):
    rec = _verdict(tmp_path, [])["record"]
    assert rec["step"] == "reconstruct" and rec["tier"] == "A"
    assert rec["decided"]["how"] == "delegated" and rec["decided"]["who"] == "reconstruct"
    assert {e["git_blob_id"] for e in rec["evidence"]} == {BRIEF, PROMPT}
    assert rec["subjects"] == [{"path": "CLAIMS.md", "git_blob_id": B}]


# -- the MCP wrappers ------------------------------------------------------------

def test_the_mcp_tools_ingest_and_answer(tmp_path, monkeypatch):
    from mcp_server import server
    s = _store(tmp_path)
    monkeypatch.setattr(server, "_store", lambda: s)
    r = server.ingest_reconstruct(path=_write(tmp_path, _base(s)))
    assert r["ok"] is True and r["lines"]["diff1"] == 2
    repo, _ = _repo(tmp_path, {_BRIEF_PATH: "brief\n"})
    # The fixture's brief blob is BRIEF, not this repo's, so the only run is old-brief:
    v = server.reconstruct_verdict(path="CLAIMS.md", git_blob_id=B, root=str(repo))
    assert v["state"] == "brief_moved" and v["superseded_runs"] == [RUN]
    assert server.reconstruct_verdict(path="CLAIMS.md", git_blob_id=C,
                                      root=str(repo))["state"] == "never_run"
    bad_root = server.reconstruct_verdict(path="CLAIMS.md", git_blob_id=B,
                                          root=str(tmp_path / "nowhere"))
    assert bad_root["ok"] is False and bad_root["satisfied_when"]
    bad = server.ingest_reconstruct(path=str(tmp_path / "missing.jsonl"))
    assert bad["ok"] is False and bad["satisfied_when"]


# -- burn-down: directory ingest (2026-11-16) -------------------------------------

def test_a_directory_is_one_transaction_over_every_run_file(tmp_path):
    s = _store(tmp_path)
    d = tmp_path / "runs"
    d.mkdir()
    (d / "prompts").mkdir()                          # ignored: not top level
    (d / "prompts" / "x.jsonl").write_bytes(b"{not json\n")
    _write(d, _base(s), "a.jsonl")
    _write(d, [_run(run_id="r2", diff1_count=0,
                    examined=[{"path": "A.lean", "git_blob_id": A}])], "b.jsonl")
    r = _ingest(s, str(d))
    assert r["files"] == 2 and r["lines"]["run"] == 2
    assert {x["run_id"] for x in _doc(s)["runs"]} == {RUN, "r2"}


def test_a_bad_line_in_any_file_refuses_the_whole_directory_and_names_it(tmp_path):
    s = _store(tmp_path)
    d = tmp_path / "runs"
    d.mkdir()
    _write(d, _base(s), "a.jsonl")
    (d / "b.jsonl").write_bytes(b"{not json\n")
    with pytest.raises(OperationError, match="b.jsonl line 1"):
        _ingest(s, str(d))
    assert (s.load()["collections"].get("blind_readings") or {}).get("runs", []) == []


# -- burn-down: coverage over a real tree ------------------------------------------

import subprocess  # noqa: E402

from consumers.readings.coverage import coverage  # noqa: E402

_BRIEF_PATH = ".claude/commands/reconstruct.md"


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=e@e.invalid",
                           "-c", "user.name=e", *a], check=True, capture_output=True,
                          text=True).stdout.strip()


def _repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x")
    return repo, {rel: _git(repo, "rev-parse", f"HEAD:{rel}") for rel in files}


def test_coverage_partitions_every_in_scope_file_into_four_states(tmp_path):
    repo, blob = _repo(tmp_path, {"Z/a.lean": "a\n", "Z/sub/b.lean": "b\n",
                                  "Z/c.lean": "c\n", "Z/d.lean": "d\n",
                                  "Z/notes.md": "n\n", _BRIEF_PATH: "brief\n"})
    cur, old = blob[_BRIEF_PATH], "9" * 40
    s = _store(tmp_path)

    def run(rid, brief, path, items=()):
        rows = [_run(run_id=rid, brief_blob=brief, diff1_count=len(items),
                     examined=[{"path": path, "git_blob_id": blob[path]}])]
        for n, d in enumerate(items, 1):
            rows.append(_diff(n, run_id=rid, item_id=f"{rid}#{n}", path=path,
                              git_blob_id=blob[path]))
            if d != "open":
                rows.append(_disp(n, d, run_id=rid, item_id=f"{rid}#{n}"))
        return rows

    rows = (run("pass", cur, "Z/a.lean", ["rejected"])
            + run("fail", cur, "Z/sub/b.lean", ["open"])
            + run("stale", old, "Z/c.lean"))
    d = tmp_path / "runs"
    d.mkdir()
    _write(d, rows, "all.jsonl")
    _ingest(s, str(d))
    cov = coverage(_doc(s), root=repo, ref="HEAD", scope=["Z/*.lean"])
    assert cov["counts"] == {"never_run": 1, "brief_moved": 1, "fail": 1, "pass": 1,
                             "total": 4}
    assert cov["files"]["fail"] == ["Z/sub/b.lean"]      # `*` crosses `/`, like the ledger
    assert cov["files"]["brief_moved"] == ["Z/c.lean"]
    assert cov["files"]["never_run"] == ["Z/d.lean"]
    assert cov["commit"] == _git(repo, "rev-parse", "HEAD")


def test_an_old_brief_run_cannot_decide_a_file_a_current_one_read(tmp_path):
    repo, blob = _repo(tmp_path, {"Z/a.lean": "a\n", _BRIEF_PATH: "brief\n"})
    s = _store(tmp_path)
    ex = [{"path": "Z/a.lean", "git_blob_id": blob["Z/a.lean"]}]
    rows = [_run(run_id="old", brief_blob="9" * 40, diff1_count=1, examined=ex),
            _diff(1, run_id="old", item_id="old#1", path="Z/a.lean",
                  git_blob_id=blob["Z/a.lean"]),
            _run(run_id="new", brief_blob=blob[_BRIEF_PATH], diff1_count=0, examined=ex)]
    _ingest(s, _write(tmp_path, rows))
    assert coverage(_doc(s), root=repo, ref="HEAD", scope=["Z/*.lean"])["counts"]["pass"] == 1


def test_coverage_refuses_an_empty_scope_and_a_bad_ref(tmp_path):
    repo, _ = _repo(tmp_path, {"Z/a.lean": "a\n"})
    doc = {"runs": [], "entries": []}
    with pytest.raises(OperationError, match="scope is empty"):
        coverage(doc, root=repo, ref="HEAD", scope=[])
    with pytest.raises(OperationError, match="failed"):
        coverage(doc, root=repo, ref="no-such-ref", scope=["Z/*.lean"])


# -- only current-brief runs decide, and only they are cited (2026-11-16) ---------

def test_the_verdict_cites_only_current_brief_runs(tmp_path):
    """⛔ The consumer's report: GapDecoder carried an old-brief run and a current one, and
    the served record cited BOTH briefs, so the ledger would have staled a record the
    current run had earned."""
    s = _store(tmp_path)
    ex = [{"path": "A.lean", "git_blob_id": A}]
    rows = [_run(run_id="old", brief_blob="9" * 40, reader_prompt_blob="8" * 40,
                 diff1_count=1, examined=ex),
            _diff(1, run_id="old", item_id="old#1", path="A.lean", git_blob_id=A),
            _run(run_id="new", diff1_count=0, examined=ex)]
    _ingest(s, _write(tmp_path, rows))
    current = {_BRIEF_PATH: BRIEF}
    v = verdict_for(_doc(s), "A.lean", A, current_briefs=current)
    assert v["runs"] == ["new"]
    assert {e["git_blob_id"] for e in v["record"]["evidence"]} == {BRIEF, PROMPT}
    assert v["record"]["verdict"] == "PASS"       # the old run's open item decides nothing
    unfiltered = verdict_for(_doc(s), "A.lean", A)
    assert unfiltered["record"]["verdict"] == "FAIL"   # the control: it was the filter


def test_only_old_brief_runs_is_brief_moved_not_a_record(tmp_path):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s)))
    v = verdict_for(_doc(s), "CLAIMS.md", B, current_briefs={_BRIEF_PATH: "0" * 40})
    assert v["state"] == "brief_moved" and v["record"] is None
    assert v["superseded_runs"] == [RUN]


def test_coverage_honours_scope_exclude(tmp_path):
    repo, _ = _repo(tmp_path, {"Z/a.lean": "a\n", "Z/Vendored/v.lean": "v\n"})
    doc = {"runs": [], "entries": []}
    cov = coverage(doc, root=repo, ref="HEAD", scope=["Z/*.lean"],
                   scope_exclude=["Z/Vendored/*"])
    assert cov["counts"]["total"] == 1 and cov["files"]["never_run"] == ["Z/a.lean"]
    assert coverage(doc, root=repo, ref="HEAD", scope=["Z/*.lean"])["counts"]["total"] == 2


# -- per-run split-round records, for the burn-down (2026-11-16) ------------------

from consumers.readings.views import run_records  # noqa: E402

D = "d" * 40


def _three_file_run(s, tmp_path, *, brief=BRIEF):
    """A.lean: one carried + one rejected. CLAIMS.md: one open. D.lean: no items."""
    ex = [{"path": "A.lean", "git_blob_id": A}, {"path": "CLAIMS.md", "git_blob_id": B},
          {"path": "D.lean", "git_blob_id": D}]
    rows = [_run(diff1_count=3, examined=ex, brief_blob=brief),
            _diff(1, path="A.lean", git_blob_id=A, kind_detail="prose says every X"),
            _diff(2, path="A.lean", git_blob_id=A),
            _diff(3),
            _disp(1, "carried"), _disp(2, "rejected")]
    _ingest(s, _write(tmp_path, rows))


def test_one_pass_over_decided_files_and_one_fail_over_open_ones(tmp_path):
    s = _store(tmp_path)
    _three_file_run(s, tmp_path)
    out = run_records(_doc(s), RUN, {_BRIEF_PATH: BRIEF})
    assert (out["files"], out["passed"], out["failed"], out["exceptions"]) == (3, 2, 1, [])
    p, f = out["records"]
    assert p["verdict"] == "PASS"
    assert [x["path"] for x in p["subjects"]] == ["A.lean", "D.lean"]
    assert f["verdict"] == "FAIL" and f["failing"] == ["CLAIMS.md"]
    # the FAIL's subjects are exactly what it indicts; decided bytes are not swept in
    assert [x["path"] for x in f["subjects"]] == ["CLAIMS.md"]
    assert f"{RUN}#2" in p["reason"]                               # rejected: reason only


def test_outstanding_carries_path_and_describes_the_finding(tmp_path):
    s = _store(tmp_path)
    _three_file_run(s, tmp_path)
    (o,) = run_records(_doc(s), RUN, {_BRIEF_PATH: BRIEF})["records"][0]["outstanding"]
    assert o == {"severity": "ordinary", "path": "A.lean",
                 "note": f"{RUN}#1 L11 scope_widened: prose says every X"}


def test_a_note_with_no_kind_detail_falls_back_to_the_signature(tmp_path):
    s = _store(tmp_path)
    _ingest(s, _write(tmp_path, _base(s) + [_disp(1, "carried"), _disp(2, "carried")]))
    v = verdict_for(_doc(s), "CLAIMS.md", B, current_briefs={_BRIEF_PATH: BRIEF})
    assert all(o["note"].endswith("signature: says less") for o in v["record"]["outstanding"])


def test_each_file_reads_the_same_grouped_as_alone(tmp_path):
    s = _store(tmp_path)
    _three_file_run(s, tmp_path)
    cur = {_BRIEF_PATH: BRIEF}
    out = run_records(_doc(s), RUN, cur)
    for rec in out["records"]:
        for sub in rec["subjects"]:
            alone = verdict_for(_doc(s), sub["path"], sub["git_blob_id"], current_briefs=cur)
            assert alone["record"]["verdict"] == rec["verdict"]


def test_an_old_brief_run_yields_exceptions_and_no_records(tmp_path):
    s = _store(tmp_path)
    _three_file_run(s, tmp_path)
    out = run_records(_doc(s), RUN, {_BRIEF_PATH: "0" * 40})
    assert out["records"] == [] and out["state"] == "no_records"
    assert [x["state"] for x in out["exceptions"]] == ["brief_moved"] * 3


def test_an_unknown_run_says_so(tmp_path):
    s = _store(tmp_path)
    assert run_records(_doc(s), "nope", {})["state"] == "unknown_run"
