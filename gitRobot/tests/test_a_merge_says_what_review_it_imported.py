"""merge() prices the review rounds it IMPORTED, on the receipt, at merge time.

⭐ ZeroParadox 2026-10-03, policy ratified by Tim: unchanged imported bytes owe nothing; genuinely
unjudged imported bytes are owed by the importing session, and the bill must surface HERE, not at
push. Measured 2026-09-24: a session-start merge turned a two-file fix into a fourteen-signature
bill nobody saw coming.

⛔ The object is asserted, not just the number: the ledger must be asked about PRE-MERGE HEAD ..
MERGE COMMIT. The fork point would bill this side's own changes as imported (the ledger-side test
`test_a_merge_owes_only_what_it_imports` measures that difference), and a receipt carrying the
right count against the wrong base would pass every count-only assertion.
"""

import subprocess

from core import ledger as ledger_client


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True).stdout.strip()


def _diverge(repo):
    """`side` changes theirs.txt; illustrated changes ours.txt. Returns pre-merge HEAD."""
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "theirs.txt").write_bytes(b"from side\n")
    _git(repo, "add", "theirs.txt")
    _git(repo, "commit", "-qm", "side change")
    _git(repo, "checkout", "-q", "illustrated")
    (repo / "ours.txt").write_bytes(b"from illustrated\n")
    _git(repo, "add", "ours.txt")
    _git(repo, "commit", "-qm", "our change")
    return _git(repo, "rev-parse", "HEAD")


def test_the_receipt_prices_the_import_against_the_pre_merge_head(robot, repo,
                                                                  committed_gate, monkeypatch):
    pre = _diverge(repo)
    asked = []

    def fake_owed(base, tip, admission=None):
        asked.append((base, tip))
        return {"ok": True, "checked": True, "owed_count": 2,
                "owed_paths": ["theirs.txt"], "owed_by_step": {"editorial": 1, "adversary": 1},
                "owed": [{"step": "editorial", "path": "theirs.txt", "git_blob_id": "b"},
                         {"step": "adversary", "path": "theirs.txt", "git_blob_id": "b"}]}

    monkeypatch.setattr(ledger_client, "owed", fake_owed)
    out = robot.merge("side", reason="price the import")

    assert out["decision"] == "allowed" and out["merged"] is True
    post = robot.git.head()
    assert asked == [(pre, post)], f"asked about {asked}, expected the pre-merge HEAD..merge"
    iu = out["imports_unjudged"]
    assert iu["state"] == "KNOWN"
    assert (iu["base"], iu["tip"]) == (pre, post)
    assert iu["owed_count"] == 2 and iu["paths"] == 1
    assert iu["by_step"] == {"editorial": 1, "adversary": 1}
    assert "PRE-MERGE HEAD" in iu["prices"], "a number must be quoted beside what it prices"


def test_an_unreachable_ledger_is_unknown_never_zero_and_never_blocks(robot, repo,
                                                                      committed_gate):
    """⛔ The autouse fixture makes the ledger UNREACHABLE. The merge has already committed, so
    disclosure must not throw — and must not read as 'nothing owed'."""
    _diverge(repo)

    out = robot.merge("side", reason="ledger down")

    assert out["decision"] == "allowed" and out["merged"] is True
    iu = out["imports_unjudged"]
    assert iu["state"] == "UNKNOWN"
    assert iu["owed_count"] is None
    assert "could not price" in iu["why"]


def test_a_ledger_that_could_not_tell_is_unknown(robot, repo, committed_gate, monkeypatch):
    _diverge(repo)
    monkeypatch.setattr(ledger_client, "owed", lambda *a, **k: {
        "ok": True, "checked": False, "why": "no admission set", "owed_count": None})

    iu = robot.merge("side", reason="unpriced")["imports_unjudged"]

    assert iu["state"] == "UNKNOWN" and iu["owed_count"] is None
    assert iu["why"] == "no admission set"


def test_an_up_to_date_merge_imports_nothing(robot, repo, committed_gate):
    _git(repo, "branch", "same")

    out = robot.merge("same", reason="nothing to bring")

    assert out["merged"] is False
    assert out["imports_unjudged"]["state"] == "NOTHING_MERGED"
    assert out["imports_unjudged"]["owed_count"] == 0
