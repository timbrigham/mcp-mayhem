"""Acceptance tests for the CLAIMS layer / multi-collection store (interop #12).

Mapped 1:1 to the ZP acceptance groups T1–T7. The definition of done is that
T1–T7 pass AND every T4 negative *fails validate* (a passing negative would be a
release blocker — the killer gate must be proven, not assumed).
"""

import pytest

from consumers.store import build_store, witness_invariant, wrap_legacy
from core.engine import Store
from core.errors import IntegrityError, OperationError, ValidationError
from core import audit

ANCHOR = {"branch": "origin/main", "commit": None, "tree": None}


def _store(tmp_path):
    return build_store(tmp_path / "store.json")


def _scan(n):
    return [{"qualified": f"A.d{i}", "short": f"d{i}", "kind": "def",
             "file": "f.lean", "line": i, "prefix": "A"} for i in range(n)]


def _found(s, n=3):
    s.apply("declarations", "import_baseline", {"scanner_output": _scan(n), "anchor": ANCHOR})
    return [e["id"] for e in s.find("declarations")]


def _claim(s, cid):
    r = s.find("claims", claim_id=cid)
    return r[0] if r else None


# -- T1: collection isolation -------------------------------------------------

def test_t1_collections_are_isolated_and_both_covered(tmp_path):
    s = _store(tmp_path)
    decl_ids = _found(s, 3)
    # A claim write touches no declaration.
    before = s.find("declarations")
    s.apply("claims", "add_claim", {"claim_id": "C1", "statement": "x", "status": "conj"})
    assert s.find("declarations") == before          # decls unchanged
    assert len(s.find("claims")) == 1
    # A declaration write touches no claim.
    claim_before = _claim(s, "C1")
    s.apply("declarations", "annotate", {"id": decl_ids[0], "role": "core"})
    assert _claim(s, "C1") == claim_before            # claim unchanged
    # Whole store covered by validate / verify_integrity / export_full.
    assert s.validate() == []
    assert s.verify_integrity()                        # truthy hash
    res = s.export_full(tmp_path / "pub.json")
    assert res["entries"] == 3 + 1                     # both collections dumped


def test_t1_declaration_ops_regress_clean_under_the_envelope(tmp_path):
    # The decl path is intact under the store envelope (the legacy 69 Registry
    # tests cover it single-collection; this proves it through the Store).
    s = _store(tmp_path)
    ids = _found(s, 3)
    s.apply("declarations", "rename", {"id": ids[0], "new_qualified": "A.renamed",
             "new_file": "A/x.lean", "namespace": "A", "reason": "restructure"})
    s.apply("declarations", "drop", {"id": ids[1], "reason": "obsolete"})
    assert s.get("declarations", ids[0])["disposition"] == "renamed"
    assert s.get("declarations", ids[1])["disposition"] == "dropped"
    assert s.validate() == []


# -- T2: claim schema ---------------------------------------------------------

def test_t2_wellformed_node_and_edge_validate(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "N1", "statement": "a node", "status": "conj"})
    s.apply("claims", "add_claim", {"claim_id": "N2", "statement": "another", "status": "conj"})
    s.apply("claims", "add_claim", {"claim_id": "E1", "statement": "an edge",
             "status": "conj", "from": "N1", "to": "N2"})
    assert s.validate() == []
    edge = _claim(s, "E1")
    assert edge["from"] == "N1" and edge["to"] == "N2"


def test_t2_offvocab_status_rejected(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)                                        # establish the store first
    with pytest.raises(ValidationError):
        s.apply("claims", "add_claim", {"claim_id": "C", "statement": "x", "status": "invented"})
    assert s.find("claims") == []                      # atomic — nothing written


def test_t2_missing_required_field_rejected_structurally(tmp_path):
    # A claim entry missing a required leaf (here 'reason') fails structural
    # validation — the invariant-structure contract holds per collection.
    s = _store(tmp_path)
    doc = s.empty_store()
    doc["collections"]["claims"]["entries"].append({
        "id": "x", "claim_id": "C", "statement": "s", "object": [], "domain": [],
        "status": "conj", "from": None, "to": None, "date": None, "history": [],
        # 'reason' omitted
    })
    violations = s.all_violations(doc)
    assert any("reason" in v for v in violations)


