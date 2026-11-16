"""`basis.kind: scope` = a declared subset of one tree, value `<tree sha>/<run id>`.

⛔ THE MEASURED CASE, 2026-11-16. The consumer's reconstruct burn-down split 261 Lean files
into 41 batches, every one read from the SAME tree (c824c3c3). Keyed `(step, tree)`, each
disjoint batch took the next REVISION, and the sixth append was refused: "V13: revision 6
exceeds policy.supersede.max_depth (5)". Revisions exist for REGRADES of the same judgment;
disjoint batches were spending them. Coverage was never at risk (it keys on content), but
the burn-down could not record.

⚠ The first proposal was `scope` with a bare run id. Refused here, because it keeps WHO ran
it and drops WHAT WAS READ, which is the claim a basis exists to make.
"""

from conftest import good

TREE = "c" * 40


def _batch(run, subjects, **over):
    rec = good(basis={"kind": "scope", "value": f"{TREE}/{run}", "resolved_from": "explicit"},
               subjects=subjects)
    rec.update(over)
    return rec


def _errs(ledger, rec):
    return ledger.validate(rec)["errors"]


def test_a_tree_and_a_run_id_is_a_valid_scope_basis(ledger):
    assert _errs(ledger, _batch("bd-B05-2026-11-16", [{"path": "a.md", "git_blob_id": "1" * 40}])) == []


def test_a_bare_run_id_is_refused_because_it_drops_what_was_read(ledger):
    rec = _batch("x", [{"path": "a.md", "git_blob_id": "1" * 40}])
    rec["basis"]["value"] = "bd-B05-2026-11-16"
    found = [e for e in _errs(ledger, rec) if "scope" in e]
    assert found and "SATISFIED WHEN" in found[0]


def test_a_tree_alone_is_refused_under_scope(ledger):
    rec = _batch("x", [{"path": "a.md", "git_blob_id": "1" * 40}])
    rec["basis"]["value"] = TREE
    assert any("scope" in e for e in _errs(ledger, rec))


def test_a_sha256_tree_is_accepted(ledger):
    rec = _batch("r", [{"path": "a.md", "git_blob_id": "1" * 40}])
    rec["basis"]["value"] = "d" * 64 + "/r"
    assert _errs(ledger, rec) == []


def test_six_batches_over_one_tree_all_record_at_revision_zero(ledger):
    """⭐ The headline: the burn-down shape. Six disjoint batches, six slots, no V13."""
    for i in range(6):
        out = ledger.append(_batch(f"bd-B{i:02d}", [{"path": f"f{i}.md", "git_blob_id": f"{i}" * 40}]))
        assert out["appended"] is True


def test_v11_still_holds_inside_one_scope_basis(ledger):
    """The control: a scope basis is a slot like any other. A different record at the same
    (step, basis, revision) is still branching."""
    import pytest
    from core.errors import ValidationFailure
    ledger.append(_batch("bd-B01", [{"path": "a.md", "git_blob_id": "1" * 40}]))
    with pytest.raises(ValidationFailure, match="V11"):
        ledger.append(_batch("bd-B01", [{"path": "b.md", "git_blob_id": "2" * 40}]))


def test_other_kinds_are_untouched(ledger):
    assert _errs(ledger, good()) == []
