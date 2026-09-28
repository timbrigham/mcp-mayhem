"""A finding may not be carried ACROSS a change to the file it is about.

⭐⭐ Tim's ruling 2026-09-27, and the measurement that prompted it: **953 `outstanding` entries in
the stream, 948 of them `ordinary`, 893 sitting on PASSING records, and nothing anywhere gating,
thresholding or ageing them.** Top contributors editorial 316, adversary 296, prior_art 197.

So an ordinary finding was preserved, attributable, and permanently inert. Better than silenced — a
reader can find it — but never ACTED on, and after 948 of them the field is where findings go to be
counted rather than resolved. That is the honest half of the answer to *"what do you do with the
failure"*: V18 stops a serious dissent being outvoted, and nothing at all happened to the ordinary
ones.

⭐ THE RULE IS NARROW AND THE NARROWNESS IS THE ARGUMENT. It asks nobody to clear the 893: a path
nobody touched keeps its findings, exactly as the changed-path ratchet grandfathers unexamined
bytes. It binds ONE case — **you edited the file the finding is about, and the finding is still
there.** At that moment it was in front of whoever made the edit, so carrying it forward is a
decision rather than a backlog.

⛔ IDENTITY IS `(severity, note)` AND A REWORDED FINDING ESCAPES. Stated rather than implied to be
airtight: nothing here separates a genuinely different finding from the same one rephrased, so this
catches carry-forward and not evasion. Same honest footing V18 takes on severity — *"Nothing here
can detect a DEFLATED finding"* — with the same remedy: the claim is attributable, because the
record names who recorded it under which brief.

⚠ ORDINARY ONLY, because V18 already makes anything worse unrepresentable on a PASS. A carried
bedrock finding needs nothing from this rule; it could never have been recorded.
"""

import subprocess

import pytest

from core import canpush as canpush_mod
from test_can_push import _rec, _repo

STEP = "check_encoding"
NOTE = "trailing whitespace on line 3"


def _repo_where_a_file_changes(tmp_path):
    """Two commits, both touching `doc.md`, so its blob genuinely moves across the range."""
    base, shas = _repo(tmp_path, n=2)
    return base, shas[0], shas[-1]


