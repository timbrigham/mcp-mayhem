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


def test_import_baseline_ingests_a_file_path(tmp_path):
    # The bulk-init form: scanner_output given as a path the op reads itself.
    scanner = [
        {"qualified": "A.b.c", "short": "c", "kind": "theorem",
         "file": "A/b.lean", "line": 10, "prefix": "b", "sorry_free": True},
        {"qualified": "A.d.e", "short": "e", "kind": "lemma",
         "file": "A/d.lean", "line": 20, "prefix": "d", "sorry_free": True},
    ]
    scan_path = tmp_path / "scanner_output.json"
    scan_path.write_text(json.dumps(scanner, ensure_ascii=False), encoding="utf-8")

    anchor = {"branch": "origin/main", "commit": None, "tree": None}

    # Inline and path forms must yield the same conforming document.
    reg_inline = _reg(tmp_path / "inline.json")
    reg_inline.apply("import_baseline", {"scanner_output": scanner, "anchor": anchor})
    reg_path = _reg(tmp_path / "frompath.json")
    reg_path.apply("import_baseline", {"scanner_output": str(scan_path), "anchor": anchor})

    inline_doc = reg_inline.load()
    path_doc = reg_path.load()

    # Ids are minted surrogates (Decision A) so they differ between imports, but
    # the natural content (everything except id) must be identical.
    def _no_id(doc):
        return [{k: v for k, v in e.items() if k != "id"} for e in doc["entries"]]
    assert _no_id(path_doc) == _no_id(inline_doc)
    assert path_doc["counts"] == {"files": 2, "declarations": 2}  # derived, not 0

    # Every id is an opaque surrogate, not the old file::qualified::Lline key.
    import uuid
    for e in path_doc["entries"]:
        assert uuid.UUID(e["id"])  # parses as a UUID
        assert "::" not in e["id"]

    # The audit record keeps the path, not the inflated inline list.
    rec = audit.read_records(reg_path.audit_path)[-1]
    assert rec["params"]["scanner_output"] == str(scan_path)


def test_import_baseline_missing_file_is_operation_error(tmp_path):
    reg = _reg(tmp_path / "fresh.json")
    with pytest.raises(OperationError):
        reg.apply("import_baseline", {
            "scanner_output": str(tmp_path / "does_not_exist.json"),
            "anchor": {"branch": "origin/main", "commit": None, "tree": None},
        })
    assert not (tmp_path / "fresh.json").exists()  # nothing written on failure


# -- terminal-state guard (interop issue #4, strict) --------------------------

_PENDING_ID = "ZeroParadox/ZPE.lean::ZeroParadox.ZPE.t_snap_derived::L142"
_RENAMED_ID = "ZeroParadox/ZPB.lean::ZeroParadox.ZPB.addVal_bot::L88"


