"""A verdict recorded against DIFFERENT BYTES does not describe these bytes.

⚠⚠ THIS FILE EXISTS BECAUSE OF A MEASURED FAILURE (2026-08-23). One probe `build`
FAIL — recorded against a throwaway tree, on a README sha of literal "bbbb…" —
reported ALL EIGHT audited commits as NOT_APPROVED, "landed over a non-passing
verdict". None of those commits had ever been examined by anything.

Two defects, one root, and they compounded:

  * `inventory` checked the FAIL verdict BEFORE the staleness check, so a PASS
    against moved content was correctly demoted to STALE while a FAIL was not.
    A single stale FAIL condemned every commit forever, clearable only by a PASS
    on the exact sha.
  * `crossref` counted STALE as "examined", so a commit nothing had ever looked at
    reported `examined_by=3` and escaped the NOT_RUN finding — the single finding
    the audit exists to produce.

The compound effect is worse than either: the audit cried wolf on every commit
(training a reader to ignore it) while simultaneously being unable to report the
one thing it is for. Both directions of wrong, at once.
"""

import pytest

from core import crossref as crossref_mod
from core import inventory as inventory_mod


# ⚠ These use `check_prose`, not `build`. `build` is narrowed to actions:["tag"]
# in the registry (stub-first commits sorry-stubbed files on purpose), so at `push`
# every build row resolves NOT_APPLICABLE -- a test written against it would be
# exercising the narrowing while claiming to exercise staleness.
def _rec(step, sha, verdict, rid=None):
    return {"id": rid or f"{step}@{sha}#0", "step": step, "verdict": verdict,
            "revision": 0, "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "README.md", "git_blob_id": sha}],
            "basis": {"kind": "tree", "value": sha}}


def _build(ledger, records, files, admission=None):
    return inventory_mod.build(config=ledger.config, records=records, action="push",
                               files=files, ref="deadbeef", admission=admission)


# -- ⭐ a FAIL against other bytes is STALE, not FAIL --------------------------

def test_a_fail_against_different_bytes_demotes_to_stale(ledger):
    """⭐ THE HEADLINE REGRESSION. `check_prose` failed on sha 'old'; we are asking about
    sha 'new'. The honest status is "never run on this", not "this failed"."""
    inv = _build(ledger, [_rec("check_prose", "old", "FAIL")], {"README.md": "new"})
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["status"] == "STALE"
    assert row["status"] != "FAIL"


def test_the_demoted_row_still_names_the_failure_it_saw(ledger):
    """⚠ Demoting must not DISCARD the signal. "there was a recent FAIL, against
    other content" is worth knowing; it is just not a verdict on these bytes."""
    inv = _build(ledger, [_rec("check_prose", "old", "FAIL")], {"README.md": "new"})
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert "against different bytes" in row["why"]
    assert "check_prose@old#0" in row["why"]


def test_a_fail_against_these_bytes_is_still_a_fail(ledger):
    """⚠ THE CONTROL THAT KEEPS THE FIX FROM BEING A HOLE. The demotion applies only
    when the record examined something else."""
    inv = _build(ledger, [_rec("check_prose", "same", "FAIL")], {"README.md": "same"})
    row = next(r for r in inv["rows"] if r["step"] == "check_prose")
    assert row["status"] == "FAIL"


def test_an_undecided_against_other_bytes_also_demotes(ledger):
    inv = _build(ledger, [_rec("check_prose", "old", "UNDECIDED")], {"README.md": "new"})
    assert next(r for r in inv["rows"] if r["step"] == "check_prose")["status"] == "STALE"


def test_demoting_weakens_no_gate(ledger):
    """⭐ THE LOAD-BEARING PROPERTY. `complete` requires stale == 0 as well as
    failed == 0, so the action is refused either way. This fix changes only what the
    reader is TOLD — never whether the push is allowed."""
    inv = _build(ledger, [_rec("check_prose", "old", "FAIL")],
                 {"README.md": "new"}, admission=["check_prose"])
    assert inv["complete"] is False