def _blob(tmp_path, ref, path):
    return subprocess.run(["git", "rev-parse", f"{ref}:{path}"], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()


def _with_findings(step, path, blob, basis, notes, severity="ordinary"):
    r = _rec(step, path, blob, basis)
    r["outstanding"] = [{"severity": severity, "note": n, "path": path} for n in notes]
    return r


def _check(ledger, tmp_path, rng, records, admission=(STEP,)):
    return canpush_mod.check(records=list(records), config=ledger.config, repo=str(tmp_path),
                             rev_range=rng, admission=list(admission),
                             commit_admission=list(admission))


def _scope(ledger, step, scope):
    types = ledger.config.required["types"]
    types[step] = dict(types.get(step) or {})
    types[step]["scope"] = list(scope)
    types[step]["scope_exclude"] = []


# -- ⭐⭐ the rule ---------------------------------------------------------------

def test_the_same_finding_on_both_sides_of_a_change_blocks(ledger, tmp_path):
    """⭐⭐ THE HEADLINE. The file changed, the finding is recorded again against the new bytes, so
    it was in front of whoever made the edit."""
    base, mid, tip = _repo_where_a_file_changes(tmp_path)
    _scope(ledger, STEP, ["*.md"])
    # ⚠ A SINGLE-COMMIT RANGE, so the TIP is the only row and nothing else can block. A wider
    # range put an intermediate commit in the walk whose own row was incomplete, which made
    # `allowed is False` true for a reason that had nothing to do with this rule.
    old, new = _blob(tmp_path, mid, "doc.md"), _blob(tmp_path, tip, "doc.md")
    assert old != new, "the fixture did not actually change the file"
    result = _check(ledger, tmp_path, mid + ".." + tip, [
        _with_findings(STEP, "doc.md", old, mid, [NOTE]),
        _with_findings(STEP, "doc.md", new, tip, [NOTE]),
    ])
    carried = (result.get("ratchet") or {}).get("carried_findings") or []
    assert carried, f"a finding carried across a change did not block: ratchet={result.get('ratchet')}"
    e = carried[0]
    assert e["path"] == "doc.md" and e["note"] == NOTE and e["severity"] == "ordinary"
    assert e["old_blob"] == old and e["new_blob"] == new
    # ⛔⛔ THE CARRIED FINDING MUST BE THE SOLE CAUSE, or this asserts nothing about the new term.
    # ⚠ The first version just checked `allowed is False` and a mutant REMOVING `and not carried`
    # from the decision SURVIVED — because the range was already refused for another reason. An
    # assertion about a blocked range is not an assertion about what blocked it.
    assert result["blocking_count"] == 0, (
        f"a commit blocks for another reason, so `allowed` proves nothing here: "
        f"{[c['commit'][:9] for c in result['commits'] if not c['complete']]}")
    assert ((result.get("ratchet") or {}).get("owed") or []) == [], (
        "the ratchet also owes a verdict here, so `allowed` is overdetermined")
    assert result["allowed"] is False, (
        "nothing else blocks and the carried finding did not refuse the push — the decision does "
        "not consult `carried_findings`")
    # ⛔ and the remedy must not say "re-run the step" — it already ran twice and said the same
    assert "Fix it" in e["why"] and "re-run" not in e["why"].lower()


def test_a_new_finding_on_a_changed_file_does_not_block(ledger, tmp_path):
    """⛔⛔ THE CONTROL THAT KEEPS THIS FROM BEING "NO FINDINGS ON CHANGED FILES". A finding that
    appears for the FIRST time was not carried across anything — the edit did not have it in view.
    Without this the rule would forbid reporting anything new about a file you touched, which is
    the opposite of what a review gate is for."""
    base, mid, tip = _repo_where_a_file_changes(tmp_path)
    _scope(ledger, STEP, ["*.md"])
    old, new = _blob(tmp_path, base, "doc.md"), _blob(tmp_path, tip, "doc.md")
    result = _check(ledger, tmp_path, base + ".." + tip, [
        _with_findings(STEP, "doc.md", old, base, ["an older, different finding"]),
        _with_findings(STEP, "doc.md", new, tip, ["something noticed for the first time"]),
    ])
    assert ((result.get("ratchet") or {}).get("carried_findings") or []) == [], (
        "a finding that had never been recorded before was treated as carried")


def test_an_untouched_path_keeps_its_findings(ledger, tmp_path):
    """⭐⭐ THE GRANDFATHERING, WHICH IS WHY THIS DOES NOT BLOCK EVERY PUSH TOMORROW. 893 ordinary
    findings sit on passing records today. The rule binds a CHANGED path only, so none of them is
    anybody's debt until the file is edited."""
    base, mid, tip = _repo_where_a_file_changes(tmp_path)
    # ⛔⛔ THE PATH MUST EXIST AT THE RANGE'S BASE WITH THE SAME BLOB. My first version ADDED the
    # file mid-range, so `base_files.get(path)` was None and the `if not old_blob` guard skipped it
    # — which tests "absent at base", a DIFFERENT property. A mutant deleting the
    # `old_blob == tip_files[path]` skip SURVIVED, because nothing exercised an UNCHANGED path,
    # which is the exact case the grandfathering of the 893 depends on.
    (tmp_path / "other.md").write_text("untouched\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed other"], cwd=tmp_path, check=True,
                   capture_output=True)
    seeded = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                            capture_output=True, text=True).stdout.strip()
    # now change doc.md ONLY, so other.md carries the same blob at both ends of the range
    (tmp_path / "doc.md").write_text("changed again\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "touch doc only"], cwd=tmp_path, check=True,
                   capture_output=True)
    newtip = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                            capture_output=True, text=True).stdout.strip()
    _scope(ledger, STEP, ["*"])
    ob_base, ob_tip = _blob(tmp_path, seeded, "other.md"), _blob(tmp_path, newtip, "other.md")
    assert ob_base == ob_tip and ob_base, (
        "the fixture does not model an UNCHANGED path, so it cannot test grandfathering")
    result = _check(ledger, tmp_path, seeded + ".." + newtip, [
        _with_findings(STEP, "other.md", ob_tip, seeded, [NOTE]),
        _with_findings(STEP, "other.md", ob_tip, newtip, [NOTE]),
    ])
    carried = (result.get("ratchet") or {}).get("carried_findings") or []
    assert not any(e["path"] == "other.md" for e in carried), (
        "a finding on a path the range never changed was treated as carried — the 893 would all "
        "become debt on the next push")
    # ⚠⚠ AND THE MECHANISM IS `_changed_across`, NOT THE BLOB COMPARISON INSIDE THE LOOP. Recorded
    # because a mutation deleting that comparison SURVIVES this test: an unchanged path never
    # enters `changed` at all, so the guard is unreachable here. It is kept as defence against a
    # diff naming a path whose blob did not move (a mode-only change), and that fixture cannot be
    # built on this platform — git runs with `core.filemode` false, so such a change is invisible
    # to the diff. ⭐ A survivor that is understood and deliberately kept is not the same as one
    # nobody noticed; this is the note that makes the difference checkable by the next reader.
    #
    # ⛔ AND THERE IS DELIBERATELY NO ASSERTION ATTACHED TO THAT NOTE. The first draft added
    # `assert … or True`, which can never fail — a vacuous assertion is worse than none, because it
    # reads as coverage. If the unreachable guard ever becomes reachable, the fixture that reaches
    # it is what belongs here, not a sentence pretending to test it.


