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
    # ⚠ under the LEGACY basis the two halves really are the same object, so the pair is honest
    assert "registry_file_sha" in text
    assert ledger.config.registry_sha[:12] in text, "the 'now' half must be the live file sha"


def test_the_broken_freeze_compares_two_values_of_the_same_kind(ledger, tmp_path):
    """⛔⛔ THE RENDER PRINTED A SCOPE DIGEST BESIDE A FILE HASH AND CALLED IT A BEFORE/AFTER.

    MEASURED ON THE LIVE FLEET 2026-09-21, `origin/illustrated..illustrated`, the basis the
    consumer actually runs on since the 09-18 re-freeze:

        frozen at 211569c3d832  ·  registry now d59065e57f7f

    ⚠⚠ `frozen_at` under `basis: scope_digest` is a SCOPE DIGEST. `registry_sha` is a FILE HASH.
    They are not the same kind of value, so the pair **cannot discriminate** "the bar moved" from
    "these two hashes were never comparable" — it would print two different strings on a freeze
    that had not moved at all. That is this repo's founding defect class (a true value read
    against the wrong object) sitting in the render of the very field added to remove it.

    ⛔ AND THE IMPLIED REMEDY WAS WORSE THAN THE DIAGNOSIS. The next line tells the reader to
    re-freeze, and the only "now" value on offer was the file sha — writing that into
    `frozen_scope_digest` never compares equal to a scope digest, so the freeze would read BROKEN
    forever and the repair would be indistinguishable from the fault.

    ⭐ WHY IT SURVIVED REVIEW, and it is the reusable half: the test above pins this same render
    and passes, because it freezes with the LEGACY `frozen_registry_sha`, where frozen-vs-
    `registry_sha` is a correct pair. The guard existed, was green, and did not cover the basis
    the fleet had migrated to. A control is only as scoped as its fixture made it.

    ⚠ `basis` was on the payload the whole time — `convergence_bar` names the object it compared
    precisely so no reader downstream has to infer it. This render inferred it anyway.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    ledger.config.policy = dict(ledger.config.policy or {})
    # the SCOPE-DIGEST basis, which is what the live fleet runs on — never the legacy field
    ledger.config.policy["convergence"] = {"frozen_scope_digest": "0" * 64}

    result = _check(ledger, tmp_path, f"{old}..{tip}",
                    [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)])
    fz = result["registry_freeze"]
    text = canpush_mod.render(result)

    assert fz["basis"] == "scope_digest", "fixture: this test exists to cover the NEW basis"
    assert fz["held"] is False, "the fixture must present a MOVED freeze"
    assert "REGISTRY FREEZE IS BROKEN" in text

    digest, file_sha = ledger.config.registry_scope_digest, ledger.config.registry_sha
    assert digest != file_sha, (
        "fixture: the two identities must differ, or this test cannot tell them apart")

    # ⛔ THE WHOLE POINT: the 'now' half is the SAME KIND as the frozen half.
    assert digest[:12] in text, "the 'now' half is not the scope digest the freeze was keyed on"
    assert file_sha[:12] not in text, (
        "the render still offers the registry FILE sha as the counterpart to a scope digest")
    # ⚠ and the remedy must name the field that value actually belongs in
    assert "frozen_scope_digest" in text, "a refusal must name the success condition"
    assert "frozen_registry_sha" not in text, "the remedy names the wrong field for this basis"


def test_stale_and_owed_are_not_presented_as_the_same_work(ledger, tmp_path):
    """⛔⛔ A STALE ROW AND A RATCHET OBLIGATION CAN BE DIFFERENT WORK, AND THE RENDER SAID SO
    NOWHERE. Raised by the ZeroParadox session mid-drill, 2026-09-18, seeing one step named twice
    from two causes: *"a reader who clears only the STALE row has not cleared the ratchet... They
    happen to be, this time. Are there cases where they are not?"*

    ⭐ MEASURED OVER 11 LIVE ARCS THE SAME HOUR: the sets differ in TEN. Two arcs had a STALE step
    with the ratchet owing NOTHING, so clearing the ratchet would have cleared nothing at all.

    Here the ratchet owes a step that is NOT stale — the file is new, so there is no earlier
    verdict to have gone stale — and the render must not let that read as one job.
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
    text = canpush_mod.render(result)

    tip_row = [c for c in result["commits"] if c["is_tip"]][0]
    assert tip_row["stale"] == [], "fixture: nothing is stale, so the two sets must differ"
    assert result["ratchet"]["owed"], "fixture: the ratchet must owe something"
    assert "DIFFERENT WORK HERE" in text
    assert "OWED, not stale" in text and STEP in text