def test_dropped_entry_is_terminal(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    reg.apply("drop", {"id": _PENDING_ID, "reason": "obsolete"})
    before = reg.verify_integrity()
    # A later verb must not silently reverse the drop.
    with pytest.raises(OperationError):
        reg.apply("rename", {"id": _PENDING_ID, "new_qualified": "X.y",
                             "new_file": "X.lean", "namespace": "X", "reason": "oops"})
    assert reg.get(_PENDING_ID)["disposition"] == "dropped"
    assert reg.verify_integrity() == before  # refused op did not write


def test_force_overrides_terminal_guard(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    reg.apply("drop", {"id": _PENDING_ID, "reason": "obsolete"})
    reg.apply("rename", {"id": _PENDING_ID, "new_qualified": "X.y", "new_file": "X.lean",
                         "namespace": "X", "reason": "actually keeping it", "force": True})
    assert reg.get(_PENDING_ID)["disposition"] == "renamed"
    assert reg.validate() == []


def test_reopen_returns_terminal_entry_to_pending(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    reg.apply("drop", {"id": _PENDING_ID, "reason": "obsolete"})
    reg.apply("reopen", {"id": _PENDING_ID, "reason": "brought back"})
    entry = reg.get(_PENDING_ID)
    assert entry["disposition"] == "pending"
    assert entry["new"]["qualified"] is None  # new.* cleared
    assert reg.validate() == []
    # After reopen the normal verbs work again without force.
    reg.apply("mark_present", {"id": _PENDING_ID})
    assert reg.get(_PENDING_ID)["disposition"] == "present"


def test_merged_entry_is_terminal(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    # Both sample entries are non-terminal (pending, renamed) → mergeable.
    reg.apply("merge", {"ids": [_PENDING_ID, _RENAMED_ID],
                        "target": {"qualified": "Z.merged", "file": "Z.lean",
                                   "namespace": "Z"}, "reason": "unify"})
    assert reg.get(_PENDING_ID)["disposition"] == "merged"
    with pytest.raises(OperationError):
        reg.apply("move", {"id": _PENDING_ID, "new_file": "elsewhere.lean"})


def test_reopen_rejects_non_terminal(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    with pytest.raises(OperationError):
        reg.apply("reopen", {"id": _PENDING_ID, "reason": "nothing to reopen"})


def test_split_source_is_terminal(sample_file):
    reg = _reg(sample_file)
    reg.seal()
    reg.apply("split", {"id": _PENDING_ID,
                        "targets": [{"qualified": "A.one", "file": "A.lean", "namespace": "A"},
                                    {"qualified": "A.two", "file": "A.lean", "namespace": "A"}],
                        "reason": "one decl became two"})
    assert reg.get(_PENDING_ID)["disposition"] == "split"
    # A split source is spent, like merged — refuse a later mutation.
    with pytest.raises(OperationError):
        reg.apply("rename", {"id": _PENDING_ID, "new_qualified": "A.three",
                             "new_file": "A.lean", "namespace": "A", "reason": "no"})
    # reopen brings it back to pending.
    reg.apply("reopen", {"id": _PENDING_ID, "reason": "undo the split"})
    assert reg.get(_PENDING_ID)["disposition"] == "pending"


# -- founding-once guard (interop issue #5) -----------------------------------

def _scan(n_files):
    return [{"qualified": f"A.d{i}", "short": f"d{i}", "kind": "def",
             "file": f"F{i % n_files}.lean", "line": i, "prefix": "A", "sorry_free": True}
            for i in range(4)]


def test_import_baseline_refuses_non_empty_registry(tmp_path):
    path = tmp_path / "reg.json"
    reg = _reg(path)
    anchor = {"branch": "origin/main", "commit": None, "tree": None}
    reg.apply("import_baseline", {"scanner_output": _scan(2), "anchor": anchor})
    # Curate something so we can prove it survives the refused re-import.
    curated_id = reg.find(disposition="pending")[0]["id"]
    reg.apply("annotate", {"id": curated_id, "role": "core"})
    before = reg.verify_integrity()

    with pytest.raises(OperationError):
        reg.apply("import_baseline", {"scanner_output": _scan(2), "anchor": anchor})

    assert reg.verify_integrity() == before  # nothing written
    assert reg.get(curated_id)["ontology"]["role"] == "core"  # curation intact


def test_import_baseline_force_overwrites(tmp_path):
    path = tmp_path / "reg.json"
    reg = _reg(path)
    anchor = {"branch": "origin/main", "commit": None, "tree": None}
    reg.apply("import_baseline", {"scanner_output": _scan(2), "anchor": anchor})
    reg.apply("import_baseline", {"scanner_output": _scan(2), "anchor": anchor, "force": True})
    assert reg.validate() == []
    assert len(reg.find(disposition="pending")) == 4  # replaced, all pending again


# -- terse write receipt (interop issue #6) -----------------------------------

def test_write_receipt_is_terse_for_bulk_but_echoes_small(tmp_path):
    path = tmp_path / "reg.json"
    reg = _reg(path)
    anchor = {"branch": "origin/main", "commit": None, "tree": None}
    big_scan = [{"qualified": f"A.d{i}", "short": f"d{i}", "kind": "def",
                 "file": "F.lean", "line": i, "prefix": "A", "sorry_free": True}
                for i in range(40)]  # > 25 -> id echo suppressed
    result = reg.apply("import_baseline", {"scanner_output": big_scan, "anchor": anchor})
    assert result["touched_count"] == 40
    assert "entries_touched" not in result  # bulk receipt stays terse
    # But the audit log still keeps the full touched list.
    last = audit.read_records(reg.audit_path)[-1]
    assert len(last["entries_touched"]) == 40
    # Small op: id is echoed for convenience.
    eid = reg.find(disposition="pending")[0]["id"]
    small = reg.apply("annotate", {"id": eid, "role": "core"})
    assert small["touched_count"] == 1
    assert small["entries_touched"] == [eid]


# -- reconcile / surrogate ids (interop issue #5, Decisions A & B) -------------

_ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}


def _found(reg, scan):
    reg.apply("import_baseline", {"scanner_output": scan, "anchor": _ANCHOR})


def _by_q(reg, qualified):
    """Fetch the single entry whose effective-current name is `qualified`."""
    for e in reg.find():
        eff = e["new"]["qualified"] if e["disposition"] in ("renamed", "new") else e["old"]["qualified"]
        if eff == qualified:
            return e
    return None


def test_reconcile_updates_location_and_preserves_curation(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.b", "short": "b", "kind": "def",
                  "file": "old.lean", "line": 10, "prefix": "A"}])
    eid = reg.find()[0]["id"]
    reg.apply("annotate", {"id": eid, "role": "core", "domain": "number"})

    # Same decl, moved to a new file/line — must be a location UPDATE, not add.
    res = reg.apply("reconcile", {"scanner_output": [
        {"qualified": "A.b", "short": "b", "kind": "def", "file": "new.lean", "line": 42, "prefix": "A"}]})

    entry = reg.get(eid)  # SAME surrogate id survived
    assert entry is not None
    assert entry["old"]["file"] == "new.lean" and entry["old"]["line"] == 42  # relocated
    assert entry["disposition"] == "pending"
    assert entry["ontology"]["role"] == "core" and entry["ontology"]["domain"] == "number"  # curation kept
    assert res["drift"]["location_updated"] == 1
    assert res["drift"]["vanished"] == [] and res["drift"]["phantom"] == []
    assert len(reg.find()) == 1  # no drop+add


def test_reconcile_flags_vanished_without_dropping(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.keep", "short": "keep", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"},
                 {"qualified": "A.gone", "short": "gone", "kind": "def", "file": "f.lean", "line": 2, "prefix": "A"}])
    res = reg.apply("reconcile", {"scanner_output": [
        {"qualified": "A.keep", "short": "keep", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}]})
    flagged = res["drift"]["vanished"]
    assert [f["qualified"] for f in flagged] == ["A.gone"]
    assert _by_q(reg, "A.gone") is not None  # still present, only flagged
    assert len(reg.find()) == 2


