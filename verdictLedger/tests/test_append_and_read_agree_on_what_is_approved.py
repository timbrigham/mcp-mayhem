"""V16c and `evidence_stale` must not ask the same question of different registries.

⛔⛔ THE THIRD TIME THIS PAIR WAS UNSATISFIABLE, ON THE SAME STEP. Measured 2026-09-27 at
`guards@8192e54`:

    V16c, at APPEND, reads `config.required`      ->  approves ONLY 7dbd4741 (today's)
    evidence_stale, at READ, read `pin_types`     ->  approved ONLY b6e81935 (the ref's)

So citing the ref's blob was REFUSED at append, and citing today's approved blob appended and never
cleared. **No record could satisfy both**, and the consumer wrote THREE correctly-shaped records
against two successive wrong diagnoses of mine before I stopped theorising and traced the actual
decision — which named both values in one line.

⚠⚠ NEITHER HALF WAS WRONG ALONE, WHICH IS WHY IT SURVIVED TWO FIXES:
  * per-ref at READ is Tim's ruling of 2026-09-13 (RLY-PIN-5, option C) and is measured better —
    against today's registry, 13/20 of the pushed arc and 86/93 of the last 93 commits went stale,
    versus 3/20 and 54/93 per-ref.
  * live at APPEND is defensible on its own terms: a NEW verdict should not come from a build
    nobody currently approves.
  * the 2026-09-12 fix made an approved blob count as fresh and WORKED while both sides read one
    registry. The 09-13 per-ref ruling re-opened the hole from the other direction, and the
    interaction went unchecked because that ruling was argued on staleness rates.

⭐ THE UNION IS THE SMALLEST SATISFIABLE ANSWER: a citation approved by the registry that governed
the content WHEN IT WAS COMMITTED, or by the registry governing it NOW, is approved by a registry
with standing over it either way.
"""

import json
import pathlib
import subprocess

import pytest

from core import inventory as inv


def _repo_with_a_moved_checker(tmp_path):
    """A repo where the checker AND its approval both moved after the commit being judged.

    ⭐ THIS FIXTURE IS THE DELIVERABLE. The bug needs THREE things true at once — a historical
    ref, a checker whose blob moved since, and a registry whose `approved_modules` moved with it —
    and no existing fixture produced that combination, which is why three rounds of reasoning
    missed it and one trace found it.
    """
    import os
    r = tmp_path
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, capture_output=True)
    for a in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)
    os.makedirs(r / "tools" / "verify", exist_ok=True)

    def commit(msg):
        subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", msg], cwd=r, check=True, capture_output=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=r,
                              capture_output=True, text=True).stdout.strip()

    def blob(path):
        return subprocess.run(["git", "rev-parse", "HEAD:" + path], cwd=r,
                              capture_output=True, text=True).stdout.strip()

    # v1 of the checker, approved by the registry committed alongside it
    (r / "tools" / "verify" / "guards.py").write_text("v1\n", encoding="utf-8")
    (r / "doc.md").write_text("content\n", encoding="utf-8")
    commit("v1 checker")
    old_blob = blob("tools/verify/guards.py")
    reg = {"schema": "zp.required.v2", "default": {"required": True},
           "types": {"guards": {"family": "mechanical", "scope": ["*.md"],
                                "module": "tools/verify/guards.py",
                                "approved_modules": [old_blob],
                                "reason": "fixture"}}}
    (r / "tools" / "verify" / "required.v2.json").write_text(json.dumps(reg, indent=2),
                                                            encoding="utf-8")
    historical = commit("registry approving v1")

    # v2 of the checker, and the registry moves its approval with it
    (r / "tools" / "verify" / "guards.py").write_text("v2 — changed\n", encoding="utf-8")
    commit("v2 checker")
    new_blob = blob("tools/verify/guards.py")
    reg["types"]["guards"]["approved_modules"] = [new_blob]
    (r / "tools" / "verify" / "required.v2.json").write_text(json.dumps(reg, indent=2),
                                                            encoding="utf-8")
    commit("registry approving v2")
    return historical, old_blob, new_blob


def _files_at(repo, ref):
    out = subprocess.run(["git", "ls-tree", "-r", ref], cwd=repo,
                         capture_output=True, text=True).stdout
    files = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        files[path] = meta.split()[2]
    return files


def _cfg(repo):
    """The FIXTURE's registry, with the shipped sample policy.

    ⚠ `required_path` points into the temp repo on purpose: `registry_types_at` resolves the
    registry's path RELATIVE to the repo to find its committed blob, so a registry living outside
    the repo makes the per-ref lookup unresolvable and the whole fixture vacuous.
    """
    from core.config import Config
    root = pathlib.Path(__file__).resolve().parents[1]
    return Config(policy_path=root / "config" / "policy.v1.sample.json",
                  required_path=repo / "tools" / "verify" / "required.v2.json")


