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
     `rely`, which is excluded precisely because it is unsatisfiable by construction."

Two sets of the SAME SIZE differing in membership — the units defect at its purest, where the
count is a true measurement of the wrong property, and the cheapest check anyone would reach
for is the one that cannot see it. The fact was measured, narrated, and never detected,
because nothing compared the sets themselves. **This file is that paragraph turned into a
line that fires.**

⭐ THE IDEA IS THE CONSUMER SESSION'S. They proposed a `check_briefs.py` leg asserting every
`--step` named in a brief is registered, after reporting a registered-type count they had
read off a differently-named field. Asked whether we had an equivalent blind spot; we did,
one repo over, in a mirror that documents itself as a mirror.

⚠ THIS TEST DETECTS AND DOES NOT DECIDE. Which way each mismatch should be resolved is GATE
POLICY -- it changes what blocks a push -- and two of the three are live migrations on the
consumer's side. The known set is pinned below so it cannot grow silently, and cannot be
quietly resolved either.
"""

from __future__ import annotations

import json
import os
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
#   prior_art  registry ['push']             admission []                    LOOSER, and
#              ⛔ DELIBERATE — DO NOT "FIX" EITHER SIDE. Confirmed by the consumer 2026-09-06
#              from `policy.v1.json`'s `_refrozen_2026_09_01c`: "Registering is not admitting.
#              `prior_art` is deliberately ABSENT from admission.v1.json... The row has to
#              EXIST for `batch.check_prior_art_attribution` to read it; `coverage_gap`
#              returns `steps: []` for a step that does not apply to the action." So
#              `actions: ["push"]` is load-bearing for a READER, not a gater: remove the
#              narrowing and their per-file push leg goes blind. The first attempt at exactly
#              that was reverted the same morning as backwards.
#              ⚠ The disagreement is still REAL and still worth flagging — only the
#              justification is elsewhere. Their finding, not mine: **a narrowing whose reason
#              lives in a different file from the entry is indistinguishable from an
#              unexplained one.** They are moving it onto the registry entry.
#
# ⛔ DO NOT ADD A LINE HERE TO MAKE THIS PASS. Adding one declares a new place where the two
# surfaces disagree about what gates a push.
KNOWN_MISMATCHES = {
    ("build", ("tag",), ("commit", "push", "tag")),
    ("rely", ("commit", "push", "tag"), ("tag",)),
    ("prior_art", ("push",), ()),
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
