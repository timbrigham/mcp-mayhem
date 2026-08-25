"""§12j — the identity of what a gate is about to certify. VERIFY, never DERIVE.

⚠⚠ THE INVERSION IS THE WHOLE POINT AND IT IS WHY THIS TOOL EXISTS AT ALL.
ZeroParadox's `common.ledger_subjects` DERIVES the blob from the index at RECORD
time. For a mechanical checker that is sound — read and record are milliseconds apart
in one process, and its worktree-vs-index fence closes the remainder.

For a REVIEW agent the same call sits MINUTES after the read. The silent case,
measured by ZeroParadox 2026-08-25:

    agent reads blob X  ->  file changes to Y AND IS STAGED  ->  at record time
    worktree == index == Y  ->  NO FENCE FIRES  ->  the record names Y

The verdict then certifies content nobody examined, and nothing anywhere reports it.
Drift-and-REVERT is harmless for the same reason the fence looked sufficient — same
content, same blob. It is drift-and-STAY that lies, and a deriving implementation is
blind to it by construction rather than by oversight.

`test_the_case_a_deriving_implementation_cannot_see` is that exact scenario, and it
is the reason `observed` is mandatory rather than optional.
"""

import subprocess

import pytest

from core.errors import UsageError


def _git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _blob(repo, path):
    return _git(repo, "hash-object", "--", path).strip()


