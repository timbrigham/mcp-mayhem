"""`can_push(range)` — every commit the push publishes, not just the tip.

⚠⚠ THIS FILE EXISTS BECAUSE THE GATE ASKED THE WRONG QUESTION. `push` consulted the
ledger about `HEAD` alone. A push publishes a RANGE — measured 2026-08-23, a push
logged `scope 1 ref(s) — range 5892cbc..55f2d6a`, 43 commits — so gating the tip
certified the content that would EXIST while every intermediate commit rode along
unexamined. Those commits are just as published: fetchable, bisectable, citable
forever. `crossref` measured eight of them at NOT_RUN.

That is SCOPE-1 reborn inside the fix for SCOPE-1 — certifying a different subject
from the one being promoted.

§12-0-alpha also fixes WHO computes: the client hands over a range EXPRESSION and
obeys the answer. A client that resolved the commits itself would be the second
implementation this integration exists to remove.
"""

import subprocess

import pytest

from core import canpush as canpush_mod


def _repo(tmp_path, n=3):
    """A repo with `n` commits on top of an initial one, and a fake 'remote' ref."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True,
                   capture_output=True)
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    def commit(name, body):
        (tmp_path / name).write_text(body, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", name], cwd=tmp_path, check=True,
                       capture_output=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                              capture_output=True, text=True).stdout.strip()

    # ⚠ Each commit REWRITES a shared file, so its blob differs at every commit. An
    # earlier version of this fixture added a NEW file each time, which left every
    # shared blob identical across the range — so a record made at the tip covered
    # every commit, and the headline test passed while proving nothing.
    base = commit("doc.md", "revision base")
    shas = [commit("doc.md", f"revision {i}") for i in range(n)]
    return base, shas


def _blob(tmp_path, ref, path):
    out = subprocess.run(["git", "ls-tree", "-r", ref], cwd=tmp_path,
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        meta, p = line.split("\t", 1)
        if p.strip() == path:
            return meta.split()[2]
    return None


def _rec(step, path, blob, basis):
    return {"id": f"{step}@{basis}#0", "step": step, "verdict": "PASS", "revision": 0,
            "decided": {"how": "signature", "who": "t", "passes": 1, "agreed": 1},
            "subjects": [{"path": path, "git_blob_id": blob}],
            "basis": {"kind": "tree", "value": basis}}


def _check(ledger, tmp_path, rev_range, records=(), admission=("check_prose",),
           commit_admission=None, **kw):
    # ⚠ commit_admission defaults to the same set: most controls here are about the
    # RANGE, not the tip/commit split, and leaving it None would make them exercise
    # the UNSET refusal instead of what they name.
    return canpush_mod.check(
        records=list(records), config=ledger.config, repo=str(tmp_path),
        rev_range=rev_range, admission=list(admission),
        commit_admission=list(admission if commit_admission is None
                              else commit_admission), **kw)


# -- ⭐ THE HEADLINE: a green tip does not carry the range --------------------

def test_a_satisfied_tip_does_not_authorise_the_commits_beneath_it(ledger, tmp_path):
    """⭐⭐ THE EXACT DEFECT. Satisfy every key for the TIP only, and assert the range
    is still refused because the commits under it were never examined. Before this,
    the tip's verdict spoke for all 43."""
    base, shas = _repo(tmp_path, n=3)
    tip = shas[-1]
    # every path at the tip is covered, so an inventory AT THE TIP is complete
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, tip, "doc.md"), tip)]

    result = _check(ledger, tmp_path, f"{base}..{tip}", records)
    assert result["commits_in_range"] == 3
    assert result["allowed"] is False
    assert result["blocking_count"] == 2      # the two beneath the tip
    assert result["commits"][-1]["complete"] is True    # the tip itself is fine


def test_every_commit_covered_allows_the_range(ledger, tmp_path):
    base, shas = _repo(tmp_path, n=2)
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, sha, "doc.md"), sha)
               for sha in shas]
    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records)
    assert result["allowed"] is True and result["blocking_count"] == 0


# -- ⚠ absence must never render as success -----------------------------------

def test_an_unresolvable_range_refuses_rather_than_reporting_nothing(ledger, tmp_path):
    """⚠ "no commits found" and "the range is nonsense" must not render the same."""
    _repo(tmp_path, n=1)
    result = _check(ledger, tmp_path, "nope..alsonope")
    assert result["ok"] is False and result["allowed"] is False
    assert "could not be resolved" in result["why"]


def test_an_empty_range_is_named_not_treated_as_green(ledger, tmp_path):
    """⚠ Pushing nothing is legitimate; rendering it as "all keys satisfied" is not."""
    base, shas = _repo(tmp_path, n=1)
    result = _check(ledger, tmp_path, f"{shas[-1]}..{shas[-1]}")
    assert result["allowed"] is True and result["empty_range"] is True
    assert "publishes no commits" in result["why"]


