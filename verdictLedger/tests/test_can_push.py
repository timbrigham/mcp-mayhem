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


# -- ⛔ "not evaluated" and "refused, N short" are different facts ---------------

def test_an_unset_admission_set_does_not_render_as_commits_short(ledger, tmp_path):
    """⛔⛔ REPORTED BY ZeroParadox 2026-09-03 AGAINST A REAL PUSH. The headline read
    `REFUSED push 13/13 commit(s) short` with every commit at `0/0`, under a correct warning that
    the admission set was not set. Their words: **"the surface reads as a refusal and means
    unconfigured, and those are different facts."**

    ⚠ "SHORT" MEANS MISSING REQUIRED KEYS. With nothing required, nothing is short — so the line
    asserted thirteen failures where zero checks had run. A caller reading it concludes their
    commits failed; the truth is nobody said what to check.

    ⚠ `allowed` STAYS FALSE — an unconfigured gate fails closed. Only the rendering changes."""
    base, shas = _repo(tmp_path, n=2)
    result = canpush_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                               rev_range=f"{base}..{shas[-1]}", admission=None,
                               commit_admission=None)
    text = canpush_mod.render(result)

    assert result["allowed"] is False, "an unconfigured gate must still fail closed"
    # ⚠ The precise phrase, not the bare word — the explanation deliberately SAYS "none of them
    # is 'short'", and an over-broad assertion would forbid the sentence that does the correcting.
    assert "commit(s) short" not in text, (
        "the headline still claims commits are SHORT when nothing was required of them")
    assert "0/0" not in text, (
        "a per-commit 0/0 reads as satisfied-of-required rather than nothing-was-asked")
    assert "NOT EVALUATED" in text


def test_the_unset_render_names_the_exact_call_to_make(ledger, tmp_path):
    """⭐⭐ TIM, 2026-09-03: *"instead of a refusal you include the exact instructions that it
    needs to provide."* §3 says a refusal must name the alternative; the strongest form of that is
    the literal call.

    ⚠ The ledger CANNOT print the step names — the admission set lives in gitRobot's
    `admission.v1.json` and the two-lists separation is deliberate. So it names the TOOL that
    serves them, which is what `requirements(action)` was built for."""
    base, shas = _repo(tmp_path, n=1)
    text = canpush_mod.render(canpush_mod.check(
        records=[], config=ledger.config, repo=str(tmp_path),
        rev_range=f"{base}..{shas[-1]}", admission=None, commit_admission=None))

    assert "requirements(action='push')" in text
    assert "requirements(action='commit')" in text
    assert "commit_admission" in text, "both sets must be named, not just the push set"
    assert f"{base}..{shas[-1]}" in text, "the suggested call must carry the caller's own range"


# -- ⭐⭐ a family that examined nothing must SAY so ---------------------------