def test_session_state_is_never_owed_because_nobody_may_record_it(ledger, tmp_path):
    """⛔⛔ `RATCHET-2` — IT BLOCKED A REAL PUSH FOR SIX COMMITS, reported by ZeroParadox
    2026-09-18, one day after the ratchet shipped.

    The subject fence refuses session-state paths as verdict subjects UNCONDITIONALLY, so the
    ratchet owing a signature on one produces a refusal whose printed remedy — *"run each step
    over the paths named and record"* — no caller is permitted to execute. **A refusal whose
    success condition cannot be met is worse than a bare refusal**: it sends the caller to do
    work the system will then reject.

    ⚠ The fence's own file says it is "the place the other three collapse ONTO, not a fifth
    copy", so this reads their declaration rather than listing the path here.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    (ledger.config.required_path.parent / "session_state.txt").write_text(
        "# session state, never a subject\nstate.json\n", encoding="utf-8", newline="\n")
    # ⚠ The list lands BEFORE the measured range: the ledger's config dir sits inside the fixture
    # repo, so writing it mid-range would make the list itself an unjudged changed path.
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "declare the session-state list"], cwd=tmp_path,
                   check=True, capture_output=True)
    tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                         text=True).stdout.strip()
    (tmp_path / "state.json").write_text('{"round": 3}', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "bump the session counter"], cwd=tmp_path,
                   check=True, capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip),
               _rec(STEP, PATH, _blob(tmp_path, newtip, PATH), newtip)]

    result = _check(ledger, tmp_path, f"{tip}..{newtip}", records)

    owed = [(o["step"], o["path"]) for o in result["ratchet"]["owed"]]
    assert owed == [], f"the ratchet owed a signature nobody may record: {owed}"


def test_an_ordinary_file_is_still_owed_when_a_session_state_list_exists(ledger, tmp_path):
    """⛔ THE CONTROL. An exemption list that quietly widens is a self-exemption route — the
    fence's own header records `vendored.is_vendored` matching `/Vendored/` at any depth and
    exempting a whole directory from four checkers. EXACT MATCH, and nothing else moves."""
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    (ledger.config.required_path.parent / "session_state.txt").write_text(
        "state.json\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "declare the session-state list"], cwd=tmp_path,
                   check=True, capture_output=True)
    tip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                         text=True).stdout.strip()
    (tmp_path / "state.json").write_text('{"round": 3}', encoding="utf-8")
    (tmp_path / "real.md").write_text("content nobody has judged", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "session state AND real content"], cwd=tmp_path,
                   check=True, capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True,
                            text=True).stdout.strip()
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip),
               _rec(STEP, PATH, _blob(tmp_path, newtip, PATH), newtip)]

    result = _check(ledger, tmp_path, f"{tip}..{newtip}", records)

    owed = [(o["step"], o["path"]) for o in result["ratchet"]["owed"]]
    assert owed == [(STEP, "real.md")], f"the exemption leaked past its exact match: {owed}"


def test_session_state_is_not_in_any_STEPS_SCOPE_either(ledger, tmp_path):
    """⛔⛔ `RATCHET-2`, SECOND OCCURRENCE — and this one HARD BLOCKED a push with a remedy no
    caller could execute. Reported by ZeroParadox 2026-09-18, hours after the first was fixed.

    The first fix landed in the ratchet. Per-commit COVERAGE computes scope independently, so it
    kept the old behaviour: `check_encoding` claimed `gate_round.json` (482 paths), the subject
    fence refused it as a subject, coverage could never exceed 481/482, the commit could never be
    complete, and `progress` printed *"run the step over the listed paths and record"* for a path
    `record.py` declines in the same breath.

    ⚠⚠ WORSE THAN THE FIRST, because the escape was gone: the blocking commits were ALREADY
    WRITTEN and their trees held the modified blob. Nothing at HEAD changes what an earlier commit
    contains.

    ⭐ SO THE EXCLUSION MOVED TO THE ONE PLACE SCOPE IS COMPUTED, which was their ask: *"the fix
    should go wherever scope is computed rather than at each consumer, so the next reader inherits
    it."* Their `session_state.txt` header had predicted exactly this — four declarations, asking
    to be the one they collapse onto; the ratchet made five and coverage six.
    """
    from core import inventory as inventory_mod
    (ledger.config.required_path.parent / "session_state.txt").write_text(
        "state.json\n", encoding="utf-8", newline="\n")

    inv = inventory_mod.build(
        config=ledger.config, records=[], action="commit",
        files={"doc.md": "a" * 40, "state.json": "b" * 40},
        ref="c" * 40, admission=[STEP], changed=None)
    row = [r for r in inv["rows"] if r["step"] == STEP][0]

    assert row["scope"] == 1, (
        f"session state is still inside the step's scope ({row['scope']} paths) — coverage can "
        f"then never complete, because nobody is permitted to record it")


def test_an_unset_intermediate_does_not_render_as_zero_of_zero_short(ledger, tmp_path):
    """⛔⛔ `0/0 short` READS AS SATISFIED-AND-YET-BLOCKING, and it cost the consumer a wrong
    diagnosis on 2026-09-18. Calling `can_push` with only the PUSH set leaves every INTERMEDIATE
    — judged under `commit` — with no admission at all, and the row rendered `0/0 short`.

    ⚠⚠ THIS IS THE 2026-09-03 HEADLINE DEFECT ONE LINE DOWN. Their words then: *"the surface
    reads as a refusal and means unconfigured, and those are different facts."* The headline was
    fixed; the per-commit rows kept the shape — the same fix applied at one level and not its
    sibling.
    """
    base, shas = _repo(tmp_path, n=2)
    old, tip = shas[0], shas[1]
    result = canpush_mod.check(records=[], config=ledger.config, repo=str(tmp_path),
                               rev_range=f"{old}..{tip}", admission=[STEP],
                               commit_admission=None)          # <- the caller's mistake
    text = canpush_mod.render(result)

    inter = [c for c in result["commits"] if not c.get("is_tip")]
    if inter:
        assert inter[0]["admission_state"] in ("UNSET", "EMPTY")
        assert "admission UNSET" in text or "admission EMPTY" in text, text
        assert "NOT a coverage failure" in text
        assert "commit_admission" in text, "the remedy must name the parameter that fixes it"


def test_EVERY_scope_deciding_function_honours_the_session_state_fence():
    """⛔⛔ THE SIBLING-SET CONTROL. Scope is decided in several functions across two modules, and
    the session-state exclusion reached two of them before this test existed.

    Measured 2026-09-20, an hour after `build` was fixed: `build` reported `check_encoding`
    SATISFIED at scope 481, while `coverage_gap` — **the tool a caller reads to learn WHAT TO
    RECORD** — still answered `missing: 1 of 482, paths: ["gate_round.json"], remedy: "run the
    step over the listed paths and record"`. The two surfaces disagreed, and the one giving
    instructions named a path nobody is permitted to record.

    ⭐ ZeroParadox's rule, applied to my own fix: after a correction, ask what SIBLING SET the
    fixed member belongs to and whether the fix reached all of it. **A grep for `session_state`
    finds the sites that HAVE it — the exact inverse of the question.** Only enumeration reaches
    the sibling, because the unfixed member is by definition where the marker does not appear.

    ⚠ STRUCTURAL, NOT BEHAVIOURAL, and deliberately: a behavioural test covers the paths a
    fixture happens to take, which is how two fixed sites sat behind a green suite while two
    others were wrong.
    """
    import pathlib
    import re
    core = pathlib.Path(__file__).resolve().parents[1] / "core"
    # every function that decides scope membership by glob
    # ⛔ ONE NAMED EXEMPTION, WITH ITS REASON, NEVER A SILENT SKIP. `subjects_outside_scope` asks
    # the INVERSE question — which recorded subjects fall OUTSIDE a step's declared scope, i.e.
    # over-claim. Excluding session state there would HIDE a real defect: a step that records
    # `gate_round.json` as a subject has over-claimed, and that is exactly what it exists to
    # report.
    EXEMPT = {"subjects_outside_scope"}
    offenders = []
    for fn in ("inventory.py", "canpush.py"):
        src = (core / fn).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(src):
            # ⚠⚠ MATCH THE READ, NOT THE WORD. The first draft matched any line containing
            # `scope_exclude` and flagged a MESSAGE STRING that merely mentions it — the
            # detector counting prose about the marker as the marker, which is `DC-51`, the
            # class I had caught that same morning in a different repo. Match the actual
            # dictionary read instead.
            if '.get("scope_exclude")' not in line:
                continue
            # ⚠ ATTRIBUTE TO THE TOP-LEVEL def. The first draft took the nearest def at ANY
            # indent and blamed a NESTED helper 550 lines above for code that lives in `build`
            # — a true line number under a false owner, which is this fleet's own defect class
            # turning up inside the detector written to catch it.
            start = next((j for j in range(i, -1, -1) if re.match(r"^def \w+", src[j])), 0)
            name = re.match(r"^def (\w+)", src[start]).group(1)
            end = next((k for k in range(start + 1, len(src))
                        if re.match(r"^def \w+", src[k])), len(src))
            # ⛔⛔ STRIP COMMENTS BEFORE LOOKING FOR THE FENCE, AND THIS IS THE FOURTH `DC-51`
            # IN ONE SITTING. The first version matched the bare word `session_state` anywhere in
            # the body — and a mutation that DELETED the fence outright still passed, because the
            # explanatory comment above it says `session_state`. **The detector counted prose
            # about the marker as the marker**, which is the exact class I had filed that
            # morning, inside the control written to enforce the lesson from it.
            code = "\n".join(l.split("#", 1)[0] for l in src[start:end])
            # ⚠ The exemption is keyed on the CONSTRUCT, not the enclosing function: the
            # inverse-question code is an inline block inside `build`, not its own def, so a
            # name-keyed exemption would either miss it or exempt all of `build`.
            window = "\n".join(src[max(0, i - 12):i + 4])
            if any(e in window for e in EXEMPT):
                continue
            if "session_state" not in code:
                offenders.append(f"{fn}:{name} (line {i + 1})")
    assert not offenders, (
        "these functions decide scope by glob and do NOT honour the session-state fence, so they "
        "can name a path no caller may record:\n  " + "\n  ".join(sorted(set(offenders))))


def test_coverage_gap_never_names_a_path_nobody_may_record(ledger, tmp_path):
    """⛔⛔ THE BEHAVIOURAL HALF, AND THE STRUCTURAL TEST CANNOT REPLACE IT.

    The sibling control above asks whether each scope-deciding site REFERENCES the fence. That
    catches a new site added without it — and it passed when the fence was neutered to `set()`,
    because the word stayed in the body. **A structural check counts a marker; only running the
    code shows the marker is load-bearing.** Third time in one sitting that a detector counted
    the marker instead of the property, so both halves are now pinned.

    ⚠ `coverage_gap` is the surface a caller reads to learn WHAT TO RECORD. On 2026-09-20 it
    answered `missing: 1 of 482, paths: ["gate_round.json"], remedy: "run the step over the
    listed paths and record"` while `build` had already been fixed and read SATISFIED at 481 —
    two surfaces disagreeing, with the instruction-giving one naming an unrecordable path.
    """
    from core import inventory as inventory_mod
    (ledger.config.required_path.parent / "session_state.txt").write_text(
        "state.json\n", encoding="utf-8", newline="\n")

    gap = inventory_mod.coverage_gap(
        config=ledger.config, records=[], action="commit",
        files={"doc.md": "a" * 40, "state.json": "b" * 40},
        admission=[STEP], step=STEP)

    named = []
    for s in gap.get("steps") or []:
        named += s.get("paths") or []
    assert "state.json" not in named, (
        f"coverage_gap told a caller to record session state: {named}. The subject fence "
        f"refuses it, so the remedy it prints cannot be executed by anyone.")
    assert "doc.md" in named, (
        "the fence must not swallow ordinary uncovered paths — that would hide real gaps")