def _write(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    return _blob(repo, name)


# -- ⭐⭐ the case that motivates the whole design ------------------------------

def test_the_case_a_deriving_implementation_cannot_see(robot, repo):
    """⭐⭐ READ X, FILE BECOMES Y **AND IS STAGED**, RECORD LATER. The worktree and
    the index agree, so every fence a deriving implementation has is silent — and it
    would hand back a subject naming Y, content the gate never looked at."""
    read_blob = _blob(repo, "tracked.txt")            # what the agent examined
    _write(repo, "tracked.txt", "rewritten while the agent was thinking\n")
    _git(repo, "add", "tracked.txt")                  # worktree == index == Y

    out = robot.ledger_subjects({"tracked.txt": read_blob})

    assert out["subjects"] == [], "it must not certify content nobody examined"
    assert len(out["skipped"]) == 1
    sk = out["skipped"][0]
    assert sk["observed"] == read_blob
    assert sk["at_ref"] != read_blob
    assert "DRIFTED SINCE YOU READ IT" in sk["why"]


def test_drift_and_revert_is_not_a_skip(robot, repo):
    """⚠ THE CONTROL, and it is Tim's blob argument doing the work: a blob is
    immutable, so a file that changed and changed back is the SAME content and the
    same id. Flagging it would be noise — and noise is what makes a fence get
    disabled."""
    read_blob = _blob(repo, "tracked.txt")
    _write(repo, "tracked.txt", "temporarily different\n")
    _write(repo, "tracked.txt", "original\n")
    _git(repo, "add", "tracked.txt")

    out = robot.ledger_subjects({"tracked.txt": read_blob})
    assert out["skipped"] == []
    assert out["subjects"] == [{"path": "tracked.txt", "git_blob_id": read_blob}]


# -- ⚠ the contract's own control: skipped must be SEEN to fire ---------------

def test_a_worktree_edit_that_is_not_staged_is_fenced(robot, repo):
    """⚠ §12j: "stage a file, modify it in the worktree, call with both paths — the
    drifted one must appear in skipped and NOT in subjects. A run where skipped is
    always empty has never been shown to fence anything." """
    clean = _write(repo, "clean.txt", "staged and left alone\n")
    _git(repo, "add", "clean.txt")
    _write(repo, "drifting.txt", "staged\n")
    _git(repo, "add", "drifting.txt")
    staged_blob = _blob(repo, "drifting.txt")
    _write(repo, "drifting.txt", "then edited in the worktree\n")   # NOT staged
    worktree_blob = _blob(repo, "drifting.txt")

    out = robot.ledger_subjects({"clean.txt": clean,
                                 "drifting.txt": worktree_blob})
    paths = [s["path"] for s in out["subjects"]]
    assert "clean.txt" in paths
    assert "drifting.txt" not in paths
    assert out["skipped"][0]["path"] == "drifting.txt"
    assert staged_blob[:12] in out["skipped"][0]["why"]


def test_an_untracked_path_is_fenced_with_its_reason(robot, repo):
    """⚠ Nothing will ever be able to tell whether an untracked file changed, so it
    cannot be a subject — and the caller must be told, not silently handed fewer."""
    blob = _write(repo, "scratch.txt", "never added\n")
    out = robot.ledger_subjects({"scratch.txt": blob})
    assert out["subjects"] == []
    assert "not tracked" in out["skipped"][0]["why"]


def test_skipped_carries_both_ids_so_the_caller_can_act(robot, repo):
    """⚠ A reason without the two values is a reason nobody can check."""
    read_blob = _blob(repo, "tracked.txt")
    _write(repo, "tracked.txt", "moved\n")
    _git(repo, "add", "tracked.txt")
    sk = robot.ledger_subjects({"tracked.txt": read_blob})["skipped"][0]
    assert set(sk) >= {"path", "observed", "at_ref", "why"}


# -- ⭐ the basis, and why INDEX needs write-tree ------------------------------

def test_the_basis_is_the_tree_the_pending_commit_will_carry(robot, repo):
    """⭐ `ref='INDEX'` is the case a review gate actually runs on — it reviews what
    is STAGED, before the commit exists — and the only one `write-tree` is needed
    for."""
    _write(repo, "tracked.txt", "staged change\n")
    _git(repo, "add", "tracked.txt")
    basis = robot.ledger_subjects({"tracked.txt": _blob(repo, "tracked.txt")})["basis"]
    assert basis["kind"] == "tree"
    assert basis["resolved_from"] == "explicit"
    assert basis["value"] == _git(repo, "write-tree").strip()


def test_the_index_tree_survives_the_commit_of_that_index(robot, repo):
    """⭐⭐ WHY RECORDING AGAINST THE INDEX IS NOT A RACE. ZeroParadox verified this
    against the ledger 2026-08-25 and had been telling Tim the opposite: committing an
    UNCHANGED index re-stales nothing, because the commit carries exactly that tree.
    Editing after recording is what stales things."""
    _write(repo, "tracked.txt", "about to be committed\n")
    _git(repo, "add", "tracked.txt")
    before = robot.ledger_subjects({"tracked.txt": _blob(repo, "tracked.txt")})["basis"]
    _git(repo, "commit", "-q", "-m", "commit the index unchanged")
    assert _git(repo, "rev-parse", "HEAD^{tree}").strip() == before["value"]


def test_a_committed_ref_also_works(robot, repo):
    """⚠ Post-commit recording is legitimate and must not need the index."""
    out = robot.ledger_subjects({"tracked.txt": _blob(repo, "tracked.txt")}, ref="HEAD")
    assert out["subjects"][0]["path"] == "tracked.txt"
    assert out["basis"]["value"] == _git(repo, "rev-parse", "HEAD^{tree}").strip()


# -- ⚠⚠ mandatory, with no deriving fallback ----------------------------------

def test_observed_is_mandatory_and_there_is_no_derive_mode(robot, repo):
    """⚠⚠ AN `observed=None` THAT QUIETLY DERIVED WOULD PUT THE SILENT CASE BACK for
    every caller that forgot — the two-route shape §12-0-alpha exists to refuse, where
    the weaker route wins exactly when you least want it to. The refusal names what to
    do instead, or it just produces a workaround."""
    for bad in ({}, None):
        with pytest.raises(UsageError, match="observed"):
            robot.ledger_subjects(bad)
    with pytest.raises(UsageError, match="blob id"):
        robot.ledger_subjects({"tracked.txt": "not-a-blob"})


def test_it_writes_no_ledger_row_and_is_audited_as_a_mutation(robot, repo):
    """⚠ §12d is untouched: gitRobot computes identity, it never records a verdict.
    But `write-tree` DOES write tree objects, so unlike a Tier 3 read this is audited
    like every other mutation."""
    robot.ledger_subjects({"tracked.txt": _blob(repo, "tracked.txt")})
    last = robot.audit.read()[-1]
    assert last["op"] == "ledger_subjects"
    assert last["decision"] == "allowed"