def test_a_covering_record_wins_over_a_stale_one(ledger):
    """⚠ A SECOND, SUBTLER DEFECT: one `record` served both covered and stale hits,
    so whichever path was iterated first supplied the verdict. A stale FAIL could
    speak for a step that had also been properly examined."""
    files = {"README.md": "new", "GUIDE.md": "new2"}
    records = [
        {"id": "check_prose@old#0", "step": "check_prose", "verdict": "FAIL", "revision": 0,
         "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
         "subjects": [{"path": "README.md", "git_blob_id": "old"}],
         "basis": {"kind": "tree", "value": "old"}},
        {"id": "check_prose@new2#0", "step": "check_prose", "verdict": "PASS", "revision": 0,
         "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
         "subjects": [{"path": "GUIDE.md", "git_blob_id": "new2"}],
         "basis": {"kind": "tree", "value": "new2"}},
    ]
    row = next(r for r in _build(ledger, records, files)["rows"] if r["step"] == "check_prose")
    assert row["status"] == "STALE"          # partly examined, not FAILED
    assert row["record_id"] == "check_prose@new2#0"   # the COVERING record speaks


# -- ⭐ STALE is not "examined" ------------------------------------------------

def test_stale_does_not_count_as_examined(ledger):
    """⭐ The bypass detector must not report coverage it does not have. A commit
    whose every row is STALE was examined by NOTHING, and NOT_RUN is the finding."""
    inv = _build(ledger, [_rec("check_prose", "old", "PASS")], {"README.md": "new"})
    examined = [r for r in inv["rows"]
                if r["status"] in ("SATISFIED", "FAIL", "UNDECIDED")]
    assert examined == []


def test_the_crossref_examined_filter_excludes_stale():
    """Pins the filter itself: the constant lives in crossref and a well-meaning
    edit re-adding STALE would silently restore the defect."""
    import inspect
    src = inspect.getsource(crossref_mod.check)
    assert '("SATISFIED", "FAIL", "UNDECIDED")' in src
    assert '("SATISFIED", "STALE", "FAIL", "UNDECIDED")' not in src


# -- ⭐⭐ LED-2: STALE and UNSCOPED are different facts -------------------------
#
# Measured by ZeroParadox 2026-08-24. `editorial`/`adversary` exclude `.claude/*.md`,
# so the twelve gate briefs sit outside both prose gates. A review recorded over those
# briefs -- blob IDs 4/4 IDENTICAL to the index -- came back STALE, "recorded against
# different bytes", remedy "re-run".
#
# The bytes had not moved. The subjects were out of scope. And re-running is the ONE
# action that can never clear it, because a checker honouring its scope will never
# examine those paths again. A remedy that cannot work costs rounds and teaches the
# operator that the gate is broken rather than that the scope is.
#
# ⚠ `check_hashes` is used throughout below because it is the shipped registry's only
# type that declares a scope, an exclusion AND a switch outside that scope -- so one
# fixture exercises the denominator from all three sides. A synthetic type would not
# have caught the switch case.

SWITCH = "tools/verify/shared_build_baseline.txt"
EXCLUDED = "scripts/build_manifest.py"          # in `scope_exclude`, by name
MODULE = "tools/verify/check_hashes.py"


def _hashes(subjects, evidence=(), verdict="PASS"):
    return {"id": "check_hashes@t#0", "step": "check_hashes", "verdict": verdict,
            "revision": 0, "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": p, "git_blob_id": b} for p, b in subjects],
            "evidence": [{"path": p, "git_blob_id": b} for p, b in evidence],
            "basis": {"kind": "tree", "value": "t"}}


def _row(ledger, records, files):
    inv = inventory_mod.build(config=ledger.config, records=records, action="push",
                              files=files, ref="t", admission=["check_hashes"])
    return next(r for r in inv["rows"] if r["step"] == "check_hashes"), inv


def test_an_out_of_scope_subject_does_not_make_a_step_stale(ledger):
    """⭐⭐ THE HEADLINE. The step examined a path its own `scope_exclude` names.
    That path moving is not this step going stale -- it is a scope that does not
    match what the checker read."""
    row, _ = _row(ledger, [_hashes([(EXCLUDED, "old")])], {EXCLUDED: "new"})
    assert row["status"] != "STALE"
    assert row["status"] == "MISSING"


