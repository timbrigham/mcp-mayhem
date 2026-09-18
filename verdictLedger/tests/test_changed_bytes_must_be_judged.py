"""The changed-path ratchet: bytes a push CHANGES must have been judged AT THOSE BYTES.

⛔⛔ THE DEFECT IT CLOSES. Coverage is content-keyed, so a path a step examined BEFORE goes STALE
when it changes and blocks — while a path that step has NEVER examined passes in silence, however
much it changed. The ratchet engaged on known files and disengaged on new content.

MEASURED 2026-09-17/18 on the live stream:
  · over the 29-commit arc pushed 09-16, 328 (step, changed path) pairs had no verdict at the new
    bytes and the gate raised TWO — 326 invisible because the step had no prior verdict to stale.
  · over the previous 7 days, 121 of 563 published file-versions carried no review-family verdict
    at the bytes that shipped; 3 were still live at the tip, one of them a prose home of a recorded
    prior-art incident.
  · all three would have been blocked by this rule at the push that shipped them.

⚠ THE BACKLOG IS GRANDFATHERED BY CONSTRUCTION — 1,102 never-examined paths sit in scope untouched
and are nobody's debt until edited. Tim's model, 2026-09-17: accept today's baseline, ratchet all
new bytes.
"""

import subprocess

import pytest

from core import canpush as canpush_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_encoding"       # scope ["*"] in the sample registry: it STATES a surface
PATH = "doc.md"


def _check(ledger, tmp_path, rng, records, admission=(STEP,)):
    return canpush_mod.check(records=list(records), config=ledger.config, repo=str(tmp_path),
                             rev_range=rng, admission=list(admission),
                             commit_admission=list(admission))


def test_a_changed_path_with_no_verdict_at_the_new_bytes_blocks(ledger, tmp_path):
    """⭐⭐ THE HEADLINE, and the case the old gate let through: the step has NEVER examined this
    path, so nothing went stale and nothing blocked. Now it is owed."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, old, PATH), old)]   # judged at the OLD bytes only

    result = _check(ledger, tmp_path, f"{old}..{tip}", records)

    assert result["allowed"] is False
    owed = result["ratchet"]["owed"]
    assert [(o["step"], o["path"]) for o in owed] == [(STEP, PATH)]
    assert owed[0]["git_blob_id"] == _blob(tmp_path, tip, PATH)


def test_judging_it_at_the_new_bytes_clears_it(ledger, tmp_path):
    """The remedy is exactly what the refusal names: record the step over the named path."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, old, PATH), old),
               _rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]

    result = _check(ledger, tmp_path, f"{old}..{tip}", records)

    assert result["allowed"] is True
    assert result["ratchet"]["owed"] == []


def test_the_backlog_is_grandfathered(ledger, tmp_path):
    """⭐ THE PROPERTY THAT MAKES THIS SHIPPABLE. An untouched path with NO verdict at all is not
    owed — only what the range changes. This is the whole difference from require_complete, which
    would block every push until the corpus had been swept."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    (tmp_path / "untouched.md").write_text("never judged, never edited", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add an unjudged file"], cwd=tmp_path, check=True,
                   capture_output=True)
    settled = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                             text=True).stdout.strip()
    # judge everything the LAST range changes, so only the older untouched file is unjudged
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip),
               _rec(STEP, "untouched.md", _blob(tmp_path, settled, "untouched.md"), settled)]
    # now a range that changes NOTHING but doc.md
    (tmp_path / PATH).write_text("moved again", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "touch doc only"], cwd=tmp_path, check=True,
                   capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()

    result = _check(ledger, tmp_path, f"{settled}..{newtip}", records)

    owed = [(o["step"], o["path"]) for o in result["ratchet"]["owed"]]
    assert owed == [(STEP, PATH)], f"only the changed path is owed, got {owed}"


def test_a_step_with_no_declared_scope_raises_nothing(ledger, tmp_path):
    """⛔ ABSENCE IS NOT A CLAIM. A step declaring neither `scope` nor `when` has stated no
    obligation surface, and reading its silence as 'every file' is what took the live measurement
    from 2 obligations to 328 — dragging in every PDF and asking a reviewer about a rendering."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    spec = dict((ledger.config.required.get("types") or {}).get(STEP) or {})
    spec.pop("scope", None)
    spec.pop("when", None)
    types = dict(ledger.config.required.get("types") or {})
    types[STEP] = spec
    ledger.config.required["types"] = types

    result = _check(ledger, tmp_path, f"{old}..{tip}", [])

    assert result["ratchet"]["owed"] == []
    assert STEP not in result["ratchet"]["steps_consulted"]


def test_a_pure_rename_re_owes_nothing(ledger, tmp_path):
    """⚠ A verdict binds (step, path, blob). A rename moves no bytes, so what was judged still
    holds; what breaks is POINTERS to the old path, which is `check_moved`'s job."""
    base, shas = _repo(tmp_path, n=2)
    tip = shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]
    subprocess.run(["git", "mv", PATH, "renamed.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "pure rename"], cwd=tmp_path, check=True,
                   capture_output=True)
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                           text=True).stdout.strip()

    result = _check(ledger, tmp_path, f"{tip}..{after}", records)

    assert result["ratchet"]["owed"] == [], "a pure rename re-owed a verdict"
    assert "renamed.md" in result["ratchet"]["renames_exempt"]


