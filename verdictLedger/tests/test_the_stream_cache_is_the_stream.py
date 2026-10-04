"""The stream cache must be indistinguishable from re-reading records.jsonl — only faster.

⭐ Tim, 2026-10-04: "the time is a factor of the storage of the verdict ledger." Measured: one append
cost ~15 s (five full re-parses plus a full inventory) on a 236.5 MB, 8,410-record stream. The cache
keeps every derived index current by folding only new bytes. records.jsonl stays the only truth,
so every test here compares the cache against a FRESH FULL PASS over the file.
"""

import json
import time

import pytest

from core import inventory as inv
from core import store as store_mod
from core.errors import Unavailable


def _rec(i, step="s", basis="b", rev=0, path=None, blob=None, verdict="PASS", seconds=None,
         ev_path="tools/x.py"):
    r = {"id": f"{step}@{basis}#{rev}-{i}", "step": step, "basis": {"value": basis},
         "revision": rev, "verdict": verdict, "run": {"config_sha": f"c{i % 3}"},
         "subjects": [{"path": path or f"p{i}.md", "git_blob_id": blob or f"{i:040x}"}],
         "evidence": [{"path": ev_path, "git_blob_id": "e" * 40}]}
    if seconds is not None:
        r["cost"] = {"seconds": seconds}
    return r


def _write(path, recs, mode="w"):
    with open(path, mode + "b") as f:
        for r in recs:
            f.write((json.dumps(r) + "\n").encode())


def _full_pass(path):
    """The ORIGINAL semantics: parse every line, compute every index from scratch."""
    s = store_mod.Store.__new__(store_mod.Store)
    s.path = path
    recs = list(s._iter())
    tips = {}
    for r in recs:
        key = (r.get("step"), (r.get("basis") or {}).get("value"))
        rev = r.get("revision", 0)
        e = tips.setdefault(key, {"latest": None, "revisions": {}})
        e["revisions"][rev] = r
        if e["latest"] is None or rev >= e["latest"].get("revision", 0):
            e["latest"] = r
    return recs, tips, inv._subject_index_fold(None, recs)


def _cached(path):
    st = store_mod.Store(path)
    recs = st.records()
    return list(recs), st.tips(), inv._subject_index(recs)


def test_two_store_instances_share_ONE_writer_lock(tmp_path):
    """⛔ The writer lock was per-instance while the server builds a Store per call — so it never
    serialised two appends on two calls. The torn-line race the module exists to prevent."""
    p = tmp_path / "r.jsonl"
    assert store_mod.Store(p)._lock is store_mod.Store(p)._lock
    assert store_mod.Store(p)._lock is not store_mod.Store(tmp_path / "other.jsonl")._lock


def test_incremental_appends_match_a_full_pass(tmp_path):
    p = tmp_path / "r.jsonl"
    _write(p, [_rec(i, step=f"s{i % 4}", basis=f"b{i % 5}", rev=i % 2,
                    path=f"p{i % 7}.md") for i in range(60)])
    assert _cached(p) == _full_pass(p)
    for k in range(5):
        _write(p, [_rec(100 + k, step="s1", basis="b2", rev=k, path="p3.md")], mode="a")
        assert _cached(p) == _full_pass(p), f"diverged after incremental append {k}"