def test_t2_offvocab_object_domain_element_rejected(tmp_path):
    s = _store(tmp_path)
    s.apply("claims", "set_vocab", {"vocab": {"object": ["snap"], "domain": ["order"]}})
    s.apply("claims", "add_claim", {"claim_id": "C", "statement": "x", "status": "conj",
             "object": ["snap"], "domain": ["order"]})
    assert s.validate() == []
    with pytest.raises(ValidationError):
        s.apply("claims", "annotate_claim", {"claim_id": "C", "domain": ["order", "wizard"]})
    assert _claim(s, "C")["domain"] == ["order"]        # unchanged (atomic)


def test_t2_dangling_from_to_rejected(tmp_path):
    s = _store(tmp_path)
    s.apply("claims", "add_claim", {"claim_id": "N1", "statement": "x", "status": "conj"})
    with pytest.raises(ValidationError):
        s.apply("claims", "add_claim", {"claim_id": "E", "statement": "edge",
                 "status": "conj", "from": "N1", "to": "GHOST"})


def test_t2_add_claim_op_guards(tmp_path):
    s = _store(tmp_path)
    s.apply("claims", "add_claim", {"claim_id": "C", "statement": "x", "status": "conj"})
    with pytest.raises(OperationError):                 # duplicate claim_id
        s.apply("claims", "add_claim", {"claim_id": "C", "statement": "y", "status": "conj"})


# -- T3: witness link ---------------------------------------------------------

def test_t3_witness_is_stored_on_decl_and_derived_for_claim(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj"})
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    # The link lives on the DECL; the claim stores no witnesses.
    assert "T" in s.get("declarations", ids[0])["claims"]["witness_of"]
    assert "witness_of" not in _claim(s, "T")
    # Witness count is DERIVED in the projection.
    assert "| T |" in s.export_view("claims", "status")
    assert s.export_view("claims", "status").count("| 1 |") >= 1


def test_t3_dangling_witness_of_flagged(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 1)
    with pytest.raises(ValidationError):
        s.apply("declarations", "link_claim", {"id": ids[0], "claim": "NO-SUCH-CLAIM"})


def test_t3_add_remove_witness_never_edits_the_claim(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj"})
    snapshot = _claim(s, "T")
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    assert _claim(s, "T") == snapshot
    s.apply("declarations", "unlink_claim", {"id": ids[0], "claim": "T"})
    assert _claim(s, "T") == snapshot


# -- T4: the KILLER invariant (every negative must FAIL validate) -------------

def _proved_setup(s):
    ids = _found(s, 2)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj",
             "date": "2026-07-04"})
    return ids


def test_t4_proved_with_live_witness_is_green(tmp_path):
    s = _store(tmp_path)
    ids = _proved_setup(s)
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    s.apply("claims", "set_status", {"claim_id": "T", "status": "proved", "date": "2026-07-05"})
    assert s.validate() == []
    assert _claim(s, "T")["status"] == "proved"


def test_t4_neg_proved_without_witness_fails(tmp_path):
    s = _store(tmp_path)
    _proved_setup(s)
    with pytest.raises(ValidationError):
        s.apply("claims", "set_status", {"claim_id": "T", "status": "proved"})
    assert _claim(s, "T")["status"] == "conj"           # rolled back


def test_t4_neg_proved_with_sorry_witness_fails(tmp_path):
    s = _store(tmp_path)
    ids = _proved_setup(s)
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    s.apply("declarations", "set_verify", {"id": ids[0], "sorry_free": False})
    with pytest.raises(ValidationError):
        s.apply("claims", "set_status", {"claim_id": "T", "status": "proved"})


def test_t4_neg_witness_removed_from_under_proved_fails(tmp_path):
    s = _store(tmp_path)
    ids = _proved_setup(s)
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    s.apply("claims", "set_status", {"claim_id": "T", "status": "proved", "date": "2026-07-05"})
    # Removing the sole live witness must fail (rollback).
    with pytest.raises(ValidationError):
        s.apply("declarations", "unlink_claim", {"id": ids[0], "claim": "T"})
    # Breaking the proof (sorry_free -> false) on the sole witness must fail too.
    with pytest.raises(ValidationError):
        s.apply("declarations", "set_verify", {"id": ids[0], "sorry_free": False})
    assert s.validate() == []                           # still consistent