def test_the_refusal_names_every_signature_it_wants(ledger, tmp_path):
    """⭐ A gate that refuses without saying what would clear it forces the caller to re-derive an
    obligation it cannot see: the rule lives in the server and the changed set lives in git."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, old, PATH), old)]

    text = canpush_mod.render(_check(ledger, tmp_path, f"{old}..{tip}", records))

    assert "CHANGED BYTES NOT JUDGED" in text
    assert PATH in text and STEP in text
    assert "signature(s) owed" in text


def test_the_headline_does_not_blame_the_commit_count_for_the_ratchets_refusal(ledger, tmp_path):
    """⛔⛔ THE HEADLINE MUST NAME WHAT IS REFUSING. A ratchet-only refusal has every commit
    complete, so the count renders `0/N commit(s) short` — a TRUE number standing where the
    reason belongs.

    ⚠ THIS EXACT LINE HAS NOW DONE IT TWICE. ZeroParadox reported it 2026-09-03 reading
    `REFUSED push 13/13 commit(s) short` when the admission set was merely unset: *"the surface
    reads as a refusal and means unconfigured, and those are different facts."* The ratchet
    reproduced it from the other direction — zero short, and still refused.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]
    (tmp_path / "brand_new.md").write_text("never seen by any step", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "a file nobody has judged"], cwd=tmp_path,
                   check=True, capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()
    records.append(_rec(STEP, PATH, _blob(tmp_path, newtip, PATH), newtip))

    result = _check(ledger, tmp_path, f"{tip}..{newtip}", records)
    headline = canpush_mod.render(result).splitlines()[0]

    assert headline.startswith("REFUSED")
    assert result["blocking_count"] == 0, "fixture: nothing but the ratchet refuses this"
    assert "signature(s) owed" in headline, (
        f"the headline blames the commit count for a refusal it had no part in: {headline!r}")


def test_the_ratchet_ALONE_refuses_a_push_that_is_otherwise_green(ledger, tmp_path):
    """⛔⛔ THE CONTROL THE OTHERS DO NOT GIVE, and its absence was caught by mutation: making the
    ratchet non-blocking failed NOTHING, because every other case here was already refused by a
    STALE row. That is the live shape exactly — 326 of 328 obligations were invisible precisely
    because the step had no prior verdict, so no row went stale and the push read green.

    Here the step is SATISFIED (it judged doc.md at the tip) and a NEW file arrives in the range
    that it has never examined. Today: allowed. With the ratchet: refused, naming the new file.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]

    (tmp_path / "brand_new.md").write_text("never seen by any step", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add a file nobody has judged"], cwd=tmp_path,
                   check=True, capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()
    records.append(_rec(STEP, PATH, _blob(tmp_path, newtip, PATH), newtip))

    result = _check(ledger, tmp_path, f"{tip}..{newtip}", records)

    tip_row = [c for c in result["commits"] if c["is_tip"]][0]
    assert tip_row["complete"] is True, (
        "fixture assumption: every ROW is green, so only the ratchet can refuse this push")
    assert result["allowed"] is False, "the ratchet did not block a push nothing else refused"
    assert [(o["step"], o["path"]) for o in result["ratchet"]["owed"]] == [(STEP, "brand_new.md")]


def test_can_push_reports_a_broken_registry_freeze(ledger, tmp_path):
    """⛔⛔ THE PUSH PATH MUST SAY THE FREEZE MOVED, and until 2026-09-18 it was the one caller
    that could not.

    ⚠ THIS IS THE 2026-09-07 DEFECT AT ITS UNFIXED SIBLING. `convergence_bar`'s docstring records
    it: *"progress() reported complete: true, satisfied 19/19 beside bar.held: false — and
    gitRobot's status() surfaced the 19/19 and not the broken bar. A reader of the gate's own
    status saw green."* The repair lifted the bar onto `inventory` and stopped there. Measured on
    the live fleet the day this test was written: `inventory` answered `held: false` while
    `can_push` did not carry the field at all, and had not since the freeze broke on 09-16.

    ⛔ A NAME COLLISION IS WHY READING THE RESPONSE COULD NOT REVEAL IT: `can_push` publishes
    `push_bar` (tip_green/every_commit), a DIFFERENT object, so a key called "bar" was already
    present and a reader had no reason to look for a second one.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    ledger.config.policy = dict(ledger.config.policy or {})
    ledger.config.policy["convergence"] = {"frozen_registry_sha": "0" * 64}   # never the live sha

    result = _check(ledger, tmp_path, f"{old}..{tip}",
                    [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)])
    text = canpush_mod.render(result)

    assert result["registry_freeze"]["frozen"] is True
    assert result["registry_freeze"]["held"] is False, "the fixture must present a MOVED freeze"
    assert "REGISTRY FREEZE IS BROKEN" in text, "the push path stayed silent about a moved freeze"
    # ⚠ and it must not let the reader confuse the two objects that both answer to "bar"
    assert "NOT the `push_bar`" in text
