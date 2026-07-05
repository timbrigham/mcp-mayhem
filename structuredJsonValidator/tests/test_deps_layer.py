"""Acceptance tests for the deps layer (interop issue #13), mapped to D1–D5.

Definition of done: D1–D5 pass AND the D3 dangling-reference negative *fails
validate* (the reference gate must be proven, not assumed).
"""

import pytest

from consumers.store import build_store, deps_reference_integrity
from core.errors import OperationError, ValidationError

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}


def _store(tmp_path):
    return build_store(tmp_path / "store.json")


def _scan(n):
    return [{"qualified": f"A.d{i}", "short": f"d{i}", "kind": "def",
             "file": "f.lean", "line": i, "prefix": "A"} for i in range(n)]


def _found(s, n=4):
    s.apply("declarations", "import_baseline", {"scanner_output": _scan(n), "anchor": ANCHOR})


def _q(i):
    return f"A.d{i}"


# -- D1: collection isolation -------------------------------------------------

def test_d1_deps_is_isolated_and_covered(tmp_path):
    s = _store(tmp_path)
    _found(s, 4)
    s.apply("claims", "add_claim", {"claim_id": "C1", "statement": "x", "status": "conj"})
    decls_before, claims_before = s.find("declarations"), s.find("claims")
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)}]})
    assert s.find("declarations") == decls_before      # deps write touched no decl
    assert s.find("claims") == claims_before           # ...and no claim
    assert s.validate() == []
    assert s.verify_integrity()
    res = s.export_full(tmp_path / "pub.json")
    assert res["entries"] == 4 + 1 + 1                  # decls + claim + dep all dumped


def test_d1_declarations_and_claims_regress_clean(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1), "kind": "type"}]})
    # decl + claim writes still work with deps present.
    s.apply("declarations", "annotate", {"id": s.find("declarations")[0]["id"], "role": "core"})
    s.apply("claims", "add_claim", {"claim_id": "K", "statement": "x", "status": "conj"})
    assert s.validate() == []


# -- D2: edge schema ----------------------------------------------------------

def test_d2_wellformed_edge_validates(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [
        {"from": _q(0), "to": _q(1), "kind": "type"},
        {"from": _q(1), "to": _q(2), "kind": "proof"},
        {"from": _q(2), "to": _q(0), "kind": None}]})
    assert s.validate() == []
    assert len(s.find("deps")) == 3


def test_d2_missing_from_or_to_rejected(tmp_path):
    s = _store(tmp_path)
    _found(s, 2)
    with pytest.raises(OperationError):
        s.apply("deps", "import_deps", {"edges": [{"from": _q(0)}]})   # no 'to'
    with pytest.raises(OperationError):
        s.apply("deps", "add_dep", {"to": _q(1)})                       # no 'from'


def test_d2_offvocab_kind_rejected(tmp_path):
    s = _store(tmp_path)
    _found(s, 2)
    with pytest.raises(OperationError):
        s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1), "kind": "weird"}]})


def test_d2_shape_variation_rejected_structurally(tmp_path):
    # An edge entry with an extra field fails additionalProperties:false.
    s = _store(tmp_path)
    _found(s, 2)
    doc = s.empty_store()
    doc["collections"]["deps"]["entries"].append(
        {"id": "x", "from": _q(0), "to": _q(1), "kind": None, "weight": 5})
    assert any("weight" in v or "additional" in v.lower() for v in s.all_violations(doc))


# -- D3: reference integrity (the gate that must be proven) -------------------

def test_d3_resolving_endpoints_are_green(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(2)}]})
    assert s.validate() == []


def test_d3_dangling_from_fails_validate(tmp_path):
    s = _store(tmp_path)
    _found(s, 2)
    with pytest.raises(ValidationError):
        s.apply("deps", "import_deps", {"edges": [{"from": "A.GHOST", "to": _q(0)}]})
    assert s.find("deps") == []                         # atomic — nothing written


def test_d3_dangling_to_fails_validate(tmp_path):
    s = _store(tmp_path)
    _found(s, 2)
    with pytest.raises(ValidationError):
        s.apply("deps", "add_dep", {"from": _q(0), "to": "A.NOPE"})


def test_d3_edge_onto_dropped_declaration_is_dangling(tmp_path):
    # A dropped decl's name is GONE from source (expected-present=False in the
    # reconcile match-key), so an edge onto it is dangling.
    s = _store(tmp_path)
    _found(s, 3)
    did = s.find("declarations", **{"old.qualified": _q(2)})[0]["id"]
    s.apply("declarations", "drop", {"id": did, "reason": "gone"})
    with pytest.raises(ValidationError):
        s.apply("deps", "add_dep", {"from": _q(0), "to": _q(2)})


