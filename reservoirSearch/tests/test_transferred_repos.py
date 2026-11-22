"""Dependencies that name a repo under its OLD owner, with no scope.

⚠ Found by a blind test 2026-11-22 (run by another ZeroParadox session, relayed by the reservoir
session): dependents("leanprover-community/ProofWidgets4") returned 8 direct where 15 were real.
The other 7 manifests name https://github.com/EdAyers/ProofWidgets4, the repo's pre-transfer url,
with scope None and Lake name "proofwidgets". Measured here on the same data: 18 such entries in
latest versions (7 direct, 10 transitive, and leanprover/leanbv with no url at all).
"""

from __future__ import annotations

import pytest

from reservoir_core.index import Store
from tests.test_index import _dep, _pkg, _ver


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "idx"
    r.mkdir()
    # the package lives under its NEW owner; its Lake name differs from its repo name
    pw = _pkg(r, "leanprover-community", "proofwidgets", stars=100,
              repo="https://github.com/leanprover-community/ProofWidgets4",
              versions=[_ver("v4.35.0")])
    old = _dep("proofwidgets", None, "https://github.com/EdAyers/ProofWidgets4")
    _pkg(r, "a", "viaoldurl", versions=[_ver("v4.35.0", [old])])
    _pkg(r, "b", "nourl", versions=[_ver("v4.35.0", [_dep("proofwidgets", "", None)])])
    # a fork that shares the REPO name but is a different Lake package: must not match
    _pkg(r, "c", "fork", versions=[_ver("v4.35.0", [
        _dep("otherwidgets", None, "https://github.com/someone/ProofWidgets4")])])
    # two packages share the Lake name "utils": a name-only dependency resolves to neither
    _pkg(r, "x", "utils", versions=[_ver("v4.35.0")])
    _pkg(r, "y", "utils", versions=[_ver("v4.35.0")])
    _pkg(r, "d", "ambiguous", versions=[_ver("v4.35.0", [_dep("utils", None, None)])])
    # ...and their REPO name too, so a pre-transfer url naming `utils` cannot pick one either
    _pkg(r, "e", "ambiguousurl", versions=[_ver("v4.35.0", [
        _dep("utils", None, "https://github.com/formerowner/utils")])])
    return r


def _edges(st, name):
    out = st.dependents(name, include_transitive=True)
    return {r["fullName"]: r["matched_by"] for r in out["results"]}, out


def test_a_pre_transfer_url_resolves_by_repo_name(root):
    edges, out = _edges(Store(root), "leanprover-community/ProofWidgets")
    assert edges["a/viaoldurl"] == "repo_name"


def test_no_url_and_no_scope_resolves_by_a_unique_lake_name(root):
    edges, _ = _edges(Store(root), "leanprover-community/proofwidgets")
    assert edges["b/nourl"] == "name"


def test_a_fork_with_a_different_lake_name_is_not_taken_for_it(root):
    edges, out = _edges(Store(root), "leanprover-community/proofwidgets")
    assert "c/fork" not in edges
    assert out["matched_by_counts"] == {"repo_name": 1, "name": 1}


def test_a_shared_lake_name_resolves_to_nothing_rather_than_a_guess(root):
    st = Store(root)
    assert st.dependents("x/utils", include_transitive=True)["total"] == 0
    assert st.dependents("y/utils", include_transitive=True)["total"] == 0
    assert st.status()["unresolved_dependency_entries"] == 3      # the fork and both ambiguous
