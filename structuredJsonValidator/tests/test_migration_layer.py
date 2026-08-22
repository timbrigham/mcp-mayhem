"""Acceptance tests for the bulk declaration migration op (interop issue #14),
mapped to M1–M5.

migrate_batch is a STORE-LEVEL (cross-collection) op: it transitions declaration
identities to their HEAD names AND resolves the deps coupling in ONE atomic
transaction, so a rename that the Issue-13 deps reference gate would otherwise
block lands together with the matching deps update.

Definition of done: M1–M5 pass AND the M4 negatives *roll the whole batch back*
(the atomicity must be proven, not assumed).
"""

import json

import pytest

from consumers.store import build_store
from core.errors import OperationError, ValidationError

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}
HEAD = {"branch": "origin/main",
        "commit": "a" * 40, "tree": "b" * 40}


def _store(tmp_path):
    return build_store(tmp_path / "store.json")


def _scan(n):
    return [{"qualified": f"ZP.Old.d{i}", "short": f"d{i}", "kind": "def",
             "file": f"ZP/Old/M{i}.lean", "line": i, "prefix": "ZP.Old"} for i in range(n)]


def _found(s, n=4):
    s.apply("declarations", "import_baseline", {"scanner_output": _scan(n), "anchor": ANCHOR})
    return [e["id"] for e in s.find("declarations")]


def _transition(eid, i, disposition="present"):
    """A reconcile item flattening ZP.Old.d{i} -> ZP.d{i} in a new file."""
    return {"id": eid, "new_qualified": f"ZP.d{i}", "new_file": f"ZP/New/N{i}.lean",
            "new_namespace": "ZP", "new_short": f"d{i}", "disposition": disposition}


# -- M1: id-keyed transition, curation preserved ------------------------------

def test_m1_transition_sets_new_and_flips_disposition(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 3)
    # curate: ontology on d0, a witnessed claim on d1.
    s.apply("declarations", "annotate", {"id": ids[0], "role": "core", "domain": "order"})
    s.apply("claims", "add_claim", {"claim_id": "C1", "statement": "x", "status": "conj"})
    s.apply("declarations", "link_claim", {"id": ids[1], "claim": "C1"})

    res = s.apply_store("migrate_batch", {
        "reconcile": [_transition(ids[0], 0), _transition(ids[1], 1), _transition(ids[2], 2)],
        "anchor": HEAD})

    assert res["reconciled"] == 3 and res["added"] == 0

    e0 = s.get("declarations", ids[0])
    assert e0["new"]["qualified"] == "ZP.d0"
    assert e0["new"]["file"] == "ZP/New/N0.lean"
    assert e0["new"]["namespace"] == "ZP"
    assert e0["disposition"] == "present"
    # curation preserved untouched.
    assert e0["ontology"]["role"] == ["core"] and e0["ontology"]["domain"] == ["order"]
    # old identity preserved (it is the anchor provenance, not identity).
    assert e0["old"]["qualified"] == "ZP.Old.d0"

    e1 = s.get("declarations", ids[1])
    assert e1["claims"]["witness_of"] == ["C1"]   # claim link preserved
    assert s.validate() == []
    assert s.load()["collections"]["declarations"]["anchor"]["commit"] == "a" * 40


def test_m1_missing_id_rolls_back_whole_batch(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    with pytest.raises(OperationError):
        s.apply_store("migrate_batch", {"reconcile": [
            _transition(ids[0], 0),
            {"id": "does-not-exist", "new_qualified": "ZP.x", "new_file": "f.lean",
             "new_namespace": "ZP", "new_short": "x", "disposition": "present"}]})
    # atomic: the valid item did NOT land either.
    assert s.get("declarations", ids[0])["new"]["qualified"] is None
    assert s.get("declarations", ids[0])["disposition"] == "pending"


def test_m1_duplicate_id_in_batch_rejected(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    with pytest.raises(OperationError):
        s.apply_store("migrate_batch", {"reconcile": [
            _transition(ids[0], 0), _transition(ids[0], 1)]})


# -- M2: deps coupling (the whole point of a store-level op) -------------------

def test_m2_rename_without_deps_update_dangles_and_rolls_back(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 3)
    # deps reference the OLD (anchor) names.
    s.apply("deps", "import_deps", {"edges": [
        {"from": "ZP.Old.d0", "to": "ZP.Old.d1", "kind": "type"}]})
    # migrating identities WITHOUT touching deps makes the old-name edge dangle
    # (effective-current name is now the NEW name) → the whole batch rolls back.
    with pytest.raises(ValidationError):
        s.apply_store("migrate_batch", {"reconcile": [
            _transition(ids[0], 0), _transition(ids[1], 1), _transition(ids[2], 2)]})
    # nothing moved; deps intact.
    assert s.get("declarations", ids[0])["new"]["qualified"] is None
    assert len(s.find("deps")) == 1
    assert s.validate() == []


def test_m2_remap_deps_keeps_edges_consistent(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [
        {"from": "ZP.Old.d0", "to": "ZP.Old.d1", "kind": "type"},
        {"from": "ZP.Old.d1", "to": "ZP.Old.d2", "kind": "proof"}]})
    res = s.apply_store("migrate_batch", {
        "reconcile": [_transition(ids[0], 0), _transition(ids[1], 1), _transition(ids[2], 2)],
        "remap_deps": True})
    assert res["deps"]["mode"] == "remap" and res["deps"]["remapped"] == 2
    # edges now reference the NEW names and resolve.
    froms = sorted(e["from"] for e in s.find("deps"))
    assert froms == ["ZP.d0", "ZP.d1"]
    assert s.validate() == []


def test_m2_fresh_deps_replace_at_new_names(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [{"from": "ZP.Old.d0", "to": "ZP.Old.d1"}]})
    res = s.apply_store("migrate_batch", {
        "reconcile": [_transition(ids[0], 0), _transition(ids[1], 1), _transition(ids[2], 2)],
        "deps": [{"from": "ZP.d0", "to": "ZP.d2", "kind": "type"}]})
    assert res["deps"]["mode"] == "replace"
    assert res["deps"]["replaced"] == 1 and res["deps"]["imported"] == 1
    edges = s.find("deps")
    assert len(edges) == 1 and edges[0]["from"] == "ZP.d0" and edges[0]["to"] == "ZP.d2"
    assert s.validate() == []