def test_an_out_of_band_same_length_edit_rebuilds(tmp_path):
    """Tim's emergency-restoration case: an edit outside the tooling must never be served stale."""
    p = tmp_path / "r.jsonl"
    _write(p, [_rec(i) for i in range(20)])
    _cached(p)
    data = p.read_bytes()
    j = data.find(b'"PASS"', len(data) // 2)
    time.sleep(0.02)
    p.write_bytes(data[:j] + b'"FAIL"' + data[j + 6:])     # same length, mid-file
    recs, _, _ = _cached(p)
    assert [r["verdict"] for r in recs] == [r["verdict"] for r in _full_pass(p)[0]]
    assert "FAIL" in [r["verdict"] for r in recs], "the cache served the pre-edit stream"


def test_an_edit_plus_an_append_still_rebuilds(tmp_path):
    """The incremental path must not trust a prefix it did not re-verify."""
    p = tmp_path / "r.jsonl"
    _write(p, [_rec(i) for i in range(20)])
    _cached(p)
    data = p.read_bytes()
    j = data.find(b'"PASS"')
    time.sleep(0.02)
    p.write_bytes(data[:j] + b'"FAIL"' + data[j + 6:] + (json.dumps(_rec(99)) + "\n").encode())
    assert _cached(p) == _full_pass(p)


def test_a_corrupt_line_is_unavailable_and_then_recovers(tmp_path):
    p = tmp_path / "r.jsonl"
    _write(p, [_rec(i) for i in range(5)])
    _cached(p)
    with open(p, "ab") as f:
        f.write(b'{"torn": \n')
    with pytest.raises(Unavailable, match="corrupt at line 6"):
        store_mod.Store(p).records()
    data = p.read_bytes()
    time.sleep(0.02)
    p.write_bytes(data[: data.rfind(b'{"torn"')])            # repair
    assert len(store_mod.Store(p).records()) == 5


def test_a_held_snapshot_never_changes_under_a_later_append(tmp_path):
    """⚠ Copy-on-write: a reader iterating tips or the subject index while an append lands must
    see the state it started with."""
    p = tmp_path / "r.jsonl"
    _write(p, [_rec(i, step="s", basis="b", rev=0, path="x.md", blob="a" * 40) for i in range(1)])
    st = store_mod.Store(p)
    tips_before = st.tips()
    recs_before = st.records()
    idx_before = inv._subject_index(recs_before)
    key = ("s", "b")
    latest_before = tips_before[key]["latest"]
    revs_before = dict(tips_before[key]["revisions"])
    by_content_before = dict(idx_before[0])
    ev_by_subject_before = {k: set(v) for k, v in idx_before[5].items()}

    evidence_before = {k: set(v) for k, v in idx_before[3].items()}
    # ⚠ a NEW evidence path on the SAME subject key, so the fold must WRITE into the existing
    # inner sets — an append re-citing the same evidence changes nothing and proves nothing
    # (that version of this test let a no-copy-on-write mutant survive, 2026-10-04)
    _write(p, [_rec(9, step="s", basis="b", rev=1, path="x.md", blob="a" * 40,
                    ev_path="tools/y.py")], mode="a")
    st.tips(); idx_after = inv._subject_index(st.records())   # fold the append
    assert ("tools/y.py", "e" * 40) in idx_after[5][("s", "x.md", "a" * 40)], "fixture: no write"

    assert tips_before[key]["latest"] is latest_before
    assert tips_before[key]["revisions"] == revs_before
    assert idx_before[0] == by_content_before
    assert {k: set(v) for k, v in idx_before[5].items()} == ev_by_subject_before
    assert {k: set(v) for k, v in idx_before[3].items()} == evidence_before


def test_old_and_new_snapshots_each_get_their_OWN_index_in_any_order(tmp_path):
    """A records list taken BEFORE an append must never be answered with the index AFTER it, and
    asking the OLD one must not disturb the NEW one — in either order of asking."""
    p = tmp_path / "r.jsonl"
    _write(p, [_rec(i, path=f"p{i}.md") for i in range(3)])
    old = store_mod.Store(p).records()
    inv._subject_index(old)                                   # old state gets a folded index
    _write(p, [_rec(7, path="new.md")], mode="a")
    new = store_mod.Store(p).records()                        # advance the cache
    assert inv._subject_index(new) == inv._subject_index_fold(None, list(new))
    idx_old = inv._subject_index(old)
    assert not any(k[1] == "new.md" for k in idx_old[0]), "a stale snapshot got the newer index"
    assert idx_old == inv._subject_index_fold(None, list(old))
    # and the NEW snapshot is still right after the old one was asked
    _write(p, [_rec(8, path="newer.md")], mode="a")
    newer = store_mod.Store(p).records()
    assert inv._subject_index(newer) == inv._subject_index_fold(None, list(newer))
