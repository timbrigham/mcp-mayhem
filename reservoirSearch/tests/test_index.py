"""reservoir_core over a miniature index in the real on-disk format."""

from __future__ import annotations

import json
import os
import time

import pytest

from reservoir_core.index import ReservoirError, Store, norm_toolchain, norm_url


def _pkg(root, owner, name, *, full=None, desc="", keywords=(), stars=0, license="MIT",
         repo=None, versions=(), builds=()):
    d = root / owner.lower() / name.lower()
    d.mkdir(parents=True)
    repo = repo or f"https://github.com/{owner}/{name}"
    (d / "metadata.json").write_text(json.dumps({
        "schemaVersion": "1.2.0", "name": name, "owner": owner,
        "fullName": full or f"{owner}/{name}", "description": desc, "keywords": list(keywords),
        "homepage": repo, "license": license, "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z", "stars": stars,
        "sources": [{"type": "git", "host": "github", "repoUrl": repo, "gitUrl": repo + ".git"}]}),
        encoding="utf-8")
    (d / "versions.json").write_text(json.dumps({"schemaVersion": "1.2.0", "data": list(versions)}),
                                     encoding="utf-8")
    (d / "builds.json").write_text(json.dumps({"schemaVersion": "1.2.0", "data": list(builds)}),
                                   encoding="utf-8")
    return d


def _ver(tc, deps=(), version="1.0.0"):
    return {"version": version, "revision": "r" * 40, "date": "2026-01-01", "tag": None,
            "toolchain": f"leanprover/lean4:{tc}", "license": "MIT", "readmeFile": "README.md",
            "dependencies": list(deps)}


def _dep(name, scope, url, transitive=False):
    return {"type": "git", "name": name, "scope": scope, "version": "0.0.0",
            "transitive": transitive, "rev": "a" * 40, "inputRev": "main", "url": url}


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "idx"
    r.mkdir()
    (r / "README.md").write_text("not a package", encoding="utf-8")
    (r / ".git").mkdir()
    # mathlib's Lake name differs from its repo name: the url is the real key
    _pkg(r, "leanprover-community", "mathlib", desc="The math library", keywords=["algebra"],
         stars=4000, license="Apache-2.0", repo="https://github.com/leanprover-community/mathlib4",
         versions=[_ver("v4.35.0", [_dep("batteries", "leanprover-community",
                                         "https://github.com/leanprover-community/batteries",
                                         )]),
                   _ver("v4.34.0", [_dep("noscope", "bob", "https://github.com/bob/noscope")],
                        version="0.9.0")])
    _pkg(r, "leanprover-community", "batteries", desc="Batteries included", stars=300,
         license="Apache-2.0", versions=[_ver("v4.35.0")])
    _pkg(r, "Alice", "Topo", desc="Point-set topology over Mathlib", keywords=["topology"],
         stars=5, versions=[_ver("v4.35.0", [
             _dep("mathlib", "leanprover-community",
                  "git@github.com:leanprover-community/mathlib4.git"),
             _dep("batteries", "leanprover-community",
                  "https://github.com/leanprover-community/batteries", transitive=True)])])
    _pkg(r, "bob", "noscope", desc="algebra helpers", keywords=["algebra"], stars=50,
         versions=[_ver("v4.36.0-rc2", [_dep("mathlib", None,
                                             "https://GitHub.com/leanprover-community/Mathlib4.git/")])])
    _pkg(r, "carol", "byname", desc="depends by scope only", stars=1,
         versions=[_ver("v4.36.0", [_dep("batteries", "leanprover-community", None)])])
    # an alias stub for a rename, and a chain of two
    (r / "alice" / "OldTopo").write_text(json.dumps({"alias": {"from": "Alice/OldTopo",
                                                               "to": "alice/topo"}}), encoding="utf-8")
    (r / "alice" / "older").write_text(json.dumps({"alias": {"from": "alice/older",
                                                             "to": "alice/oldtopo"}}), encoding="utf-8")
    # a broken package dir (measured on the first real load: katzenpost/crypt_walker)
    (r / "broken" / "pkg").mkdir(parents=True)
    return r


def test_norm_url_collapses_every_spelling():
    want = "github.com/o/r"
    for u in ("https://github.com/o/r", "https://GitHub.com/O/R.git", "https://github.com/o/r/",
              "git@github.com:o/r.git", "https://user@github.com/o/r.git/"):
        assert norm_url(u) == want, u
    assert norm_url(None) is None and norm_url("") is None


def test_norm_toolchain_is_exact():
    assert norm_toolchain("leanprover/lean4:v4.35.0") == norm_toolchain("4.35.0") == "v4.35.0"
    assert norm_toolchain("v4.36.0-rc2") != norm_toolchain("v4.36.0")


def test_load_counts_and_skips_the_broken_entry(root):
    s = Store(root).status()
    assert (s["packages"], s["aliases"]) == (5, 2)
    assert [e["entry"] for e in s["skipped_entries"]] == ["broken/pkg"]