def test_reconcile_adds_phantom_as_pending_and_flags(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.x", "short": "x", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}])
    res = reg.apply("reconcile", {"scanner_output": [
        {"qualified": "A.x", "short": "x", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"},
        {"qualified": "A.new", "short": "new", "kind": "def", "file": "f.lean", "line": 9, "prefix": "A"}]})
    assert [p["qualified"] for p in res["drift"]["phantom"]] == ["A.new"]
    added = _by_q(reg, "A.new")
    assert added is not None and added["disposition"] == "pending"


def test_reconcile_flags_resurrection_of_dropped(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.z", "short": "z", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}])
    reg.apply("drop", {"id": reg.find()[0]["id"], "reason": "gone for now"})
    res = reg.apply("reconcile", {"scanner_output": [
        {"qualified": "A.z", "short": "z", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}]})
    assert [r["qualified"] for r in res["drift"]["resurrection"]] == ["A.z"]


def test_reconcile_does_not_guess_rename(tmp_path):
    # A qualified-name change with no recorded rename is indistinguishable from
    # delete+add: flag the vanished name AND the phantom, never silent-match.
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.oldname", "short": "oldname", "kind": "def",
                  "file": "f.lean", "line": 1, "prefix": "A"}])
    res = reg.apply("reconcile", {"scanner_output": [
        {"qualified": "A.newname", "short": "newname", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}]})
    assert [v["qualified"] for v in res["drift"]["vanished"]] == ["A.oldname"]
    assert [p["qualified"] for p in res["drift"]["phantom"]] == ["A.newname"]


