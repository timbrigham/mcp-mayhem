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
    v = server.reconstruct_verdict(path="CLAIMS.md", git_blob_id=B)
    assert v["state"] == "recorded" and v["record"]["verdict"] == "FAIL"
    assert server.reconstruct_verdict(path="CLAIMS.md", git_blob_id=C)["state"] == "never_run"
    bad = server.ingest_reconstruct(path=str(tmp_path / "missing.jsonl"))
    assert bad["ok"] is False and bad["satisfied_when"]
