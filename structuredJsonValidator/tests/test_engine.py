"""End-to-end tests for the handler engine: operations, audit, drift detection."""

import json

import pytest

from consumers.lean import build_registry
from core.errors import IntegrityError, OperationError, ValidationError
from core import audit


def _reg(path):
    return build_registry(path)


def test_seal_then_verify_integrity_ok(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    assert reg.verify_integrity()  # returns the confirmed hash, truthy


def test_rename_operation_round_trips_and_chains_hashes(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    entry_id = "ZeroParadox/ZPE.lean::ZeroParadox.ZPE.t_snap_derived::L142"
    result = reg.apply("rename", {
        "id": entry_id,
        "new_qualified": "ZeroParadox.Domains.X.t_snap_derived",
        "new_file": "ZeroParadox/Domains/X.lean",
        "namespace": "ZeroParadox.Domains.X",
        "reason": "restructure",
    })
    assert result["entries_touched"] == [entry_id]
    # File still conforms and the integrity chain is intact after the write.
    assert reg.validate() == []
    assert reg.verify_integrity() == result["resulting_sha256"]
    entry = reg.get(entry_id)
    assert entry["disposition"] == "renamed"
    assert entry["new"]["qualified"] == "ZeroParadox.Domains.X.t_snap_derived"


def test_out_of_band_edit_is_detected(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    # Tamper with the file directly, bypassing the handler.
    doc = json.loads(sample_file.read_text(encoding="utf-8"))
    doc["entries"][0]["disposition"] = "present"
    sample_file.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        reg.verify_integrity()
    # And a subsequent operation must refuse to run on a drifted file.
    with pytest.raises(IntegrityError):
        reg.apply("mark_present", {"id": doc["entries"][0]["id"]})


def test_invalid_operation_does_not_write_or_audit(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    before_hash = reg.verify_integrity()
    before_audit_len = len(audit.read_records(reg.audit_path))
    # 'drop' without a reason violates §7 → postcondition fails → no write.
    with pytest.raises(ValidationError):
        reg.apply("drop", {"id": "ZeroParadox/ZPB.lean::ZeroParadox.ZPB.addVal_bot::L88", "reason": ""})
    assert reg.verify_integrity() == before_hash  # file unchanged
    assert len(audit.read_records(reg.audit_path)) == before_audit_len  # no audit record


def test_history_filters_by_entry(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    eid = "ZeroParadox/ZPB.lean::ZeroParadox.ZPB.addVal_bot::L88"
    reg.apply("annotate", {"id": eid, "role": "core"})
    recs = reg.history(eid)
    assert len(recs) == 1
    assert recs[0]["op"] == "annotate"
    assert reg.history() and len(reg.history()) >= 2  # seal + annotate


def test_unknown_operation_raises(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    with pytest.raises(OperationError):
        reg.apply("frobnicate", {"id": "x"})


def test_export_full_writes_deterministic_valid_artifact(sample_file, tmp_path):
    reg = _reg(sample_file)
    reg.seal()
    dest = tmp_path / "public" / "registry.json"
    result = reg.export_full(dest)

    assert dest.exists()
    assert result["entries"] == 2
    # The written bytes hash to what the audit record claims.
    from core import store
    assert store.sha256_hex(dest.read_bytes()) == result["export_sha256"]

    published = json.loads(dest.read_text(encoding="utf-8"))
    # Entries are sorted by id; keys are sorted recursively (fixed key order).
    ids = [e["id"] for e in published["entries"]]
    assert ids == sorted(ids)
    assert list(published.keys()) == sorted(published.keys())
    assert list(published["entries"][0].keys()) == sorted(published["entries"][0].keys())

    # A published artifact is itself a valid registry.
    assert _reg(dest).validate() == []

    # Re-exporting identical source yields byte-identical output (deterministic).
    dest2 = tmp_path / "public2" / "registry.json"
    reg.export_full(dest2)
    assert dest2.read_bytes() == dest.read_bytes()


def test_export_full_preserves_source_integrity_chain(sample_file, tmp_path):
    reg = _reg(sample_file)
    reg.seal()
    before = reg.verify_integrity()
    reg.export_full(tmp_path / "pub.json")
    # Exporting does not mutate the source; the integrity chain still verifies
    # and a subsequent write is not falsely flagged as drift.
    assert reg.verify_integrity() == before
    reg.apply("annotate", {"id": "ZeroParadox/ZPB.lean::ZeroParadox.ZPB.addVal_bot::L88", "role": "core"})
    assert reg.verify_integrity()


def test_export_full_refuses_invalid_source(sample_file, tmp_path):
    reg = _reg(sample_file)
    reg.seal()
    # Corrupt the source out of band into an invalid state.
    doc = json.loads(sample_file.read_text(encoding="utf-8"))
    doc["entries"][0]["disposition"] = "not-a-disposition"
    sample_file.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    dest = tmp_path / "pub.json"
    with pytest.raises(ValidationError):
        reg.export_full(dest)
    assert not dest.exists()  # nothing published


def test_export_full_refuses_drifted_source(sample_file, tmp_path):
    reg = _reg(sample_file)
    reg.seal()
    # Rewrite the file out of band with different formatting: still fully valid,
    # but the bytes (and thus hash) no longer match the sealed baseline → drift.
    doc = json.loads(sample_file.read_text(encoding="utf-8"))
    sample_file.write_text(json.dumps(doc, indent=4) + "\n", encoding="utf-8")
    dest = tmp_path / "pub.json"
    with pytest.raises(IntegrityError):
        reg.export_full(dest)
    assert not dest.exists()


def test_import_baseline_builds_conforming_document(tmp_path):
    path = tmp_path / "fresh.json"
    reg = _reg(path)
    scanner = [
        {"qualified": "A.b.c", "short": "c", "kind": "theorem",
         "file": "A/b.lean", "line": 10, "prefix": "b", "sorry_free": True},
        {"qualified": "A.b.d", "short": "d", "kind": "lemma",
         "file": "A/b.lean", "line": 20, "prefix": "b", "sorry_free": True},
    ]
    reg.apply("import_baseline", {
        "scanner_output": scanner,
        "anchor": {"branch": "origin/main", "commit": None, "tree": None},
        "files": 1,
    })
    assert reg.validate() == []
    entries = reg.find(disposition="pending")
    assert len(entries) == 2
    assert reg.verify_integrity()  # first write established the baseline hash