def test_reconcile_matches_renamed_entry_on_new_qualified(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.orig", "short": "orig", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}])
    eid = reg.find()[0]["id"]
    reg.apply("rename", {"id": eid, "new_qualified": "B.renamed", "new_file": "g.lean",
                         "namespace": "B", "reason": "restructure"})
    # A fresh scan sees the post-rename name; it must match, not phantom.
    res = reg.apply("reconcile", {"scanner_output": [
        {"qualified": "B.renamed", "short": "renamed", "kind": "def", "file": "g2.lean", "line": 5, "prefix": "B"}]})
    assert res["drift"]["phantom"] == [] and res["drift"]["vanished"] == []
    assert reg.get(eid)["new"]["file"] == "g2.lean"  # location updated on new.*


def test_reconcile_is_idempotent(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    scan = [{"qualified": "A.a", "short": "a", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"},
            {"qualified": "A.b", "short": "b", "kind": "def", "file": "f.lean", "line": 2, "prefix": "A"}]
    _found(reg, scan)
    reg.apply("reconcile", {"scanner_output": scan})
    res = reg.apply("reconcile", {"scanner_output": scan})
    d = res["drift"]
    assert d["vanished"] == [] and d["phantom"] == [] and d["resurrection"] == []
    assert d["location_updated"] == 0
    assert len(reg.find()) == 2


def test_reconcile_rejects_duplicate_qualified_in_scan(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found(reg, [{"qualified": "A.a", "short": "a", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}])
    with pytest.raises(OperationError):
        reg.apply("reconcile", {"scanner_output": [
            {"qualified": "A.a", "short": "a", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"},
            {"qualified": "A.a", "short": "a", "kind": "def", "file": "g.lean", "line": 2, "prefix": "A"}]})


# -- controlled ontology vocabulary (interop tag-vocab work item) --------------

def _found1(reg):
    _found(reg, [{"qualified": "A.a", "short": "a", "kind": "def", "file": "f.lean", "line": 1, "prefix": "A"}])
    return reg.find()[0]["id"]


def test_set_vocab_enforces_hard_enum(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    reg.apply("set_vocab", {"vocab": {
        "domain": {"values": ["number", "order"], "cardinality": "0..1"},
        "role": ["core", "face"]}})
    # A value in the vocab is accepted...
    reg.apply("annotate", {"id": eid, "domain": "number", "role": "core"})
    assert reg.validate() == []
    # ...one outside it is rejected (postcondition fails, nothing written).
    with pytest.raises(ValidationError):
        reg.apply("annotate", {"id": eid, "domain": "not-a-domain"})
    assert reg.get(eid)["ontology"]["domain"] == "number"  # unchanged


def test_set_vocab_rejects_unknown_field(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    reg.apply("set_vocab", {"vocab": {"domain": ["number"]}})  # no 'role' field
    with pytest.raises(ValidationError):
        reg.apply("annotate", {"id": eid, "role": "core"})  # 'role' not in vocab


def test_set_vocab_null_axes_are_allowed(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found1(reg)
    reg.apply("set_vocab", {"vocab": {"domain": ["number"], "role": ["core"]}})
    assert reg.validate() == []  # all axes null on the pending entry → fine


def test_role_no_go_passes_schema_and_vocab(tmp_path):
    # role is double-guarded (schema enum + vocab); 'no-go' must clear BOTH.
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    reg.apply("set_vocab", {"vocab": {"role": ["core", "no-go"]}})
    reg.apply("annotate", {"id": eid, "role": "no-go"})
    assert reg.get(eid)["ontology"]["role"] == "no-go"
    assert reg.validate() == []


def test_set_vocab_refuses_adoption_conflicting_with_existing_curation(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    reg.apply("annotate", {"id": eid, "domain": "number"})
    # Adopting a vocab that omits 'number' must be refused (whole-registry postcond).
    with pytest.raises(ValidationError):
        reg.apply("set_vocab", {"vocab": {"domain": ["order", "logic"]}})
    assert reg.get(eid)["ontology"]["domain"] == "number"  # data intact


def test_set_vocab_from_file_and_normalizes_values(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found1(reg)
    cfg = tmp_path / "tag_vocab.json"
    cfg.write_text(json.dumps({"domain": {"values": ["order", "number", "number"]}}),
                   encoding="utf-8")
    reg.apply("set_vocab", {"vocab": str(cfg)})
    stored = reg.load()["vocab"]["domain"]["values"]
    assert stored == ["number", "order"]  # de-duped + alphabetized


def test_set_vocab_accepts_fields_wrapper_and_ignores_metadata(tmp_path):
    # The real config nests axes under `fields` with sibling metadata keys.
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    cfg = {
        "status": "DRAFT — ignored by sjv",
        "purpose": "ignored",
        "fields": {
            "domain": {"values": ["order", "number"], "cardinality": "1 expected (soft)",
                       "glosses": {"order": "…", "number": "…"}},
            "role": {"values": ["core", "face"]},
        },
        "_open": "ignored",
    }
    reg.apply("set_vocab", {"vocab": cfg})
    stored = reg.load()["vocab"]
    assert sorted(stored.keys()) == ["domain", "role"]  # only the fields, not metadata
    assert stored["domain"]["values"] == ["number", "order"]
    reg.apply("annotate", {"id": eid, "domain": "number", "role": "core"})
    assert reg.validate() == []


def test_registry_default_vocab_path_is_in_data_folder(tmp_path):
    reg = _reg(tmp_path / "sub" / "registry.json")
    assert reg.vocab_path == tmp_path / "sub" / "tag_vocab.json"


def test_cardinality_is_soft_and_surfaced_by_anomaly_view(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    # role required (min 1), but the entry has no role → must still VALIDATE...
    reg.apply("set_vocab", {"vocab": {"role": {"values": ["core"], "cardinality": "1"}}})
    assert reg.validate() == []  # cardinality never blocks
    # ...and be surfaced by the anomalies view.
    anomalies = reg.export_view("anomalies")
    assert eid in anomalies and "role" in anomalies
    # Once the required axis is set, the anomaly clears.
    reg.apply("annotate", {"id": eid, "role": "core"})
    assert "_(none)_" in reg.export_view("anomalies")


def test_cardinality_object_form_is_persisted_and_fires(tmp_path):
    # Regression: ZP supplied cardinality as {"min":1,"max":1}; it was dropped
    # (only string form was persisted) so anomalies stayed inert on pending rows.
    reg = _reg(tmp_path / "reg.json")
    eid = _found1(reg)
    reg.apply("annotate", {"id": eid, "object": "bottom"})  # partial: object only
    reg.apply("set_vocab", {"vocab": {
        "object": {"values": ["bottom"], "cardinality": {"min": 0, "max": 1}},
        "domain": {"values": ["order"], "cardinality": {"min": 1, "max": 1}},
        "role": {"values": ["core"], "cardinality": {"min": 1, "max": 1}}}})
    # Object cardinality is persisted (normalized), not silently dropped.
    stored = reg.load()["vocab"]
    assert stored["domain"]["cardinality"] == {"min": 1, "max": 1}
    # A pending, partially-tagged entry (domain+role null, both required) is flagged.
    anomalies = reg.export_view("anomalies")
    assert eid in anomalies and "domain" in anomalies and "role" in anomalies
    assert reg.validate() == []  # still soft — never blocks


def test_set_vocab_skips_underscore_prefixed_keys(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found1(reg)
    reg.apply("set_vocab", {"vocab": {
        "_note": "draft marker, not a field",
        "role": ["core", "face"]}})
    assert sorted(reg.load()["vocab"].keys()) == ["role"]


def test_anomalies_view_is_paged_and_count_only(tmp_path):
    # anomalies is the tagging worklist (large by design) — it must not blow the
    # token budget the way #6 addressed for find (interop retest 2026-07-02).
    reg = _reg(tmp_path / "reg.json")
    scan = [{"qualified": f"A.d{i}", "short": f"d{i}", "kind": "def",
             "file": "f.lean", "line": i, "prefix": "A"} for i in range(400)]
    _found(reg, scan)
    reg.apply("set_vocab", {"vocab": {
        "domain": {"values": ["order"], "cardinality": {"min": 1, "max": 1}},
        "role": {"values": ["core"], "cardinality": {"min": 1, "max": 1}}}})

    full = reg.export_view("anomalies")  # default page
    # Leads with the summary counts (per-axis breakdown).
    assert "anomalies: 400 entries" in full
    assert "| domain | 400 |" in full and "| role | 400 |" in full
    # Default page is capped (safe inline), not all 400 rows. Rows carry the
    # surrogate id and the "domain, role" missing-axis cell, one per row.
    assert full.count("domain, role") == 50   # default page, not 400
    assert len(full) < 8000                    # small inline, not ~tens of KB

    # count_only: summary only, no rows.
    summary = reg.export_view("anomalies", count_only=True)
    assert "| domain | 400 |" in summary
    assert "| id | missing required axis |" not in summary
    assert "domain, role" not in summary

    # paging window.
    page = reg.export_view("anomalies", limit=10, offset=20)
    assert "showing 21–30 of 400" in page
    assert page.count("domain, role") == 10

    # limit=0 → all rows.
    everything = reg.export_view("anomalies", limit=0)
    assert everything.count("domain, role") == 400


# -- bulk annotate (interop issue #9) -----------------------------------------

def _found_prefixes(reg):
    """Found a small registry across two prefixes and adopt a vocab."""
    scan = ([{"qualified": f"ZPA.d{i}", "short": f"d{i}", "kind": "def",
              "file": "ZPA.lean", "line": i, "prefix": "ZPA"} for i in range(3)]
            + [{"qualified": f"ZPB.d{i}", "short": f"d{i}", "kind": "def",
                "file": "ZPB.lean", "line": i, "prefix": "ZPB"} for i in range(2)])
    _found(reg, list(scan))
    reg.apply("set_vocab", {"vocab": {
        "domain": ["order", "valuation"], "role": ["core", "face"]}})


def test_annotate_many_sets_and_is_atomic(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    ids = [e["id"] for e in reg.find(**{"old.prefix": "ZPA"})]
    res = reg.apply("annotate_many", {"items": [
        {"id": ids[0], "domain": "order", "role": "core"},
        {"id": ids[1], "domain": "order"}]})
    assert res["count"] == 2 and res["unchanged"] == 0
    assert reg.get(ids[0])["ontology"] == {"object": None, "domain": "order", "role": "core"}
    assert reg.validate() == []
    # Re-applying the same tags is a no-op (idempotency visibility).
    res2 = reg.apply("annotate_many", {"items": [{"id": ids[0], "domain": "order", "role": "core"}]})
    assert res2["count"] == 0 and res2["unchanged"] == 1


def test_annotate_many_rejects_bad_value_atomically(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    ids = [e["id"] for e in reg.find(**{"old.prefix": "ZPA"})]
    before = reg.verify_integrity()
    with pytest.raises(ValidationError):
        reg.apply("annotate_many", {"items": [
            {"id": ids[0], "domain": "order"},
            {"id": ids[1], "domain": "not-a-domain"}]})  # one bad → whole batch fails
    assert reg.get(ids[0])["ontology"]["domain"] is None  # first item NOT written
    assert reg.verify_integrity() == before


def test_annotate_many_rejects_duplicate_and_missing_ids(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    eid = reg.find()[0]["id"]
    with pytest.raises(OperationError):
        reg.apply("annotate_many", {"items": [{"id": eid, "role": "core"},
                                              {"id": eid, "role": "face"}]})  # dup
    with pytest.raises(OperationError):
        reg.apply("annotate_many", {"items": [{"id": "no-such-id", "role": "core"}]})


def test_annotate_many_null_clears(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    eid = reg.find()[0]["id"]
    reg.apply("annotate", {"id": eid, "role": "core"})
    reg.apply("annotate_many", {"items": [{"id": eid, "role": None}]})  # explicit clear
    assert reg.get(eid)["ontology"]["role"] is None


def test_annotate_by_filter_tags_all_matches(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    res = reg.apply("annotate_by_filter", {"filter": {"old.prefix": "ZPA"},
                                           "tags": {"domain": "order"}})
    assert res["matched"] == 3 and res["updated"] == 3
    assert all(e["ontology"]["domain"] == "order" for e in reg.find(**{"old.prefix": "ZPA"}))
    # ZPB untouched.
    assert all(e["ontology"]["domain"] is None for e in reg.find(**{"old.prefix": "ZPB"}))


def test_annotate_by_filter_targets_only_untagged(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    zpa = [e["id"] for e in reg.find(**{"old.prefix": "ZPA"})]
    reg.apply("annotate", {"id": zpa[0], "domain": "valuation"})  # pre-tag one
    # Filter on the null axis to hit only the still-untagged ZPA entries.
    res = reg.apply("annotate_by_filter", {
        "filter": {"old.prefix": "ZPA", "ontology.domain": None}, "tags": {"domain": "order"}})
    assert res["matched"] == 2 and res["updated"] == 2
    assert reg.get(zpa[0])["ontology"]["domain"] == "valuation"  # pre-tagged one preserved


def test_annotate_by_filter_rejects_empty_filter_and_bad_tag(tmp_path):
    reg = _reg(tmp_path / "reg.json")
    _found_prefixes(reg)
    with pytest.raises(OperationError):
        reg.apply("annotate_by_filter", {"filter": {}, "tags": {"domain": "order"}})
    reg.apply("annotate_by_filter", {"filter": {}, "tags": {"domain": "order"}, "force": True})  # ok
    with pytest.raises(ValidationError):
        reg.apply("annotate_by_filter", {"filter": {"old.prefix": "ZPB"},
                                         "tags": {"domain": "bogus"}})