def test_an_over_long_range_REFUSES_rather_than_truncating(ledger, tmp_path):
    """⭐ An answer about part of a range renders identically to one about all of it.
    crossref caps and reports; here the safe move is to refuse outright, because the
    caller is about to make an irreversible change on the strength of the answer."""
    base, shas = _repo(tmp_path, n=4)
    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", limit=2)
    assert result["allowed"] is False
    assert "REFUSED rather than truncated" in result["why"]
    assert result["commits_in_range"] == 4


# -- the union is what a human acts on ----------------------------------------

def test_the_union_of_remaining_work_is_reported(ledger, tmp_path):
    base, shas = _repo(tmp_path, n=2)
    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}")
    assert result["missing"] == ["check_prose"]


def test_render_names_commits_and_never_hides_how_many_it_omitted(ledger, tmp_path):
    """⚠ GRB-4's lesson: `history()` returned 194,296 characters at its own default,
    unreadable at the moment it was needed. So the render is capped — but the COUNT
    of un-shown commits is always printed, because showing five of forty-six silently
    would render like a complete answer."""
    base, shas = _repo(tmp_path, n=8)
    line = canpush_mod.render(_check(ledger, tmp_path, f"{base}..{shas[-1]}"))
    assert "commits short (8)" in line
    assert "and 3 more" in line              # 8 blocking, 5 shown
    assert len(line.splitlines()) < 20


# -- ⚠ the admission set still governs ----------------------------------------

def test_an_unset_admission_set_is_not_an_empty_one(ledger, tmp_path):
    """⚠ `admission=None` means nobody said what gates this. It must not read as
    "nothing required" — the state that let a push through on 2026-08-23."""
    base, shas = _repo(tmp_path, n=1)
    result = canpush_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                               rev_range=f"{base}..{shas[-1]}", admission=None)
    assert result["admission_state"] == "UNSET"
    assert result["admitted"] is None


# -- ⭐ a later verdict must not retract an earlier one -----------------------

def test_a_newer_verdict_does_not_erase_an_older_commits_coverage(ledger, tmp_path):
    """⭐⭐ THE DEFECT RANGE GATING EXPOSED, kept as its own control.

    The index used to keep ONE tip record per (step, path). Recording `check_prose`
    for `doc.md` at commit 3 therefore ERASED the coverage of `doc.md` at commits 1
    and 2. Invisible while only the tip was ever asked about; fatal for a range, where
    every commit but the last then reads STALE however diligently it was checked at
    the time.

    A verdict is about CONTENT. It stays true for any commit holding that content, and
    nothing recorded later can make it false.
    """
    base, shas = _repo(tmp_path, n=3)
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, sha, "doc.md"), sha)
               for sha in shas]

    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records)
    assert result["allowed"] is True, "the newest verdict retracted the older ones"
    assert [r["complete"] for r in result["commits"]] == [True, True, True]


def test_the_middle_commit_alone_can_be_the_one_short(ledger, tmp_path):
    """⚠ Proves the answer is per-commit rather than an aggregate that happens to
    agree. Cover the ends, leave the middle bare."""
    base, shas = _repo(tmp_path, n=3)
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, sha, "doc.md"), sha)
               for sha in (shas[0], shas[2])]

    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records)
    assert result["allowed"] is False
    assert result["blocking_count"] == 1
    assert [r["complete"] for r in result["commits"]] == [True, False, True]
    assert result["commits"][1]["commit"] == shas[1]


# -- ⭐ the tip is judged as a PUSH; the commits under it as COMMITS ----------

def test_review_types_are_required_of_the_tip_only(ledger, tmp_path):
    """⭐⭐ MY DEFECT, found by ZeroParadox. `can_push` asked action="push" of EVERY
    commit, so each intermediate one owed `adversary`, `editorial` and `prior_art` —
    three agent rounds apiece, 129 for a 43-commit range. That is not a strict gate,
    it is an unsatisfiable one.

    The registry already said otherwise and this ignored it: those three carry
    `actions: ["push", "tag"]`, which IS the statement that they judge the work being
    PUBLISHED rather than each step of reaching it.
    """
    base, shas = _repo(tmp_path, n=3)
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, sha, "doc.md"), sha)
               for sha in shas]
    # `adversary` gates the push; only `check_prose` gates a commit
    records.append(_rec("adversary", "doc.md",
                        _blob(tmp_path, shas[-1], "doc.md"), shas[-1]))

    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records,
                    admission=("check_prose", "adversary"),
                    commit_admission=("check_prose",))
    assert result["allowed"] is True, "a review key was demanded of an intermediate commit"
    assert [r["judged_as"] for r in result["commits"]] == ["commit", "commit", "push"]
    assert [r["is_tip"] for r in result["commits"]] == [False, False, True]