def test_t4_deep_also_requires_a_witness(tmp_path):
    s = _store(tmp_path)
    _proved_setup(s)
    with pytest.raises(ValidationError):
        s.apply("claims", "set_status", {"claim_id": "T", "status": "deep"})


def test_t4_conj_and_commitment_need_no_witness(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "A", "statement": "x", "status": "conj"})
    s.apply("claims", "add_claim", {"claim_id": "B", "statement": "y", "status": "commitment"})
    assert s.validate() == []


# -- drop_claim (erroneous-seed removal) --------------------------------------

def test_drop_claim_removes_a_node(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "OOPS", "statement": "x", "status": "conj"})
    s.apply("claims", "drop_claim", {"claim_id": "OOPS", "reason": "seeded in error"})
    assert _claim(s, "OOPS") is None
    assert s.validate() == []


def test_drop_claim_requires_reason(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "C", "statement": "x", "status": "conj"})
    with pytest.raises(OperationError):
        s.apply("claims", "drop_claim", {"claim_id": "C", "reason": "  "})


def test_drop_claim_refused_while_witnessed_then_allowed_after_unlink(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj"})
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    # A decl still witnesses T → dropping it would dangle that link → rollback.
    with pytest.raises(ValidationError):
        s.apply("claims", "drop_claim", {"claim_id": "T", "reason": "err"})
    assert _claim(s, "T") is not None
    # Unlink first, then the drop is clean.
    s.apply("declarations", "unlink_claim", {"id": ids[0], "claim": "T"})
    s.apply("claims", "drop_claim", {"claim_id": "T", "reason": "err"})
    assert _claim(s, "T") is None


def test_drop_claim_refused_while_an_edge_endpoint(tmp_path):
    s = _store(tmp_path)
    s.apply("claims", "seed_claims", {"items": [
        {"claim_id": "N1", "statement": "a", "status": "conj"},
        {"claim_id": "N2", "statement": "b", "status": "conj"},
        {"claim_id": "E", "statement": "e", "status": "conj", "from": "N1", "to": "N2"}]})
    with pytest.raises(ValidationError):          # E's 'from' would dangle
        s.apply("claims", "drop_claim", {"claim_id": "N1", "reason": "err"})
    # Drop the edge first, then the node is free to go.
    s.apply("claims", "drop_claim", {"claim_id": "E", "reason": "err"})
    s.apply("claims", "drop_claim", {"claim_id": "N1", "reason": "err"})
    assert _claim(s, "N1") is None


# -- T5: provenance -----------------------------------------------------------

def test_t5_status_changes_append_to_history_and_downgrades_are_kept(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 1)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj",
             "date": "2026-07-01"})
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    s.apply("claims", "set_status", {"claim_id": "T", "status": "proved", "date": "2026-07-04"})
    # A downgrade (proof retracted) — the sorry_free witness is broken first so
    # 'proved' would no longer hold; the honest state is a downgrade to conj.
    s.apply("claims", "set_status", {"claim_id": "T", "status": "conj", "date": "2026-07-06",
             "reason": "proof retracted"})
    hist = _claim(s, "T")["history"]
    assert [h["status"] for h in hist] == ["conj", "proved", "conj"]
    assert hist[1]["date"] == "2026-07-04"              # the proved episode is never erased


# -- T6: integrity / scale / determinism --------------------------------------

def test_t6_whole_store_integrity_covers_claim_writes(tmp_path):
    s = _store(tmp_path)
    _found(s, 2)
    h1 = s.verify_integrity()
    s.apply("claims", "add_claim", {"claim_id": "C", "statement": "x", "status": "conj"})
    h2 = s.verify_integrity()
    assert h1 != h2                                     # one chain advanced by a claim write