def test_m2_replace_with_dangling_edge_rolls_back(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    with pytest.raises(ValidationError):
        s.apply_store("migrate_batch", {
            "reconcile": [_transition(ids[0], 0), _transition(ids[1], 1)],
            "deps": [{"from": "ZP.d0", "to": "ZP.GHOST"}]})
    # whole batch rolled back — identities NOT migrated.
    assert s.get("declarations", ids[0])["new"]["qualified"] is None


# -- M3: add_new --------------------------------------------------------------

def test_m3_add_new_appends_head_declarations(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    res = s.apply_store("migrate_batch", {
        "reconcile": [_transition(ids[0], 0), _transition(ids[1], 1)],
        "add_new": [{"qualified": "ZP.brand", "file": "ZP/New/Brand.lean",
                     "namespace": "ZP", "short": "brand", "kind": "theorem"}]})
    assert res["added"] == 1
    added = s.find("declarations", **{"new.qualified": "ZP.brand"})
    assert len(added) == 1
    entry = added[0]
    assert entry["disposition"] == "new"
    # Genuinely new — no ANCHOR identity, but its BIRTH identity is recorded as a
    # synthetic old (interop #16a) so the entry is not born immutable.
    assert entry["old"]["synthetic"] is True
    assert entry["old"]["qualified"] == "ZP.brand"
    assert entry["new"]["file"] == "ZP/New/Brand.lean"
    assert len(s.find("declarations")) == 3
    assert s.load()["collections"]["declarations"]["counts"]["declarations"] == 3
    assert s.validate() == []


# -- M4: full atomic rollback across collections ------------------------------

def test_m4_add_new_not_applied_when_reconcile_fails(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    before = len(s.find("declarations"))
    with pytest.raises(OperationError):
        s.apply_store("migrate_batch", {
            "reconcile": [{"id": "ghost", "new_qualified": "ZP.x", "new_file": "f.lean",
                           "new_namespace": "ZP", "new_short": "x", "disposition": "present"}],
            "add_new": [{"qualified": "ZP.brand", "file": "f.lean", "namespace": "ZP",
                         "short": "brand"}]})
    assert len(s.find("declarations")) == before   # add_new rolled back with the batch


# -- M5: HEAD identity populated + deterministic export -----------------------

def test_m5_new_file_populated_and_export_reflects_head(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 3)
    s.apply_store("migrate_batch", {
        "reconcile": [_transition(ids[i], i) for i in range(3)]})
    # every migrated entry now carries a resolvable HEAD file path.
    for e in s.find("declarations"):
        assert e["new"]["file"] and e["new"]["file"].startswith("ZP/New/")
    res = s.export_full(tmp_path / "ssot.json")
    assert res["entries"] == 3
    pub = json.load(open(tmp_path / "ssot.json", encoding="utf-8"))
    names = {e["new"]["qualified"] for e in pub["collections"]["declarations"]["entries"]}
    assert names == {"ZP.d0", "ZP.d1", "ZP.d2"}


# -- source-file input (keeps the founding call tiny) -------------------------

def test_migrate_from_source_file(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    payload = {
        "anchor": HEAD,
        "reconcile": [_transition(ids[0], 0), _transition(ids[1], 1)],
        "add_new": [{"qualified": "ZP.extra", "file": "ZP/New/E.lean",
                     "namespace": "ZP", "short": "extra"}],
    }
    src = tmp_path / "import.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    res = s.apply_store("migrate_batch", {"source": str(src)})
    assert res["reconciled"] == 2 and res["added"] == 1
    assert s.get("declarations", ids[0])["new"]["qualified"] == "ZP.d0"
    assert s.validate() == []