def test_the_row_says_the_scope_is_the_problem_not_the_run(ledger):
    """⚠ Silence would be a different bug. MISSING alone reads "never ran", and the
    operator runs it -- forever. The row must name the residue and say what re-running
    can and cannot do."""
    row, inv = _row(ledger, [_hashes([(EXCLUDED, "old")])], {EXCLUDED: "new"})
    assert EXCLUDED in row["why"]
    assert "scope" in row["why"] and "re-running cannot move this row" in row["why"]
    assert inv["unscoped"] == [EXCLUDED]


def test_every_in_scope_byte_identical_still_read_as_moved(ledger):
    """⭐ THE REPORTED SHAPE: "recorded against different bytes" while the bytes it is
    supposed to judge had not moved at all. It takes the COMPOUND case to reproduce --
    an in-scope subject matching exactly, plus out-of-scope residue that has moved. The
    residue supplied `stale`, `stale` beat SATISFIED, and the row announced a staleness
    that was not about anything in scope.

    ⚠ An earlier version of this test used the out-of-scope path ALONE and passed
    against the unfixed code, because a lone matching subject reads covered. It was
    testing a proxy. Left in this shape, and said out loud, so the next reader does not
    re-simplify it back.
    """
    rec = [_hashes([("register.md", "same"), (EXCLUDED, "old")])]
    row, _ = _row(ledger, rec, {"register.md": "same", EXCLUDED: "new"})
    assert row["status"] == "SATISFIED"
    assert not (row["why"] and "different bytes" in row["why"])


def test_an_in_scope_path_still_goes_stale(ledger):
    """⚠⚠ THE CONTROL THAT KEEPS THE FIX FROM BEING A HOLE. Narrowing the denominator
    must not stop a step's actual corpus from staling it."""
    row, inv = _row(ledger, [_hashes([("register.md", "old")])], {"register.md": "new"})
    assert row["status"] == "STALE"
    assert inv["complete"] is False


def test_a_switch_outside_the_scope_still_stales_the_key(ledger):
    """⭐⭐ V15's WHOLE MECHANISM, and the denominator is where it could be disarmed
    by accident. `shared_build_baseline.txt` is a declared switch and is NOT in
    check_hashes' scope -- if the fix above narrowed to `scope` alone, editing an
    exemption list would silently stop staling the key and a suppression would land
    unverified. That is the defect V15 exists to prevent, re-entering through the fix
    for a different one."""
    rec = [_hashes([("register.md", "a"), (SWITCH, "b")])]
    fresh, _ = _row(ledger, rec, {"register.md": "a", SWITCH: "b"})
    edited, inv = _row(ledger, rec, {"register.md": "a", SWITCH: "c"})
    assert fresh["status"] == "SATISFIED"
    assert edited["status"] == "STALE"
    assert inv["complete"] is False


def test_v16_evidence_outside_the_scope_still_stales_the_key(ledger):
    """⭐⭐ THE SAME HAZARD FOR V16. A checker's own module is outside its scanned
    scope by construction, so if the denominator were `scope` alone, editing a checker
    would stop expiring its records -- removing the only non-forgeable half of V16."""
    rec = [_hashes([("register.md", "a")], evidence=[(MODULE, "m")])]
    fresh, _ = _row(ledger, rec, {"register.md": "a", MODULE: "m"})
    edited, _ = _row(ledger, rec, {"register.md": "a", MODULE: "n"})
    assert fresh["status"] == "SATISFIED"
    assert edited["status"] == "STALE"


def test_an_unscoped_step_still_owes_the_whole_tree(ledger):
    """⚠ A type that has not said what it examines owes every path, and this fix must
    not quietly turn that default around. `decls` declares no scope, so its
    denominator is the tree."""
    rec = [{"id": "decls@t#0", "step": "decls", "verdict": "PASS", "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": "anything.md", "git_blob_id": "old"}],
            "basis": {"kind": "tree", "value": "t"}}]
    inv = inventory_mod.build(config=ledger.config, records=rec, action="push",
                              files={"anything.md": "new"}, ref="t",
                              admission=["decls"])
    assert next(r for r in inv["rows"] if r["step"] == "decls")["status"] == "STALE"