def _reload(tmp_path, config_dir):
    """A Ledger reading the registry AS IT IS NOW. `Ledger.config` is built in `__init__`."""
    from core.ledger import Ledger
    return Ledger(tmp_path / "reload.jsonl",
                  policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


def _set_scope(config_dir, step, scope=None, exclude=None):
    """Point one registry type's scope somewhere. Returns nothing; the ledger re-reads live."""
    import json
    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    spec = doc["types"][step]
    if scope is not None:
        spec["scope"] = scope
    if exclude is not None:
        spec["scope_exclude"] = exclude
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def test_a_family_that_examined_nothing_in_the_push_is_named(ledger, tmp_path, config_dir):
    """⭐⭐ THE DETECTOR FOR THE THING A HUMAN CAUGHT BY EYE.

    Measured 2026-09-07: a push of 11 files reported ALLOWED, 19/19 satisfied, 0 blocking,
    with `adversary` and `editorial` both ADMITTED, both SATISFIED, both `gating: true`,
    73/73 subjects and 0 unexamined — and both covering **zero** of the eleven changed paths.
    Their scope is the published prose surface; the push was `CLAUDE.md` and ten files under
    `tools/verify/`. Every number was correct and the review layer had looked at nothing.

    ⚠⚠ It was caught by Tim reading a status line and asking why a step that must gate was
    sitting in a list of things that do not. That question is `scope ∩ changed = ∅` — a set
    intersection over data `check` already holds — and a person must never be the instrument
    for it.

    ⚠ REPORTED, NEVER BLOCKING. `allowed` must not move: whether an unwitnessed path refuses
    a push is the admission set's decision, and shipping it as a gate here would refuse a
    push that every configured rule permits.
    """
    base, shas = _repo(tmp_path, n=1)
    # `adversary` is family=review and admitted; point it away from the only changed file.
    _set_scope(config_dir, "adversary", scope=["nothing/matches/this/*"])
    _set_scope(config_dir, "check_prose", scope=["*.md"])
    # ⚠ A FRESH Ledger. `Ledger.config` is loaded in __init__ and is NOT re-read, so the
    # injected fixture still holds the registry as it was before `_set_scope`.
    led = _reload(tmp_path, config_dir)

    out = _check(led, tmp_path, f"{base}..{shas[-1]}",
                 admission=("check_prose", "adversary"))

    w = out["witness"]
    assert w["resolved"] is True
    assert w["changed_paths"] == 1, "doc.md is rewritten by the fixture's every commit"
    assert w["witnessed_by_family"]["mechanical"] == 1, "check_prose scopes *.md"
    assert w["witnessed_by_family"]["review"] == 0, (
        "adversary is admitted and scoped elsewhere, so the review family witnessed nothing")
    assert w["unwitnessed_by_family"]["review"] == ["doc.md"], (
        "the unwitnessed PATHS must be named — a count alone cannot be acted on")

    text = canpush_mod.render(out)
    assert "NO REVIEW STEP EXAMINED THIS PUSH" in text, (
        "a caller reading the rendered line must see it; the push_bar_source defect was "
        "invisible for three days precisely because it lived only in the payload")
    assert "doc.md" in text
    assert "NOT blocking" in text, "the line must say it is disclosure, not a refusal"


def test_the_witness_is_silent_when_every_family_looked(ledger, tmp_path, config_dir):
    """⚠ THE CONTROL. A warning that fires on every push is wallpaper, and `relaxations`
    already has a test for exactly this reason. If both families cover the changed paths,
    `unwitnessed_by_family` must be EMPTY and the rendered line must carry no warning."""
    base, shas = _repo(tmp_path, n=1)
    _set_scope(config_dir, "adversary", scope=["*.md"], exclude=[])
    _set_scope(config_dir, "check_prose", scope=["*.md"])
    led = _reload(tmp_path, config_dir)

    out = _check(led, tmp_path, f"{base}..{shas[-1]}",
                 admission=("check_prose", "adversary"))

    assert out["witness"]["unwitnessed_by_family"] == {}
    assert out["witness"]["witnessed_by_family"] == {"mechanical": 1, "review": 1}
    assert "EXAMINED THIS PUSH" not in canpush_mod.render(out)


def test_an_unresolvable_base_claims_nothing_rather_than_full_coverage(ledger, tmp_path,
                                                                       config_dir):
    """⛔ ABSENCE IS NEVER SUCCESS. If the base cannot be read, the honest answer is that
    nothing is known about which families looked — NOT an empty `unwitnessed` list, which
    renders identically to a push every family covered."""
    from core import canpush as cp
    base, shas = _repo(tmp_path, n=1)
    out = cp._witness(config=ledger.config, repo=str(tmp_path),
                      base="0" * 40, tip_files={}, admitted=["adversary"])
    assert out["resolved"] is False
    assert "no claim is made" in out["why"]
    assert "unwitnessed_by_family" not in out, (
        "a zero-length unwitnessed list on an unreadable base is the false-negative this "
        "whole disclosure exists to prevent")