def test_the_tip_still_carries_the_full_push_bar(ledger, tmp_path):
    """⚠ THE CONTROL THAT KEEPS THE SPLIT FROM BEING A HOLE. Relaxing intermediate
    commits must not relax the thing actually being published."""
    base, shas = _repo(tmp_path, n=2)
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, sha, "doc.md"), sha)
               for sha in shas]          # no `adversary` anywhere

    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records,
                    admission=("check_prose", "adversary"),
                    commit_admission=("check_prose",))
    assert result["allowed"] is False
    assert result["commits"][-1]["complete"] is False
    assert "adversary" in result["commits"][-1]["missing"]
    assert all(r["complete"] for r in result["commits"][:-1])


def test_intermediate_commits_still_earn_the_full_commit_set(ledger, tmp_path):
    """⭐ NOTHING IS WEAKENED. The property range gating exists for — no commit lands
    unexamined — is unchanged; only WHICH bar applies to which commit moved."""
    base, shas = _repo(tmp_path, n=3)
    records = [_rec("check_prose", "doc.md", _blob(tmp_path, sha, "doc.md"), sha)
               for sha in (shas[0], shas[2])]      # the middle commit earns nothing

    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records,
                    commit_admission=("check_prose",))
    assert result["allowed"] is False
    assert result["commits"][1]["complete"] is False


def test_an_absent_commit_admission_set_refuses(ledger, tmp_path):
    """⚠ Absent is not empty, on this parameter too. Omitting it must not quietly
    mean "intermediate commits require nothing"."""
    base, shas = _repo(tmp_path, n=2)
    result = canpush_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                               rev_range=f"{base}..{shas[-1]}",
                               admission=["check_prose"], commit_admission=None)
    assert result["allowed"] is False
    assert result["commits"][0]["admission_state"] == "UNSET"


# -- ⭐ the gate names what the audit does not claim ---------------------------

def test_can_push_reports_how_much_of_the_range_is_below_the_audit_floor(ledger,
                                                                         tmp_path):
    """⭐⭐ THE GAP BETWEEN TWO CORRECT TOOLS. Measured 2026-08-23: 174 unpushed
    commits, 23 above the genesis floor, 151 below. Those 151 are in BOTH tools' scope
    and NEITHER tool's answer — `can_push` walks the raw range and refuses them, while
    `crossref` stops at the floor and claims nothing. Each is right under its own
    scoping, and together they read as "the audit is clean and the push is refused,
    about the same commits".

    ⚠ The fix is NOT to move the floor. That would audit nothing; it would only lower
    where judgement starts so the audit *says* something — a claim nobody made, and
    the thing Tim declined. So the gate reports it instead.
    """
    base, shas = _repo(tmp_path, n=4)
    records = [{"id": "genesis@x#0", "step": "genesis", "verdict": "PASS",
                "revision": 0,
                "decided": {"how": "signature", "who": "t", "passes": 1, "agreed": 1},
                "subjects": [{"path": "<genesis>", "git_blob_id": shas[1]}],
                "basis": {"kind": "tree", "value": shas[1]}}]

    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records)
    assert result["commits_in_range"] == 4
    assert result["audit_floor"] == shas[1]
    # the floor commit and everything under it inside this range
    assert result["commits_below_audit_floor"] == 2
    assert "BELOW the genesis floor" in result["audit_note"]
    assert "Neither tool is wrong" in result["audit_note"]
    assert result["audit_note"] in canpush_mod.render(result)


def test_no_audit_note_when_the_whole_range_is_above_the_floor(ledger, tmp_path):
    """⚠ …and it must stay quiet when the two scopes actually meet."""
    base, shas = _repo(tmp_path, n=3)
    records = [{"id": "genesis@x#0", "step": "genesis", "verdict": "PASS",
                "revision": 0,
                "decided": {"how": "signature", "who": "t", "passes": 1, "agreed": 1},
                "subjects": [{"path": "<genesis>", "git_blob_id": base}],
                "basis": {"kind": "tree", "value": base}}]
    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}", records)
    assert result["commits_below_audit_floor"] == 0
    assert result["audit_note"] is None


def test_no_floor_means_no_claim_either_way(ledger, tmp_path):
    """⚠ With no genesis record there is no floor, so the gate must not invent one —
    and must not imply the audit covered anything."""
    base, shas = _repo(tmp_path, n=2)
    result = _check(ledger, tmp_path, f"{base}..{shas[-1]}")
    assert result["audit_floor"] is None
    assert result["audit_note"] is None