def _rec(blob_cited, subject_blob, basis):
    return {"schema": "zp.record.v1", "step": "guards", "tier": "M", "verdict": "PASS",
            "reason": None, "basis": {"kind": "tree", "value": basis, "resolved_from": "explicit"},
            "subjects": [{"path": "doc.md", "git_blob_id": subject_blob}],
            "evidence": [{"path": "tools/verify/guards.py", "git_blob_id": blob_cited}],
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
            "inputs": [], "revision": 0,
            "cost": {"seconds": 1.0, "seconds_prices": "fixture"},
            "run": {"id": "r", "started": None, "config_sha": None, "env": {}}}


def _row(repo, ref, records):
    files = _files_at(repo, ref)
    i = inv.build(config=_cfg(repo), records=records, action="commit", files=files,
                  admission=["guards"], repo=str(repo))
    return next((r for r in i["rows"] if r["step"] == "guards"), None), files


# -- ⭐⭐ the headline: a citation of EITHER approved build is fresh ------------

def test_a_citation_of_todays_approved_build_clears_a_historical_ref(tmp_path):
    """⭐⭐ THE CASE THAT WAS UNSATISFIABLE. Today's approved blob is what V16c will ACCEPT at
    append, so it must also be what the read side counts as fresh — otherwise the only appendable
    record is the only one that never clears."""
    hist, old_blob, new_blob = _repo_with_a_moved_checker(tmp_path)
    files = _files_at(tmp_path, hist)
    row, _ = _row(tmp_path, hist, [_rec(new_blob, files["doc.md"], files["doc.md"])])
    assert row["evidence_stale"] == 0, (
        f"a record citing TODAY's approved build still reads stale at a historical ref, so the "
        f"only record V16c accepts is the only one that cannot clear: {row.get('evidence_moved')}")


def test_a_citation_of_the_ref_era_approved_build_also_clears(tmp_path):
    """⚠ THE OTHER HALF OF THE UNION, AND IT IS TIM'S 09-13 RULING. The registry committed
    alongside the content approved that build; history's honest answer must keep working."""
    hist, old_blob, new_blob = _repo_with_a_moved_checker(tmp_path)
    files = _files_at(tmp_path, hist)
    row, _ = _row(tmp_path, hist, [_rec(old_blob, files["doc.md"], files["doc.md"])])
    assert row["evidence_stale"] == 0, (
        "the per-ref approval stopped counting, which reverses Tim's 2026-09-13 ruling")


# -- ⛔⛔ and RLY-PIN-5 must stay closed ---------------------------------------

def test_a_blob_no_registry_ever_approved_is_still_stale(tmp_path):
    """⛔⛔ THE CONTROL THAT MAKES THE UNION SAFE, AND IT IS THE CASE THE PER-REF PIN EXISTS FOR.
    `RLY-PIN-5`: a blob approved once, then UNPINNED, must not freshen a commit that reverts to it.
    The union admits only blobs some registry WITH STANDING approved — neither the ref's nor
    today's approves an unpinned build, so it stays stale.

    ⚠ Without this the union would be indistinguishable from deleting the check."""
    hist, old_blob, new_blob = _repo_with_a_moved_checker(tmp_path)
    files = _files_at(tmp_path, hist)
    never = "f" * 40          # approved by no registry, at any point
    row, _ = _row(tmp_path, hist, [_rec(never, files["doc.md"], files["doc.md"])])
    assert row["evidence_stale"] == 1, (
        "a blob NO registry ever approved was accepted as fresh evidence — the union widened into "
        "deleting the check, and RLY-PIN-5 is reopened")
    assert "tools/verify/guards.py" in (row.get("evidence_moved") or [])


# -- ⚠ the two checks must agree by construction, not by coincidence ----------

def test_v16c_and_the_read_side_accept_the_same_citation(tmp_path, ledger):
    """⛔⛔ THE PAIR TEST, WHICH IS THE ONE NOBODY WROTE FOR THREE ROUNDS. Each check was tested
    alone and both passed; the defect lived only in their conjunction.

    ⚠ Asserted as: every blob V16c would ACCEPT at append must be a blob the read side counts as
    FRESH. If that ever stops holding, the appendable record and the clearing record are different
    records and the block is unsatisfiable again.
    """
    hist, old_blob, new_blob = _repo_with_a_moved_checker(tmp_path)
    files = _files_at(tmp_path, hist)
    cfg = _cfg(tmp_path)
    # what V16c accepts: the LIVE registry's approved set
    live = set((cfg.required["types"]["guards"].get("approved_modules")) or [])
    assert new_blob in live and old_blob not in live, "fixture no longer models a moved approval"
    for blob in sorted(live):
        row, _ = _row(tmp_path, hist, [_rec(blob, files["doc.md"], files["doc.md"])])
        assert row["evidence_stale"] == 0, (
            f"V16c would accept a record citing {blob[:12]} and the read side still calls it "
            f"stale. That is the unsatisfiable conjunction, back for a fourth time.")