def test_a_cleared_finding_does_not_block(ledger, tmp_path):
    """⚠ THE SUCCESS PATH MUST EXIST AND BE REACHABLE. Fixing the finding — recording the new
    verdict without it — clears the block. A rule whose success condition cannot be produced is the
    unsatisfiable-refusal shape this fleet treats as the server's own defect."""
    base, mid, tip = _repo_where_a_file_changes(tmp_path)
    _scope(ledger, STEP, ["*.md"])
    old, new = _blob(tmp_path, base, "doc.md"), _blob(tmp_path, tip, "doc.md")
    result = _check(ledger, tmp_path, base + ".." + tip, [
        _with_findings(STEP, "doc.md", old, base, [NOTE]),
        _with_findings(STEP, "doc.md", new, tip, []),          # fixed
    ])
    assert ((result.get("ratchet") or {}).get("carried_findings") or []) == []


def test_it_is_reported_apart_from_owed(ledger, tmp_path):
    """⛔ THE TWO LISTS HAVE OPPOSITE REMEDIES AND MUST NOT MERGE. `owed` says RUN THE STEP over
    bytes nobody judged. This says the step ran TWICE and reported the same thing. A caller told to
    re-run would reproduce it — `RLY41-2`'s shape, a true blocking answer wearing a remedy for a
    different failure."""
    base, mid, tip = _repo_where_a_file_changes(tmp_path)
    _scope(ledger, STEP, ["*.md"])
    old, new = _blob(tmp_path, base, "doc.md"), _blob(tmp_path, tip, "doc.md")
    result = _check(ledger, tmp_path, base + ".." + tip, [
        _with_findings(STEP, "doc.md", old, base, [NOTE]),
        _with_findings(STEP, "doc.md", new, tip, [NOTE]),
    ])
    rt = result.get("ratchet") or {}
    assert rt.get("carried_findings"), "nothing carried"
    assert not any(o.get("path") == "doc.md" and o.get("step") == STEP
                   for o in (rt.get("owed") or [])), (
        "the carried finding also appears as OWED, so the caller is told to run a step that "
        "already ran and will report the same finding again")


@pytest.mark.parametrize("severity", ["bedrock", "blocking"])
def test_only_ordinary_is_considered(ledger, tmp_path, severity):
    """⚠ V18 ALREADY MAKES ANYTHING WORSE UNREPRESENTABLE ON A PASS, so a carried bedrock finding
    could never have been recorded and needs nothing from this rule. Considering it here would
    duplicate V18 and invite the two to disagree."""
    base, mid, tip = _repo_where_a_file_changes(tmp_path)
    _scope(ledger, STEP, ["*.md"])
    old, new = _blob(tmp_path, base, "doc.md"), _blob(tmp_path, tip, "doc.md")
    result = _check(ledger, tmp_path, base + ".." + tip, [
        _with_findings(STEP, "doc.md", old, base, [NOTE], severity=severity),
        _with_findings(STEP, "doc.md", new, tip, [NOTE], severity=severity),
    ])
    assert ((result.get("ratchet") or {}).get("carried_findings") or []) == []
