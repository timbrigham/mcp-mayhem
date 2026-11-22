"""`basis.kind: subjects`: a human signature whose slot is the git tree of exactly the bytes signed.

⛔ THE MEASURED CASE, 2026-11-22 (relayed by the consumer, then chosen by Tim in this repo's
session). A tier-H signature over 145 unchanged files was refused by V11, because adversary
rev 0 at the index tree's basis was held by an unrelated two-file agent review. Revision 1 would
have SUPERSEDED that review and dropped its coverage. The signature got through only by being
re-keyed to the commit id, a different basis value that happened to be free.
Tim: *"we need to be able to do overrides on a specific set of bytes without having to iterate to
a new blob ID as well.. Maybe not four every function but the signatures on my part in
particular"*.
"""

import subprocess

import pytest

from conftest import good
from core import schema
from core.errors import ValidationFailure

S1 = [{"path": "ZeroParadox/A.lean", "git_blob_id": "1" * 40},
      {"path": "ZeroParadox/Sub/B.lean", "git_blob_id": "2" * 40},
      {"path": "README.md", "git_blob_id": "3" * 40}]


def sig(subjects=S1, **over):
    rec = good(step="adversary", tier="H", verdict="PASS", reason="signed: sweep cleared",
               subjects=subjects, evidence=[],
               basis={"kind": "subjects", "value": schema.subjects_tree(subjects),
                      "resolved_from": "explicit"},
               decided={"how": "signature", "who": "Tim", "passes": 1, "agreed": 1})
    rec.update(over)
    return rec


def errs(ledger, rec):
    return ledger.validate(rec)["errors"]


def _git_write_tree(tmp_path, subjects):
    """The tree id git itself gives for an index holding these blobs at these paths."""
    repo = tmp_path / "wt"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True,
                                    text=True).stdout.strip()
    run("init", "-q")
    for s in subjects:
        run("update-index", "--add", "--info-only", "--cacheinfo",
            f"100644,{s['git_blob_id']},{s['path']}")
    return run("write-tree", "--missing-ok")


@pytest.mark.parametrize("subjects", [
    S1,
    [{"path": "a.md", "git_blob_id": "a" * 40}],
    # ⚠ git's ordering trap: a directory sorts as if named "x/", so "x.md" < "x/" < "x0".
    [{"path": "x/y.md", "git_blob_id": "4" * 40}, {"path": "x.md", "git_blob_id": "5" * 40},
     {"path": "x0", "git_blob_id": "6" * 40}, {"path": "x-1/z", "git_blob_id": "7" * 40}],
])
def test_the_value_is_the_tree_git_itself_computes(tmp_path, subjects):
    """⭐⭐ The claim that makes this GIT'S hash rather than a second one: git reproduces it."""
    assert schema.subjects_tree(subjects) == _git_write_tree(tmp_path, subjects)


def test_a_signature_over_a_byte_set_is_accepted(ledger):
    assert errs(ledger, sig()) == []
    assert ledger.append(sig())["appended"] is True


def test_the_measured_collision_is_gone(ledger):
    """⭐⭐ THE HEADLINE. An agent review holds rev 0 at a tree; a signature over other unchanged
    files still records at rev 0, and the review keeps its slot and its coverage."""
    tree = "9" * 40
    review = good(step="adversary", tier="A", verdict="PASS", reason="reviewed",
                  subjects=[{"path": "GUIDE.md", "git_blob_id": "8" * 40}],
                  evidence=[{"path": "tools/verify/briefs/adversary.md", "git_blob_id": "e" * 40}],
                  basis={"kind": "tree", "value": tree, "resolved_from": "explicit"},
                  decided={"how": "delegated", "passes": 1, "agreed": 1, "who": "adversary"})
    assert ledger.append(review)["appended"] is True
    assert ledger.append(sig())["appended"] is True


def test_the_same_bytes_land_in_the_same_slot(ledger):
    """Re-signing identical bytes is one fact (dedupes); a different claim about them is a
    regrade at revision 1, the ordinary V11 discipline, unchanged."""
    ledger.append(sig())
    ledger.append(sig())                                     # identical: dedupes, no refusal
    with pytest.raises(ValidationFailure, match="V11"):
        ledger.append(sig(reason="signed again, different words"))
    assert ledger.append(sig(reason="signed again, different words", revision=1))["appended"]


def test_different_bytes_get_their_own_slot(ledger):
    ledger.append(sig())
    other = [dict(S1[0], git_blob_id="f" * 40)] + S1[1:]
    assert ledger.append(sig(other))["appended"] is True


def test_a_value_that_is_not_these_bytes_is_refused(ledger):
    rec = sig()
    rec["basis"]["value"] = schema.subjects_tree(S1[:2])
    found = [e for e in errs(ledger, rec) if "'subjects'" in e]
    assert found and "SATISFIED WHEN" in found[0] and schema.subjects_tree(S1) in found[0]


@pytest.mark.parametrize("tier,how", [("A", "delegated"), ("A", "agreement"),
                                      ("H", "override"), ("M", "mechanical")])
def test_only_a_human_signature_may_use_it(ledger, tier, how):
    """⛔ Tim's scope. Agent records keep V11's protection against branching their own claims;
    `override` is out because V12 keys to the basis and would never see a prior decision here."""
    rec = sig(tier=tier, decided={"how": how, "who": "Tim", "passes": 3, "agreed": 3})
    assert any("signature only" in e for e in errs(ledger, rec))


@pytest.mark.parametrize("subjects", [
    [],
    [{"path": "a.md"}],
    [{"path": "a.md", "git_blob_id": "XYZ"}],
    [{"path": "a.md", "git_blob_id": "1" * 40}, {"path": "a.md", "git_blob_id": "2" * 40}],
    [{"path": "a", "git_blob_id": "1" * 40}, {"path": "a/b", "git_blob_id": "2" * 40}],
    [{"path": "../a", "git_blob_id": "1" * 40}],
])
def test_a_set_that_names_no_tree_is_refused(ledger, subjects):
    rec = sig(subjects=[{"path": "a.md", "git_blob_id": "1" * 40}])
    rec["subjects"] = subjects
    assert schema.subjects_tree(subjects) is None
    assert any("'subjects'" in e for e in errs(ledger, rec))


def test_other_kinds_are_untouched(ledger):
    assert errs(ledger, good()) == []