def test_search_ands_terms_and_ranks_by_stars(root):
    st = Store(root)
    out = st.search("algebra")
    assert [r["fullName"] for r in out["results"]] == ["leanprover-community/mathlib", "bob/noscope"]
    assert st.search("algebra helpers")["total"] == 1
    assert st.search("TOPOLOGY")["results"][0]["fullName"] == "Alice/Topo"   # display casing


def test_search_filters_and_truncation(root):
    st = Store(root)
    assert st.search(toolchain="4.35.0")["total"] == 3
    assert st.search(license="apache-2.0")["total"] == 2
    assert st.search(owner="Alice")["total"] == 1
    out = st.search(toolchain="v4.35.0", limit=1)
    assert (len(out["results"]), out["truncated"], out["total"]) == (1, 2, 3)
    with pytest.raises(ReservoirError):
        st.search()


def test_get_package_is_case_insensitive_and_follows_aliases(root):
    st = Store(root)
    p = st.get_package("LEANPROVER-COMMUNITY/Mathlib", versions_limit=1)
    assert p["key"] == "leanprover-community/mathlib" and not p["resolved_alias"]
    assert (p["versions_total"], len(p["versions"]), p["versions_truncated"]) == (2, 1, 1)
    assert p["latest"]["toolchain"].endswith("v4.35.0")
    assert st.get_package("Alice/OldTopo")["key"] == "alice/topo"
    assert st.get_package("alice/older")["resolved_alias"] is True     # two hops
    with pytest.raises(ReservoirError) as e:
        st.get_package("nobody/nothing")
    assert e.value.error_type == "not_found" and "partial" in e.value.satisfied_when
    with pytest.raises(ReservoirError):
        st.get_package("mathlib")                                        # not owner/name


def test_dependents_by_url_by_scope_and_transitive(root):
    st = Store(root)
    m = st.dependents("leanprover-community/mathlib")
    # scp-style url and an odd-cased https url with .git/ both resolve to the mathlib4 repo
    assert sorted(r["fullName"] for r in m["results"]) == ["Alice/Topo", "bob/noscope"]
    assert {r["matched_by"] for r in m["results"]} == {"url"}
    b = st.dependents("leanprover-community/batteries")
    assert (b["direct"], b["transitive"]) == (2, 1)
    assert sorted(r["fullName"] for r in b["results"]) == ["carol/byname",
                                                           "leanprover-community/mathlib"]
    assert {r["fullName"]: r["matched_by"] for r in b["results"]}["carol/byname"] == "scope/name"
    bt = st.dependents("leanprover-community/batteries", include_transitive=True)
    assert bt["total"] == 3 and any(r["transitive"] for r in bt["results"])


def test_dependents_only_reads_the_latest_version(root):
    """mathlib's OLDER version depended on bob/noscope; its latest does not. Only the newest
    entry in versions.json counts, so bob/noscope has no dependents."""
    st = Store(root)
    assert st.dependents("bob/noscope", include_transitive=True)["total"] == 0


def test_builds_on_exact_and_toolchains(root):
    st = Store(root)
    assert st.builds_on("v4.36.0")["total"] == 1
    assert [r["fullName"] for r in st.builds_on("v4.36.0-rc2")["results"]] == ["bob/noscope"]
    assert st.builds_on("leanprover/lean4:v4.35.0")["total"] == 3
    with pytest.raises(ReservoirError):
        st.builds_on("  ")
    counts = {r["toolchain"]: r["packages"] for r in st.toolchains()["toolchains"]}
    assert counts == {"v4.35.0": 3, "v4.36.0-rc2": 1, "v4.36.0": 1}


def test_a_swapped_directory_reloads_on_the_next_call(root):
    """⭐ The index is replaced in place. A new package dir must appear without a restart."""
    st = Store(root)
    assert st.search("newcomer")["total"] == 0
    time.sleep(0.05)
    _pkg(root, "dave", "newcomer", desc="newcomer pkg", versions=[_ver("v4.35.0")])
    os.utime(root / "dave")
    assert st.search("newcomer")["total"] == 1
    assert st.reloads == 2


def test_a_package_added_under_an_existing_owner_reloads(root):
    """⚠ The root's mtime does NOT move when a package appears inside an existing owner dir, so
    this is the case only the per-owner half of the fingerprint can see."""
    st = Store(root)
    assert st.search("second")["total"] == 0
    before = os.stat(root).st_mtime_ns
    _pkg(root, "bob", "second", desc="second bob pkg", versions=[_ver("v4.35.0")])
    os.utime(root / "bob", ns=(time.time_ns(), time.time_ns() + 10**9))
    assert os.stat(root).st_mtime_ns == before, "fixture must leave the root untouched"
    assert st.search("second")["total"] == 1


def test_an_unchanged_directory_does_not_reload(root):
    st = Store(root)
    st.search("algebra"); st.search("algebra"); st.status()
    assert st.reloads == 1


def test_a_missing_root_is_a_config_refusal(tmp_path):
    with pytest.raises(ReservoirError) as e:
        Store(tmp_path / "nope").status()
    assert e.value.error_type == "config"
