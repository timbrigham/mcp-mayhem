"""RLY-PIN-5: a producer pin is judged against the registry COMMITTED AT THE REF, at read time.

⛔⛔ THE DEFECT. Measured by ZeroParadox 2026-09-13 and reproduced on the live servers the same
day. `guards.py@2775fcf6` was approved long enough for nine intermediate commits to record
under it, then unpinned at 548b1216. A commit that reverted guards.py to 2775fcf6 on top of the
unpin (dad75d6b, never pushed) read ALLOWED 19/19 with ZERO new records. V16c refused a fresh
record from that build at APPEND; nothing asked the same question at READ, because the at-ref
evidence route accepted any record citing the producer blob found at the ref.

⭐ THE RULING (Tim, option C): judge the pin against required.v2.json as committed at that ref.
At every commit in that arc the committed registry approved exactly the checker blob the commit
carried, so history reads the way it was built. Judging against TODAY's registry instead
re-staled 13/20 of the pushed arc in simulation.

These tests build a real repository because the whole point is reading the registry from git.
"""

import json
import shutil
import subprocess
from pathlib import Path

from core import inventory as inventory_mod
from core.config import Config

ROOT = Path(__file__).resolve().parents[1]
REG = "tools/verify/required.v2.json"
MOD = "tools/verify/guards.py"
OTHER = "tools/verify/batch.py"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def _registry(approved):
    data = json.loads((ROOT / "config" / "required.v2.sample.json").read_text(encoding="utf-8"))
    spec = dict(data["types"]["guards"])
    spec["module"] = MOD
    spec["scope"] = ["tools/verify/*.py"]
    spec["approved_modules"] = list(approved)
    data["types"]["guards"] = spec
    return json.dumps(data, indent=1)


def _commit(repo, message, **files):
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # ⚠ BYTES, not write_text: on Windows write_text emits CRLF, so the blob git commits
        # differs from `hash-object --stdin` over the same str. The first draft of this file
        # did that, every evidence blob mismatched, and the headline test passed because
        # EVERYTHING was stale. The two controls below caught it.
        path.write_bytes(body.encode("utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _files(repo, ref):
    out = _git(repo, "ls-tree", "-r", ref, "--format=%(objectname)%x09%(path)")
    return {ln.split("\t", 1)[1]: ln.split("\t", 1)[0] for ln in out.splitlines()}


def _world(tmp_path):
    """Three commits, the RLY-PIN-5 shape:

        old     guards.py = OLD build, committed registry approves OLD   (recorded here)
        unpin   guards.py = NEW build, committed registry approves NEW only
        revert  guards.py = OLD build again, registry still approves NEW only
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"),
                 ("core.autocrlf", "false")):
        _git(repo, "config", k, v)

    old_body, new_body = "# guards, old build\n", "# guards, new build\n"
    old_blob = _git_hash(repo, old_body)
    new_blob = _git_hash(repo, new_body)

    old = _commit(repo, "old", **{MOD: old_body, OTHER: "batch\n", REG: _registry([old_blob])})
    unpin = _commit(repo, "unpin", **{MOD: new_body, REG: _registry([new_blob])})
    revert = _commit(repo, "revert", **{MOD: old_body})

    # The live registry is the working tree's copy, which is `revert`'s: approves NEW only.
    policy = tmp_path / "policy.v1.json"
    shutil.copy(ROOT / "config" / "policy.v1.sample.json", policy)
    config = Config(policy, repo / REG)

    f_old = _files(repo, old)
    assert f_old[MOD] == old_blob and _files(repo, unpin)[MOD] == new_blob, (
        "fixture blobs drifted from what git committed; every row would read stale")
    record = {"id": f"guards@{old}#0", "step": "guards", "verdict": "PASS", "revision": 0,
              "decided": {"how": "signature", "who": "t", "passes": 1, "agreed": 1},
              "subjects": [{"path": MOD, "git_blob_id": f_old[MOD]},
                           {"path": OTHER, "git_blob_id": f_old[OTHER]}],
              "evidence": [{"path": MOD, "git_blob_id": old_blob}],
              "basis": {"kind": "tree", "value": old}}
    return repo, config, [record], {"old": old, "unpin": unpin, "revert": revert}


def _git_hash(repo, body):
    return subprocess.run(["git", "hash-object", "--stdin"], cwd=str(repo),
                          input=body.encode("utf-8"), capture_output=True,
                          check=True).stdout.decode().strip()


def _row(repo, config, records, ref, *, with_repo=True):
    inv = inventory_mod.build(config=config, records=records, action="push",
                              files=_files(repo, ref), ref=ref, admission=["guards"],
                              repo=str(repo) if with_repo else None)
    return inv, next(r for r in inv["rows"] if r["step"] == "guards")


def test_a_revert_to_an_unpinned_build_reads_stale(tmp_path):
    """⛔⛔ THE HEADLINE. The revert commit carries the OLD build, which its own committed
    registry does not approve. The record citing that build was real and made while it was
    approved; it must not freshen content committed after the unpin."""
    repo, config, records, refs = _world(tmp_path)
    inv, row = _row(repo, config, records, refs["revert"])

    assert row["status"] == "STALE", row
    assert row["evidence_unapproved"] == [MOD]
    assert inv["complete"] is False
    assert inv["pin_basis"].startswith("ref: tools/verify/required.v2.json@")
    assert "NOT APPROVED" in (row.get("why") or "")


def test_history_recorded_under_its_own_pin_stays_fresh(tmp_path):
    """⭐ THE REASON FOR THE PER-REF RULE. The `old` commit carried the OLD build AND a
    registry approving it, so its record still describes it honestly. Judged against today's
    registry (approves NEW only) this would go stale, which is option A's collateral."""
    repo, config, records, refs = _world(tmp_path)
    inv, row = _row(repo, config, records, refs["old"])

    assert row["status"] == "SATISFIED", row
    assert row["evidence_unapproved"] == []
    assert inv["complete"] is True


def test_without_a_repository_the_check_is_named_as_not_run(tmp_path):
    """⚠ The control that proves the repository is what switches it on, and that its absence
    is disclosed rather than rendering as a check that passed."""
    repo, config, records, refs = _world(tmp_path)
    inv, row = _row(repo, config, records, refs["revert"], with_repo=False)

    assert inv["pin_basis"].startswith("unchecked")
    assert row["status"] == "SATISFIED", "the pre-2026-09-13 behaviour, kept only when no repo is named"


def test_an_unreadable_committed_registry_falls_back_to_the_current_pins(tmp_path):
    """⚠ ABSENCE IS NEVER SUCCESS. If the registry is not tracked in the repository, the
    CURRENT registry's pins apply, which is the stricter reading, and `pin_basis` says why."""
    repo, config, records, refs = _world(tmp_path)
    outside = tmp_path / "elsewhere" / "required.v2.json"
    outside.parent.mkdir()
    shutil.copy(repo / REG, outside)
    config = Config(tmp_path / "policy.v1.json", outside)

    inv, row = _row(repo, config, records, refs["revert"])
    assert inv["pin_basis"].startswith("current: the registry is not tracked")
    assert row["status"] == "STALE" and row["evidence_unapproved"] == [MOD]

    # and the stricter reading is visible on history too: `old` reads stale under today's pins
    inv, row = _row(repo, config, records, refs["old"])
    assert row["evidence_unapproved"] == [MOD]