def test_d3_renamed_declaration_matches_on_new_qualified(tmp_path):
    # After a rename, the edge must reference the NEW qualified (effective-current).
    s = _store(tmp_path)
    _found(s, 2)
    did = s.find("declarations", **{"old.qualified": _q(0)})[0]["id"]
    s.apply("declarations", "rename", {"id": did, "new_qualified": "A.renamed",
             "new_file": "A/x.lean", "namespace": "A", "reason": "r"})
    with pytest.raises(ValidationError):               # old name now dangling
        s.apply("deps", "add_dep", {"from": _q(1), "to": _q(0)})
    s.apply("deps", "add_dep", {"from": _q(1), "to": "A.renamed"})   # new name resolves
    assert s.validate() == []


# -- D4: bulk import-replace --------------------------------------------------

def test_d4_bulk_import_is_atomic_and_terse(tmp_path):
    s = _store(tmp_path)
    _found(s, 50)
    edges = [{"from": _q(i), "to": _q((i + 1) % 50)} for i in range(50)]
    res = s.apply("deps", "import_deps", {"edges": edges})
    assert res["imported"] == 50 and res["replaced"] == 0
    assert "entries_touched" not in res                # terse (>25)
    assert len(s.find("deps")) == 50


def test_d4_second_import_replaces_wholesale(tmp_path):
    s = _store(tmp_path)
    _found(s, 4)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)},
                                              {"from": _q(1), "to": _q(2)}]})
    res = s.apply("deps", "import_deps", {"edges": [{"from": _q(2), "to": _q(3)}]})
    assert res["replaced"] == 2 and res["imported"] == 1
    edges = {(e["from"], e["to"]) for e in s.find("deps")}
    assert edges == {(_q(2), _q(3))}                   # old set gone entirely


def test_d4_reimport_same_set_is_a_deterministic_noop(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    edges = [{"from": _q(0), "to": _q(1), "kind": "type"},
             {"from": _q(1), "to": _q(2), "kind": "proof"}]
    s.apply("deps", "import_deps", {"edges": edges})
    h1 = s.verify_integrity()
    s.apply("deps", "import_deps", {"edges": edges})   # identical set re-imported
    h2 = s.verify_integrity()
    assert h1 == h2                                     # deterministic ids -> byte no-op


def test_d4_duplicate_edges_deduped(tmp_path):
    s = _store(tmp_path)
    _found(s, 2)
    res = s.apply("deps", "import_deps", {"edges": [
        {"from": _q(0), "to": _q(1)}, {"from": _q(0), "to": _q(1)}]})
    assert res["imported"] == 1 and res["deduped"] == 1


def test_d4_bad_edge_rolls_back_whole_import(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)}]})
    # A batch with one dangling edge fails as a whole (atomic) — the prior set stays.
    with pytest.raises(ValidationError):
        s.apply("deps", "import_deps", {"edges": [{"from": _q(1), "to": _q(2)},
                                                  {"from": _q(2), "to": "A.GHOST"}]})
    assert {(e["from"], e["to"]) for e in s.find("deps")} == {(_q(0), _q(1))}


# -- D5: integrity / scale ----------------------------------------------------

def test_d5_whole_store_hash_advances_on_deps_write(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    h1 = s.verify_integrity()
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)}]})
    assert s.verify_integrity() != h1


def test_d5_export_is_deterministic_with_deps(tmp_path):
    s = _store(tmp_path)
    _found(s, 4)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)},
                                              {"from": _q(2), "to": _q(3)}]})
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    s.export_full(a)
    s.export_full(b)
    assert a.read_bytes() == b.read_bytes()


def test_d5_reference_validator_is_a_pure_function(tmp_path):
    doc = {"collections": {
        "declarations": {"entries": [
            {"disposition": "pending", "old": {"qualified": "A.x"}, "new": {"qualified": None}}]},
        "deps": {"entries": [{"id": "1", "from": "A.x", "to": "A.y", "kind": None}]}}}
    v = deps_reference_integrity(doc)
    assert v and "A.y" in v[0]                          # 'to' dangles
    doc["collections"]["deps"]["entries"][0]["to"] = "A.x"
    assert deps_reference_integrity(doc) == []          # now both resolve


# -- cycles view --------------------------------------------------------------

def test_cycles_view_detects_mutual_block(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)},
                                              {"from": _q(1), "to": _q(0)}]})
    out = s.export_view("deps", "cycles")
    assert "SCC 1" in out and _q(0) in out and _q(1) in out


def test_cycles_view_acyclic(tmp_path):
    s = _store(tmp_path)
    _found(s, 3)
    s.apply("deps", "import_deps", {"edges": [{"from": _q(0), "to": _q(1)},
                                              {"from": _q(1), "to": _q(2)}]})
    assert "acyclic" in s.export_view("deps", "cycles")
