"""The shared-scratch leak guard counts TEST worktrees only — never the live server's.

⛔ Measured 2026-10-03: two full-suite runs errored in `_no_leak_into_the_shared_scratch` on an
unrelated test, each overlapping a real consumer `worktree.add` through the live gitRobot. The guard
read a live worktree as a leak from the suite. These pin the discriminator both ways.
"""

from pathlib import Path

from conftest import _PYTEST_TMP_ROOTS, _is_test_leak


def _wt(dirpath: Path, gitdir: str):
    dirpath.mkdir(parents=True)
    (dirpath / ".git").write_bytes(f"gitdir: {gitdir}\n".encode())
    return dirpath


def test_a_worktree_of_a_pytest_fixture_repo_is_a_leak(tmp_path):
    assert "pytest-of-" in str(tmp_path), "fixture assumption: tmp_path lives under pytest-of-*"
    d = _wt(tmp_path / "scratch" / "leaked", str(tmp_path / "repo" / ".git" / "worktrees" / "x"))
    assert _is_test_leak(d, _PYTEST_TMP_ROOTS) is True


def test_a_live_worktree_of_a_real_repository_is_not(tmp_path):
    d = _wt(tmp_path / "scratch" / "live", r"C:\Workspace\SomeRealRepo\.git\worktrees\y")
    assert _is_test_leak(d, _PYTEST_TMP_ROOTS) is False


def test_an_unreadable_or_bare_directory_still_counts(tmp_path):
    """⚠ Fail toward noticing: a directory that cannot be classified is reported."""
    bare = tmp_path / "scratch" / "bare"
    bare.mkdir(parents=True)
    assert _is_test_leak(bare, _PYTEST_TMP_ROOTS) is True
    odd = tmp_path / "scratch" / "odd"
    odd.mkdir()
    (odd / ".git").write_bytes(b"not a gitdir line\n")
    assert _is_test_leak(odd, _PYTEST_TMP_ROOTS) is True