def test_t6_out_of_band_edit_detected(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    p = tmp_path / "store.json"
    import json
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["collections"]["claims"]["entries"].append({"id": "hand", "claim_id": "H"})
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        s.verify_integrity()


def test_t6_export_is_deterministic(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 3)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj"})
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    s.export_full(a)
    s.export_full(b)
    assert a.read_bytes() == b.read_bytes()


def test_t6_seed_is_atomic_and_terse_with_surrogate_ids(tmp_path):
    s = _store(tmp_path)
    _found(s, 1)
    items = [{"claim_id": f"C{i}", "statement": f"s{i}", "status": "conj"} for i in range(40)]
    res = s.apply("claims", "seed_claims", {"items": items})
    assert res["count"] == 40
    assert "entries_touched" not in res                 # terse (>25)
    ids = {c["id"] for c in s.find("claims")}
    assert len(ids) == 40                               # surrogate ids, all distinct
    # A bad element fails the WHOLE batch (atomic).
    with pytest.raises((ValidationError, OperationError)):
        s.apply("claims", "seed_claims", {"items": [
            {"claim_id": "OK", "statement": "s", "status": "conj"},
            {"claim_id": "BAD", "statement": "s", "status": "not-a-status"}]})
    assert _claim(s, "OK") is None                       # nothing from the failed batch


def test_t6_seed_edges_can_reference_batch_siblings(tmp_path):
    s = _store(tmp_path)
    res = s.apply("claims", "seed_claims", {"items": [
        {"claim_id": "N1", "statement": "a", "status": "conj"},
        {"claim_id": "N2", "statement": "b", "status": "conj"},
        {"claim_id": "E", "statement": "edge", "status": "conj", "from": "N1", "to": "N2"}]})
    assert res["count"] == 3
    assert s.validate() == []


# -- T7: projection -----------------------------------------------------------

def test_t7_views_are_deterministic_pure_joins(tmp_path):
    s = _store(tmp_path)
    ids = _found(s, 2)
    s.apply("claims", "add_claim", {"claim_id": "T", "statement": "x", "status": "conj",
             "date": "2026-07-04"})
    s.apply("declarations", "link_claim", {"id": ids[0], "claim": "T"})
    s.apply("claims", "set_status", {"claim_id": "T", "status": "proved", "date": "2026-07-05"})
    assert s.export_view("claims", "status") == s.export_view("claims", "status")
    assert s.export_view("claims", "graph") == s.export_view("claims", "graph")
    # A proved claim renders only with a live witness (the store is always valid,
    # so an unwitnessed proved claim cannot exist to be rendered).
    table = s.export_view("claims", "status")
    assert "| T | proved | 2026-07-05 | 1 |" in table


def test_t7_graph_renders_nodes_and_edges(tmp_path):
    s = _store(tmp_path)
    s.apply("claims", "seed_claims", {"items": [
        {"claim_id": "N1", "statement": "a", "status": "conj"},
        {"claim_id": "N2", "statement": "b", "status": "conj"},
        {"claim_id": "E", "statement": "e", "status": "conj", "from": "N1", "to": "N2"}]})
    g = s.export_view("claims", "graph")
    assert "graph LR" in g
    assert "-->|E: conj|" in g


# -- migration ----------------------------------------------------------------

def test_wrap_legacy_lifts_a_bare_registry(tmp_path):
    bare = {"schema_version": "1", "anchor": ANCHOR,
            "counts": {"files": 0, "declarations": 0}, "entries": [], "vocab": {}}
    env = wrap_legacy(bare)
    assert env["store_version"] == Store.STORE_VERSION
    assert env["collections"]["declarations"] is bare
    assert env["collections"]["claims"]["entries"] == []


def test_witness_invariant_is_a_pure_function(tmp_path):
    # Direct unit check of the gate on a hand-built store doc.
    doc = {"collections": {
        "declarations": {"entries": [
            {"id": "d1", "claims": {"witness_of": ["T"]}, "verify": {"sorry_free": True}}]},
        "claims": {"entries": [{"claim_id": "T", "status": "proved"}]}}}
    assert witness_invariant(doc) == []
    doc["collections"]["declarations"]["entries"][0]["verify"]["sorry_free"] = False
    assert witness_invariant(doc)                        # now fails
