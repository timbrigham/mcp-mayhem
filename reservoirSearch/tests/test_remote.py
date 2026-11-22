"""The GitHub source, against a fake GitHub that serves a real tarball of the real format."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from reservoir_core.index import ReservoirError, Store, schema_warnings, source_from_env
from reservoir_core.remote import GitHubSource
from tests.test_index import _pkg, _ver


def _tarball(src: Path, top: str, extra=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(src, arcname=top)
        for name, data in (extra or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeGitHub:
    def __init__(self, sha: str, tarball: bytes):
        self.sha, self.tarball, self.calls, self.down = sha, tarball, [], False

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url.rsplit("/", 1)[-1])
        if self.down:
            raise OSError("network down")
        if url.endswith("/commits/HEAD"):
            return io.BytesIO(self.sha.encode())
        if url.endswith("/tarball"):
            return io.BytesIO(self.tarball)
        raise AssertionError(url)


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _pkg(src, "leanprover-community", "batteries", desc="Batteries", stars=300,
         versions=[_ver("v4.35.0")], builds=[{"built": True, "toolchain": "v4.35.0"}])
    _pkg(src, "alice", "topo", desc="topology", stars=5, versions=[_ver("v4.35.0")])
    return src


def _store(tmp_path, gh, ttl=3600.0):
    return Store(remote=GitHubSource("leanprover/reservoir-index", tmp_path / "cache", ttl,
                                     opener=gh))


def test_first_call_fetches_and_reports_the_source(tmp_path, tree):
    gh = FakeGitHub("a" * 40, _tarball(tree, "leanprover-reservoir-index-aaaaaaa"))
    st = _store(tmp_path, gh)
    s = st.status()
    assert s["packages"] == 2 and s["packages_with_builds"] == 1
    assert s["source"] == "leanprover/reservoir-index"
    assert s["source_detail"]["kind"] == "github" and s["source_detail"]["commit"] == "a" * 40
    assert gh.calls == ["HEAD", "tarball"]


def test_within_the_ttl_nothing_touches_the_network(tmp_path, tree):
    gh = FakeGitHub("a" * 40, _tarball(tree, "x-y-aaaa"))
    st = _store(tmp_path, gh)
    st.status()
    n = len(gh.calls)
    st.search("topology"); st.status()
    assert len(gh.calls) == n


def test_a_lapsed_ttl_with_an_unmoved_head_downloads_nothing(tmp_path, tree):
    gh = FakeGitHub("a" * 40, _tarball(tree, "x-y-aaaa"))
    st = _store(tmp_path, gh, ttl=0)
    st.status()
    gh.calls.clear()
    st.status()
    assert gh.calls == ["HEAD"]


def test_a_moved_head_downloads_and_the_new_package_appears(tmp_path, tree):
    gh = FakeGitHub("a" * 40, _tarball(tree, "x-y-aaaa"))
    st = _store(tmp_path, gh)
    assert st.search("newcomer")["total"] == 0
    _pkg(tree, "dave", "newcomer", desc="newcomer", versions=[_ver("v4.35.0")])
    gh.sha, gh.tarball = "b" * 40, _tarball(tree, "x-y-bbbb")
    out = st.reload()
    assert st.search("newcomer")["total"] == 1
    assert st.status()["source_detail"]["commit"] == "b" * 40
    assert not (tmp_path / "cache" / "old").exists()


def test_a_failed_refresh_keeps_serving_the_cache_and_says_so(tmp_path, tree):
    gh = FakeGitHub("a" * 40, _tarball(tree, "x-y-aaaa"))
    st = _store(tmp_path, gh, ttl=0)
    st.status()
    gh.down = True
    s = st.status()
    assert s["packages"] == 2
    assert "network down" in s["source_detail"]["last_refresh_error"]


def test_no_cache_and_no_network_is_a_refusal_not_an_empty_index(tmp_path, tree):
    gh = FakeGitHub("a" * 40, b"")
    gh.down = True
    with pytest.raises(ReservoirError) as e:
        _store(tmp_path, gh).search("anything")
    assert e.value.error_type == "unavailable" and "RESERVOIR_SOURCE=local" in e.value.satisfied_when


def test_a_tarball_escaping_its_directory_is_refused(tmp_path, tree):
    gh = FakeGitHub("a" * 40, _tarball(tree, "x-y-aaaa", extra={"../escape.txt": b"x"}))
    with pytest.raises(ReservoirError):
        _store(tmp_path, gh).status()
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "cache" / "escape.txt").exists()


def test_schema_versions_warn_on_major_or_minor_only():
    assert schema_warnings({"1.2.0": 10, "1.2.7": 1}) == []
    w = schema_warnings({"1.3.0": 2, "2.0.0": 1, "None": 4})
    assert len(w) == 3 and any("1.3.0" in x for x in w) and any("'None'" in x for x in w)


def test_an_unknown_schema_in_the_data_surfaces_in_status(tmp_path, tree):
    m = tree / "alice" / "topo" / "metadata.json"
    doc = json.loads(m.read_text(encoding="utf-8"))
    doc["schemaVersion"] = "1.3.0"
    m.write_text(json.dumps(doc), encoding="utf-8")
    s = Store(tree).status()
    assert s["schema_versions"] == {"1.2.0": 5, "1.3.0": 1}
    assert s["schema_warnings"] and "1.3.0" in s["schema_warnings"][0]


def test_a_bare_list_builds_file_is_read_and_flagged(tree):
    (tree / "alice" / "topo" / "builds.json").write_text('[{"built": true}]', encoding="utf-8")
    s = Store(tree).status()
    assert s["packages"] == 2 and s["skipped"] == 0 and s["packages_with_builds"] == 2
    assert any("'None'" in w for w in s["schema_warnings"])


def test_source_selection_from_the_environment(tmp_path):
    assert isinstance(source_from_env({}), GitHubSource)                        # zero setup
    assert source_from_env({"RESERVOIR_INDEX": str(tmp_path)}) == tmp_path      # local
    g = source_from_env({"RESERVOIR_SOURCE": "github", "RESERVOIR_INDEX": "x",
                         "RESERVOIR_REPO": "me/fork", "RESERVOIR_TTL_HOURS": "2",
                         "GH_TOKEN": "t"})
    assert (g.repo, g.ttl, g.token) == ("me/fork", 7200.0, "t")
    with pytest.raises(ReservoirError):
        source_from_env({"RESERVOIR_SOURCE": "ftp"})