# -- ⭐⭐ THE GLOB SEMANTICS, PINNED — because a registry editor guessed them ----
#
# ZeroParadox asked, 2026-08-25: "if your matcher's glob semantics are documented
# anywhere, I would rather read them than re-derive them." They were documented — in a
# comment in `inventory.py`, which is not where anyone editing `required.v2.json`
# stands. Now that the registry lives in ZeroParadox's repo, the semantics are one
# repo away from the file they govern.
#
# The cost was already paid: it "fixed" a scope by ADDING a glob while leaving a
# blanket exclusion in place, and wrote into the registry that the exclusions were
# INERT because `*` does not cross `/`. That was inferred from an arithmetic
# coincidence (two unrelated scopes both totalling 59) and it is FALSE. The fix was a
# no-op wearing a rationale, and the rationale was about to become a recorded fact.
#
# So the answer lives in a control that fails if it ever stops being true.

def test_star_crosses_slash(ledger):
    """⭐⭐ `*` MATCHES `/`. `["*"]` therefore means EVERY path, not "top-level only".
    This is `fnmatch`, not shell globbing, and it is the single fact that would have
    prevented the near-miss above."""
    files = {"README.md": "a", "docs/deep/x.md": "b", "tools/verify/y.py": "c"}
    rec = [{"id": "decls@t#0", "step": "decls", "verdict": "PASS", "revision": 0,
            "decided": {"how": "mechanical", "passes": 1, "agreed": 1},
            "subjects": [{"path": p, "git_blob_id": b} for p, b in files.items()],
            "basis": {"kind": "tree", "value": "t"}}]
    inv = inventory_mod.build(config=ledger.config, records=rec, action="push",
                              files=files, ref="t", admission=["decls"])
    row = next(r for r in inv["rows"] if r["step"] == "decls")
    assert row["scope"] == 3, "an undeclared scope owes the whole tree"
    assert row["status"] == "SATISFIED"


def test_a_star_star_slash_prefix_MISSES_every_top_level_file(ledger, config_dir,
                                                              tmp_path):
    """⚠⚠ `**/*` IS WRONG RATHER THAN REDUNDANT, and it fails in the dangerous
    direction: it requires at least one `/`, so every top-level file falls out of
    scope silently. Anyone importing shell or gitignore intuitions writes this."""
    import json
    from core.ledger import Ledger
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["decls"] = {"family": "mechanical", "scope": ["**/*"],
                             "reason": "probe"}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "g.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")

    files = {"README.md": "a", "docs/x.md": "b"}
    inv = inventory_mod.build(config=led.config, records=[], action="push",
                              files=files, ref="t", admission=["decls"])
    row = next(r for r in inv["rows"] if r["step"] == "decls")
    assert row["scope"] == 1, "README.md must have fallen out — that is the defect"
    assert "docs/x.md" not in (row["subjects_unscoped"] or [])


def test_an_exclusion_cancels_an_inclusion_however_specific(ledger, config_dir,
                                                            tmp_path):
    """⭐ THE NEAR-MISS ITSELF: adding a precise glob to `scope` while a blanket
    `scope_exclude` still matches those paths is a NO-OP. Exclusions are applied after
    inclusions and do not care how specific the inclusion was."""
    import json
    from core.ledger import Ledger
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["decls"] = {"family": "mechanical",
                             "scope": ["*.md", ".claude/commands/*.md"],
                             "scope_exclude": [".claude/*.md"], "reason": "probe"}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "h.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")

    files = {"README.md": "a", ".claude/commands/rely.md": "b"}
    inv = inventory_mod.build(config=led.config, records=[], action="push",
                              files=files, ref="t", admission=["decls"])
    row = next(r for r in inv["rows"] if r["step"] == "decls")
    assert row["scope"] == 1, (
        "the blanket exclusion cancelled the specific inclusion — which is exactly "
        "the no-op-wearing-a-rationale that was nearly recorded as a measured fact")
