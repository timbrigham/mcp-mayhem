"""The admission set and the registry are a MIRROR, and nothing compared them until now.

⚠⚠ TWO SURFACES, ONE VOCABULARY, NO DETECTOR. `admission.v1.json` says which registered
types must be GREEN for gitRobot to let an action through; `required.v2.json` (verdictLedger's
registry, in the consumer's tree) says which types exist and carries each type's `actions`
narrowing WITH A STATED REASON. Admission's own comment names the relationship:

    "These lists mirror the registry's own `actions` narrowings. If admission and the
     registry ever disagree on an action, THE REGISTRY IS THE BUG -- it is the list that
     carries stated reasons."

**It states how to RESOLVE a disagreement and provides no way to NOTICE one.** Measured
2026-09-06: three of twenty-seven types disagree, and the file has been edited three times
since without any of them surfacing. A rule for resolving a conflict, with no detector for
the conflict, is a rule that fires only when somebody happens to look.

⭐⭐ AND IT WAS ALREADY KNOWN, WRITTEN DOWN, AND INERT FOR A WEEK. `requirements()` in
`gitrobot_server/server.py` has recorded this since 2026-08-30, in prose:

    "for `push` both lists are 20 entries and they DIFFER — the ledger marks `rely` required,
     gitRobot admits `build` instead. **Same count, 19 shared, so a reader comparing sizes
     concludes they agree.** A caller following the ledger's list burns rounds converging
     `rely`, which this server does not admit here."

⛔ THE QUOTE ABOVE USED TO END "...excluded precisely because it is unsatisfiable by
construction", and that half was FALSE -- measured 2026-09-09: `rely` carries 6 PASS records,
is ADMITTED at `tag`, and `coverage.require_complete` is false so partial coverage satisfies.
This test QUOTED the false clause as authority, which is the third control in two days found
asserting the thing it was written to police. Corrected at the source and here together,
because a quotation is a copy and copies are what this file exists to catch.

Two sets of the SAME SIZE differing in membership — the units defect at its purest, where the
count is a true measurement of the wrong property, and the cheapest check anyone would reach
for is the one that cannot see it. The fact was measured, narrated, and never detected,
because nothing compared the sets themselves. **This file is that paragraph turned into a
line that fires.**

⭐ THE IDEA IS THE CONSUMER SESSION'S. They proposed a `check_briefs.py` leg asserting every
`--step` named in a brief is registered, after reporting a registered-type count they had
read off a differently-named field. Asked whether we had an equivalent blind spot; we did,
one repo over, in a mirror that documents itself as a mirror.

⛔⛔ WHAT THIS TEST CANNOT SEE, stated so nobody reads its green as wider than it is. It compares
EFFECTIVE actions, so **an absent `actions` key and a key naming every action are identical to
it** — both resolve to all three. That is correct for its purpose (finding where the two surfaces
disagree about what gates what) and blind to the difference the consumer named: one claims
"nobody narrowed this", the other claims "all three were considered". `rely` is the measured
instance of the first reading as staleness a month on.

Measured 2026-09-06: `check_briefs` was registered with no `actions` key, the consumer added
`["commit","push","tag"]` explicitly with a stated reason, and **this test passed identically
before and after.** So a future entry silently LOSING its key would not fail here either.
Verifying that fix required reading the registry entry directly. **A behaviour checker cannot
police a documentation claim, and should not be cited as though it does.**

⚠ THIS TEST DETECTS AND DOES NOT DECIDE. Which way each mismatch should be resolved is GATE
POLICY -- it changes what blocks a push -- and two of the three are live migrations on the
consumer's side. The known set is pinned below so it cannot grow silently, and cannot be
quietly resolved either.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ADMISSION = Path(__file__).resolve().parents[1] / "config" / "admission.v1.json"

# ⚠⚠ THE KNOWN DISAGREEMENTS, 2026-09-06, WITH THEIR DIRECTION — direction is the whole
# reading. "Stricter" means admission demands MORE than the registry does: fail-closed, safe,
# still a disagreement. "Looser" means admission demands LESS, so a type the registry says
# must gate an action does not gate it.
#
#   build      registry ['tag']              admission [commit, push, tag]   STRICTER, safe
#   rely       registry [commit, push, tag]  admission [tag]                 LOOSER, and
#              DELIBERATE on this side — `_rely_not_admitted_at_commit_or_push` states it and
#              98c3480 landed it ("rely records and stops blocking — it gated the machinery it
#              reviews"). The consumer confirmed 2026-09-06 that their registry has NO
#              `actions` key for `rely` at all, so it defaults to every action rather than
#              narrowing. By admission's own rule the REGISTRY is the stale half.
#              ⛔ NOT RESOLVED UNILATERALLY: narrowing it removes a required row from
#              `inventory(action=push)`, which feeds `complete`, which gitRobot REQUIRES — so
#              it makes a push EASIER to judge complete. A loosening is gate policy even when
#              it only makes the record honest. With Tim.
#   prior_art  RESOLVED 2026-09-17 — the two surfaces now agree at `push`, on Tim's ruling.
#              ⭐ THE ENTRY IS GONE BECAUSE THE DISAGREEMENT IS, and this test is what forced
#              the bookkeeping: it ratchets in BOTH directions, so leaving the line here after
#              resolving it fails exactly as loudly as adding one would. The reason it sat here
#              from 2026-09-06 was `actions: []` in the registry; that was re-widened to
#              `actions: ["push"]` on 2026-09-01 and NOBODY MOVED THE NOTE, so this file
#              described a narrowing that had not existed for sixteen days.
#              ⚠ The reader-not-gater argument recorded here was correct and is unaffected:
#              the registry entry still has to EXIST for the consumer's per-file push leg to
#              read it. Admitting adds gating; it takes nothing away from that leg.
#
# ⛔ DO NOT ADD A LINE HERE TO MAKE THIS PASS. Adding one declares a new place where the two
# surfaces disagree about what gates a push.
# ⭐⭐ `copy_editor` WAS HERE FOR SIXTEEN DAYS AND CAME OUT 2026-09-22 — THE FIRST GENUINE
#              RESOLUTION IN THIS FILE THIS WEEK, as against two SHAPE CHANGES that fired the
#              ratchet without resolving anything. Worth the contrast: `pdf_coupling_in_push`
#              and `check_hashes` both moved tuples and stayed, because the disagreement was
#              never about WHICH action. This one is gone because the two surfaces now assert
#              the same obligation: the registry declares `actions: ['tag']` and
#              `admission.v1.json` admits it at tag.
#              ⚠ It came out only after the removal test BOTH files had stated since
#              2026-09-06 was actually met — "one real panel has run and been inspected."
#              Unmet for sixteen days: 0 records in 2,170, brief never executed. Tim's ruling
#              2026-09-22 was rehearse first, then admit on an inspected result rather than on
#              design intent, and the rehearsal earned it: the panel's FIRST execution returned
#              UNDECIDED, which is exactly what would have refused a live tag. Learned on a
#              rehearsal. The full evidence lives in `admission.v1.json`'s
#              `_copy_editor_admitted_at_tag_2026_09_22`, including the half that matters most
#              — the findings-UNION rule rather than the headcount, since all three readers
#              hedged that they were "probably alone" on findings every one of them shared.
#   check_briefs  registry [ALL — no `actions` key]  admission []             LOOSER, and
#              ⛔ EXPECTED AND CORRECT FOR NOW. Registered 2026-09-06 alongside `copy_editor`
#              so the brief-conformance leg can RECORD. Registering is not admitting; nothing
#              gates on it yet, and admitting a leg whose own `/rely` round just returned
#              BLOCKING:5 would gate on a checker that is still being fixed.
#              ⚠ Note the registry shape differs from `copy_editor`'s: no `actions` key at
#              all, so it defaults to EVERY action rather than narrowing to one. That is the
#              `rely` shape, and it is the shape that later reads as a stale registry rather
#              than a deliberate narrowing — worth an `actions` key with a reason before it
#              is forgotten.
KNOWN_MISMATCHES = {
    ("build", ("tag",), ("commit", "push", "tag")),
    ("rely", ("commit", "push", "tag"), ("tag",)),
    ("check_briefs", ("commit", "push", "tag"), ()),
    #   pdf_coupling_in_push  registry [push]  admission []   LOOSER, and
    #              ⭐ DELIBERATE AND EXPECTED. Registered by ZeroParadox 2026-09-21 to split a
    #              step that was carrying TWO properties under one name: `record_pdf_coupling`
    #              asks a TREE question (does any build script on disk name this PDF — trivially
    #              true for all 40, so near-vacuous as a gate) while `check_pdf_coupling(ranges)`
    #              asks a PUSH-DIFF question (does a script CHANGED IN THIS PUSH name this
    #              changed PDF — the one with teeth, tightened by their P7-3).
    #              ⛔⛔ THE SPLIT IS NOT COSMETIC, IT IS A SOUNDNESS FIX. `sign()` stores an
    #              accept as `verdict: "PASS"`, so signing to clear the push-diff leg would ALSO
    #              have satisfied the tree-scope property at that basis — one signature
    #              discharging two questions, one of which nobody examined, on a step pinned at
    #              `min_coverage: 1.0` over 40 subjects.
    #              ⚠ NOT ADMITTED HERE ON PURPOSE, and this side needs no change: `sign()`
    #              validates against the REGISTRY, and `find`/`get` ignore admission entirely, so
    #              a registered-unadmitted step is signable and consultable while gating nothing.
    #              Registering is free; admitting is the deliberate act.
    #              ⭐ NARROWED TO `["push"]` IN THE REGISTRY 2026-09-21 (`8c86c572`), so the
    #              half of this note that asked for it is now spent. It previously declared NO
    #              `actions` key and defaulted to EVERY action — the `rely` / `check_briefs`
    #              shape this file warns reads later as a stale registry rather than a
    #              deliberate narrowing. Its whole purpose is the PUSH diff and it now says so.
    #              ⚠⚠ THE ROW STAYS, AND THAT IS THE POINT WORTH READING TWICE: the registry
    #              edit did NOT resolve this mismatch, it CHANGED ITS SHAPE — from
    #              (every action vs nothing) to (push vs nothing). The disagreement was never
    #              about WHICH actions; it is that the step gates nothing here at all, which is
    #              deliberate and unchanged. A row like this is exactly what a resolution can be
    #              mistaken for: the tuple moved, so the ratchet fired, and a reader clearing
    #              it on that signal alone would have dropped a live exemption.
    #              ⭐ SATISFIED WHEN: the hook consults the ledger for a signed accept and this
    #              step becomes the gating surface — then it joins `admission.v1.json` and this
    #              line goes.
    ("pdf_coupling_in_push", ("push",), ()),
    # ⭐⭐ `check_hashes` WAS HERE AND IS GONE, 2026-09-21, AND THE LIFECYCLE IS THE LESSON.
    # It was added the moment admission narrowed the step to the tip (Tim's ruling: a STALE row
    # does not mean the hashes DISAGREE, it means no verdict exists at those bytes, so requiring
    # it per-commit demanded a green record for a state `R-REGISTER` deliberately makes false
    # mid-arc). The note said the REGISTRY was the half to correct, because its entry declared
    # no narrowing and so claimed every action by default. The consumer landed
    # `actions: ["push", "tag"]` in `8c86c572` and the surfaces now agree, so the row came out
    # in the same round rather than being left to rot.
    #
    # ⚠ THE WINDOW BETWEEN THE TWO EDITS IS NOT A BUG AND MUST NOT BE ENGINEERED AWAY. This
    # ratchet is exact equality, so it fails when new debt appears AND when listed debt is fixed
    # without updating the list — which means between their commit and this one it failed as
    # RESOLVED. That red is the check doing its job across a repository boundary nothing else
    # spans. A one-directional check would have let the stale row sit indefinitely, asserting a
    # disagreement that no longer existed — the same defect class as the freeze line that told a
    # reader to compare a scope digest against a file hash.
}


def _registry() -> dict:
    """The registry is the CONSUMER's file, read live by verdictLedger via ZPLEDGER_CONFIG.

    ⚠ A missing registry SKIPS LOUDLY rather than passing. A cross-surface check that
    silently succeeds when it cannot see one of the surfaces is the absence-as-success defect
    wearing a green tick.
    """
    root = os.environ.get("ZPLEDGER_CONFIG", r"C:\Workspace\ZeroParadox\tools\verify")
    path = Path(root) / "required.v2.json"
    if not path.exists():
        pytest.skip(f"registry not readable at {path} — this check saw only ONE of the two "
                    f"surfaces and is reporting nothing, not agreement. "
                    f"SATISFIED WHEN: ZPLEDGER_CONFIG names the directory holding "
                    f"required.v2.json.")
    return json.loads(path.read_text(encoding="utf-8"))


def _compare():
    reg = _registry()
    types = reg.get("types") or reg.get("required")
    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))["admission"]
    actions = set(admission)
    found = set()
    for name, entry in types.items():
        narrowing = entry.get("actions")
        # ⚠ `actions` ABSENT means every action, per §9b "required by default". `actions: []`
        # means none — an advisory type that records but never gates. Those are different
        # facts and collapsing them would make every advisory type look like a mismatch.
        expected = actions if narrowing is None else set(narrowing)
        actual = {a for a, names in admission.items() if name in names}
        if expected != actual:
            found.add((name, tuple(sorted(expected)), tuple(sorted(actual))))
    return types, found


def test_admission_names_only_registered_types():
    """⚠ A type gitRobot admits but the registry has never heard of buys no coverage.

    `batch.py`'s own rule: such a name "must never be read as a pass". This is the direction
    that fails OPEN — gitRobot would wait for a green verdict that can never be recorded,
    or worse, treat the absence as satisfied.
    """
    types, _ = _compare()
    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))["admission"]
    unknown = {(a, n) for a, names in admission.items() for n in names if n not in types}
    assert not unknown, f"admission names types the registry does not define: {sorted(unknown)}"


def test_the_two_surfaces_disagree_exactly_where_recorded():
    """⭐ RATCHETED IN BOTH DIRECTIONS, like the schema debt.

    A new disagreement fails this. Resolving a recorded one ALSO fails it, which is the half
    that matters: it forces the set down rather than letting a stale allowlist over-report.
    """
    _, found = _compare()
    assert found == KNOWN_MISMATCHES, (
        f"admission/registry disagreement moved.\n"
        f"  NEW (a type now gates differently on the two surfaces): "
        f"{sorted(found - KNOWN_MISMATCHES)}\n"
        f"  RESOLVED (remove from KNOWN_MISMATCHES): "
        f"{sorted(KNOWN_MISMATCHES - found)}")


def test_check_hashes_gates_the_push_and_not_every_commit():
    """⛔⛔ `check_hashes` IS A TIP PROPERTY. Tim's ruling 2026-09-21, after the premise was
    falsified and held.

    It asks whether build-script bytes match the token recorded in `register.md`. `R-REGISTER`'s
    workflow — edit, bump the version, rebuild the PDF, recompute the token — completes per ARC,
    and the stub-first protocol deliberately commits incomplete work as rollback points.

    ⚠⚠ AND THE REASON IS SHARPER THAN "IT COMPLETES PER ARC": a STALE row does not mean the
    hashes DISAGREE, it means no verdict exists at those bytes. Requiring the step per-commit
    required a PASSING verdict for a property the protocol deliberately makes FALSE mid-arc — a
    green record for a state the workflow intends to be red.

    ⭐ MEASURED on `origin/illustrated..illustrated`, 42 commits: blocking 18/42 → 2/42, every
    removed blocker `stale:check_hashes`.

    ⛔ THE TIP MUST KEEP IT. The push publishes HEAD, so the state that reaches the world is
    still checked; only intermediates stop being asked a question their own protocol answers
    "not yet". A future edit that drops it from `push` too would turn a scoping fix into a hole.
    """
    import json
    import pathlib
    cfg = json.loads((pathlib.Path(__file__).resolve().parents[1] / "config"
                      / "admission.v1.json").read_text(encoding="utf-8"))
    adm = cfg["admission"]
    assert "check_hashes" not in adm["commit"], (
        "check_hashes gating every commit demands a green verdict for a property stub-first "
        "deliberately makes false mid-arc")
    assert "check_hashes" in adm["push"], (
        "the TIP must still be checked — the push is what publishes the bytes")
    assert any(k.startswith("_check_hashes_is_a_tip_property") for k in cfg), (
        "the scoping decision must carry its reasoning in the file, not only in a commit message")


def test_a_push_only_step_must_declare_a_scope():
    """⛔⛔ THE THIRD LEG OF A FAIL-OPEN THAT WAS REPRODUCED, NOT ARGUED — 2026-09-21.

    A step that is admitted at `push`, NOT admitted at `commit`, and declares NEITHER `scope`
    NOR `when` falls through every mechanism that could refuse it:

        intermediates   do not gate it — it is not in the commit admission set
        the TIP row     forgave it when its stale paths lay outside the tip commit's own diff
        the ratchet     skips it — `_judging_steps` consults only steps that STATE an
                        obligation surface, deliberately, because silence is not a claim to
                        everything

    A fixture composing all three returned `allowed: True` over a tip reading
    `stale: ['check_prose'], required 2, satisfied 1, complete True` — a push publishing bytes
    an admitted step had never judged.

    ⭐ THE TIP LEG IS FIXED IN verdictLedger (`published` now prices the RANGE at the tip), so
    this is the belt to that braces. It is worth having anyway, and the reason is specific:
    **the two halves live in different repositories.** The tip fix is in code this repo owns;
    whether a push-only step declares a scope is decided in `required.v2.json`, which it does
    not own and cannot enforce. This test is the only place the two files are read together.

    ⚠⚠ IT WAS A COINCIDENCE WHEN IT WAS FOUND, NOT A DESIGN. The push-only set was CREATED the
    same day by narrowing `check_hashes` to the tip, and the scopes of the other three members
    — adversary, editorial, prior_art — were under active edit that same afternoon. Nothing
    linked the safety of one file's narrowing to the other file's scopes, which is exactly the
    shape `_removing_an_entry_can_invalidate_a_downgrade_elsewhere` already records one door
    over: a property resting on a compensating control, with no link to that control.

    SATISFIED WHEN: every step in (push admission - commit admission) declares `scope` or
    `when` in the registry, so the changed-path ratchet consults it over the whole range.
    """
    reg = _registry()
    types = reg.get("types") or reg.get("required")
    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))["admission"]

    push_only = set(admission.get("push") or ()) - set(admission.get("commit") or ())
    assert push_only, (
        "fixture floor: no step is push-only, so this check examined NOTHING. An assertion "
        "that never ran is indistinguishable from one that passed.")

    unscoped = sorted(
        s for s in push_only
        if not ((types.get(s) or {}).get("scope") or (types.get(s) or {}).get("when")))

    assert not unscoped, (
        f"{unscoped} are admitted at push, NOT at commit, and declare no scope or when in the "
        f"registry. Nothing gates them on intermediates and the changed-path ratchet does not "
        f"consult them, so a STALE row over bytes the push publishes can go unrefused. "
        f"INSTEAD: give each a `scope` (or `when`) in required.v2.json so the ratchet covers "
        f"it, or admit it at `commit` as well so intermediates do.")


# ⛔⛔ A DEFERRAL WHOSE EXPIRY CONDITION IS SOMEBODY ELSE'S UNILATERAL ACTION -------------
#
# ⚠⚠ MEASURED 2026-09-27, AND THE DEFECT IS MINE. `copy_editor._module_why` has said since
# 2026-09-08, in terms:
#
#     "TENSION, unresolved on purpose: the brief's tally rule is 2-of-3 and V3 requires
#      unanimity for a PASS under `agreement` ... if that is wrong it is Tim's call, and
#      `copy_editor` is admitted by nothing so nothing is gated on the answer."
#
# **That is a deliberate deferral with a STATED EXPIRY CONDITION, and I expired it** by adding
# `copy_editor` to `admission.push` on 2026-09-26 without ever looking at what rested on it not
# being admitted. The gate then bound a step whose central question was explicitly parked on the
# premise that it bound nothing. Nothing was mis-recorded and the gate held — the cost was that
# the question surfaced on a real panel run instead of before one.
#
# ⭐ THE CLASS, WHICH IS WHAT MAKES IT WORTH A TEST RATHER THAN AN APOLOGY: a deferral is safe
# only while its condition holds, and here the condition was an ADMISSION ENTRY IN ANOTHER REPO —
# something I can change alone, in one line, without reading their file. **A premise one party
# can invalidate without noticing is not a premise, it is a race.**
#
# ⚠ IT IS A PROSE MATCH AND THEREFORE HEURISTIC, AND THE DIRECTION IS THE JUSTIFICATION. A false
# positive is their wording tripping a bar: visible, cheap, resolved by acknowledging it here. The
# false negative is exactly what happened on 2026-09-26 and cost a deferred question surfacing
# mid-run. Fail toward noticing.
NOT_ADMITTED_PREMISE = re.compile(
    r"admitted by nothing|admitted at nothing|gates nothing|nothing is gated"
    r"|where nothing gates|deliberately absent from", re.I)

# ⚠ ACKNOWLEDGED, RATCHETED BOTH WAYS like KNOWN_MISMATCHES: a NEW match fails, and clearing an
# acknowledged one without removing it from this set ALSO fails. A one-directional list lets debt
# sit forever, which is the failure the mismatch ratchet above was written for.
ACKNOWLEDGED_STALE_PREMISES = {
    # ⛔ LIVE DEBT — the text still asserts the premise as current.
    # Tim ruled the tension 2026-09-27: a genuine 2-of-3 split records UNDECIDED and is accepted
    # by `signature`, and a `panel` vocabulary was commissioned separately. So the QUESTION is
    # resolved while this key's TEXT still says nothing is gated on the answer.
    # ⚠ Correcting it is the consumer's edit in the consumer's file. This entry records that it
    # is owed, and it must come out when they fix it.
    # ⭐ TRACKED ON THEIR SIDE AS `COPYEDITOR-MODULEWHY-STALE` (their DEFECTS.md, filed 2026-09-27,
    # verified at the source rather than taken on my report), in the same document family as
    # `ADMIT-1` and `COPYEDITOR-ESCALATION-1`. ⚠⚠ THE ID IS WHY THIS LINE EXISTS: an acknowledged
    # entry with no pointer is indistinguishable from one nobody is tracking, and an exemption
    # list is exactly where a forgotten item sits quietly forever. A reader who finds this key
    # still matching in a month can ask about a NAMED ROW instead of rediscovering the question.
    ("copy_editor", "_module_why"): "live",

    # ⚠⚠ HISTORICAL PROVENANCE, NOT DEBT — these keys QUOTE an expired or false premise in order
    # to correct it, and their own headers say so. `_scope_was_null_until_2026_09_22` says its
    # conclusion is reversed; `prior_art._admission_is_action_scoped_2026_09_22` opens with "THIS
    # KEY USED TO BE CALLED `_registered_is_not_admitted` AND ITS CENTRAL CLAIM WAS FALSE".
    #
    # ⛔ THE DISTINCTION IS THE WHOLE VALUE OF CLASSIFYING THESE. A detector over prose cannot
    # tell a premise being ASSERTED from one being QUOTED AND RETRACTED — that is `DC-51`, a
    # detector counting prose about the marker, and it is the predicted cost of a heuristic
    # guard. Paying it as one labelled line each is the trade that was argued for; leaving them
    # unlabelled would make the acknowledged set read as four items of debt when it is one.
    ("copy_editor", "_scope_was_null_until_2026_09_22"): "historical",
    ("prior_art", "_admission_is_action_scoped_2026_09_22"): "historical",
}


def _stale_premise_keys(types, admitted) -> set:
    """Every (step, key) where an ADMITTED step's rationale still asserts it gates nothing.

    ⚠ EXTRACTED so the ratchet can be tested in BOTH directions. Inline, the reverse half —
    "an acknowledged entry stopped matching, so remove it" — was unreachable by any test, and a
    mutation setting `resolved = set()` survived. A one-directional ratchet lets debt sit forever,
    which is the exact failure the mismatch ratchet above this was written for.
    """
    found = set()
    for step in sorted(admitted):
        for key, value in (types.get(step) or {}).items():
            if key.startswith("_") and isinstance(value, str)                     and NOT_ADMITTED_PREMISE.search(value):
                found.add((step, key))
    return found


def _admitted_steps() -> set:
    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))["admission"]
    return {n for names in admission.values() for n in names}


def _premise_debt(acknowledged=None) -> tuple:
    """(new, resolved) — the two directions of the ratchet, computed OUTSIDE any test body.

    ⛔⛔ IT LIVES HERE BECAUSE PUTTING IT IN THE TEST MADE THE TEST UNTESTABLE. Mutations replacing
    `new = found - acknowledged` with `new = set()` INSIDE the test SURVIVED — twice — because the
    only other test exercised set arithmetic in isolation rather than the guard that uses it. **A
    control that verifies `a - b` works is testing Python, not the guard.** With the computation
    here, neutering it breaks every caller, and the synthetic-input tests below reach it.
    """
    ack = set(ACKNOWLEDGED_STALE_PREMISES if acknowledged is None else acknowledged)
    types, _ = _compare()
    found = _stale_premise_keys(types, _admitted_steps())
    return found - ack, ack - found


def test_no_admitted_step_rests_on_a_premise_that_it_gates_nothing():
    """⛔⛔ THE GUARD FOR THE CLASS ABOVE. Tim's ruling 2026-09-27.

    For every step gitRobot ADMITS, no rationale key in the registry may still assert that the
    step gates nothing — because a decision deferred on that premise is unsafe the moment the
    admission entry lands, and the admission entry is mine to add alone.

    ⚠ SWEPT AT THE TIME OF WRITING and the result is bounded, which is worth recording: FIVE keys
    across the registry rest on a not-admitted premise. Three are `pdf_coupling_in_push`'s and are
    SAFE — it is admitted at nothing, verified. Two are `copy_editor`'s, whose premise expired on
    2026-09-26. So exactly one live expiry, not a systemic rot.
    """
    types, _ = _compare()
    # ⛔ FLOOR FIRST: a sweep returning nothing makes every assertion below pass for the wrong
    # reason. Three keys matched on 2026-09-27.
    assert _stale_premise_keys(types, _admitted_steps()), (
        "the premise sweep found NOTHING, so this test cannot fail — either the detector broke "
        "or every key was corrected; check which before touching the acknowledged set")
    # ⚠⚠ ONE COPY OF THE COMPUTATION, and it lives in `_premise_debt`. The first attempt at this
    # extraction left the sweep inline HERE as well as in the helper — two copies of exactly the
    # defect this whole file exists to detect, introduced while refactoring to remove it.
    new, resolved = _premise_debt()
    assert not new, (
        "an ADMITTED step carries a rationale key still asserting that it gates nothing, so a "
        "decision deferred on that premise is now unsafe: %s\n"
        "⛔ Read the key before clearing this. Either the deferred question needs deciding, or "
        "the text is stale and the consumer owes the correction — and either way it must be "
        "acknowledged here rather than ignored." % sorted(new))

    assert not resolved, (
        "acknowledged stale premises no longer match, so the text was corrected: remove them "
        "from ACKNOWLEDGED_STALE_PREMISES. %s" % sorted(resolved))


def test_the_premise_detector_would_actually_fire():
    """⛔⛔ A DETECTOR NOBODY HAS SEEN FIRE IS A HYPOTHESIS. The test above passes today because
    every match is acknowledged, which is indistinguishable from a pattern that matches nothing.

    ⚠ This is the floor assertion: the pattern must match the ACTUAL sentence that caused the
    2026-09-26 miss, quoted from the registry rather than invented, and must NOT match ordinary
    rationale prose.
    """
    real = ("if that is wrong it is Tim's call, and `copy_editor` is admitted by nothing so "
            "nothing is gated on the answer.")
    assert NOT_ADMITTED_PREMISE.search(real), (
        "the detector does not match the sentence it was written for")
    for benign in ("this step is admitted at push and tag",
                   "the scope was declared so the ratchet has something to count",
                   "registered 2026-09-21 to split a step carrying two properties"):
        assert not NOT_ADMITTED_PREMISE.search(benign), (
            f"the detector fires on ordinary rationale: {benign!r}")
    # ⚠ AND THE ACKNOWLEDGED SET MUST BE NON-EMPTY TODAY, because it records real debt. If it
    # empties, either the consumer fixed both keys (remove this floor) or someone cleared the
    # list to make the suite green.
    assert ACKNOWLEDGED_STALE_PREMISES, (
        "the acknowledged set is empty; it held three entries on 2026-09-27")
    # ⭐ AND THE LIVE COUNT IS THE NUMBER THAT MATTERS — the one Tim was told was "exactly one".
    # ⚠ It was reached with a NARROWER manual grep than this guard uses: my sweep missed
    # `prior_art._admission_is_action_scoped_2026_09_22` entirely and the guard found it on its
    # first run. The conclusion survived only because that key turned out to be historical.
    live = [k for k, v in ACKNOWLEDGED_STALE_PREMISES.items() if v == "live"]
    assert live == [("copy_editor", "_module_why")], (
        f"the set of LIVE expired premises changed: {live}. A new one means an admitted step's "
        f"deferred question is unsafe right now; losing this one means the consumer corrected "
        f"the text and it should leave the acknowledged set entirely.")


def test_the_ratchet_fires_in_BOTH_directions():
    """⛔⛔ THE REVERSE HALF, WHICH NO TEST COULD REACH UNTIL THE SWEEP WAS EXTRACTED. A mutation
    setting `resolved = set()` SURVIVED the first version — so "an acknowledged entry stopped
    matching, remove it" was asserted and never exercised.

    ⚠ Both directions matter for the same reason KNOWN_MISMATCHES ratchets both ways: new debt
    must fail, AND debt that was silently paid must fail, or the acknowledged list becomes a
    permanent exemption nobody revisits.
    """
    LIVE = ("copy_editor", "_module_why")
    GHOST = ("copy_editor", "_a_key_that_does_not_exist")

    # ⭐ DRIVES THE REAL HELPER WITH SYNTHETIC ACKNOWLEDGEMENTS, so neutering either direction
    # inside `_premise_debt` fails here rather than passing on isolated arithmetic.
    full = set(ACKNOWLEDGED_STALE_PREMISES)

    # FORWARD: drop an acknowledgement and the key must surface as NEW
    new, _ = _premise_debt(full - {LIVE})
    assert LIVE in new, (
        "dropping an acknowledgement did not surface the key as new — the forward direction of "
        "the ratchet is not computed")

    # REVERSE: acknowledge something that matches nothing and it must surface as RESOLVED
    _, resolved = _premise_debt(full | {GHOST})
    assert GHOST in resolved, (
        "an acknowledged entry matching nothing was not surfaced for removal — the reverse "
        "direction is not computed, so the list becomes a permanent exemption")

    # ⚠ and with the real set, BOTH must be empty — which is what the main test asserts
    assert _premise_debt() == (set(), set())


def test_the_detector_matches_nothing_when_no_step_is_admitted():
    """⚠ SCOPE CONTROL. The guard is about ADMITTED steps, so with an empty admitted set it must
    find nothing — otherwise it is sweeping the whole registry and its name is wrong.
    ⭐ This is what makes `pdf_coupling_in_push`'s three keys correctly INVISIBLE: it is admitted
    at nothing, so its not-admitted premises are true and not debt."""
    types, _ = _compare()
    assert _stale_premise_keys(types, set()) == set()
    # and the three pdf_coupling_in_push keys must NOT appear while it is unadmitted
    assert ("pdf_coupling_in_push" not in {s for s, _ in
                                          _stale_premise_keys(types, _admitted_steps())}), (
        "pdf_coupling_in_push surfaced as debt while it is admitted at nothing — its "
        "not-admitted premises are TRUE, which is the whole distinction this guard draws")
