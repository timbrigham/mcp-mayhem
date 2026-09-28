"""A signed loop-break carve must reach EVERY reader of scope, not just the served one.

⛔⛔ THE CARVE WAS HALF-APPLIED FOR A DAY AND I VERIFIED IT ON THE HALF THAT WORKED. Measured
2026-09-27, after the ZeroParadox session reported an obligation I had just told them was
structurally impossible:

    requirements('push')['copy_editor']['scope_exclude']        carve PRESENT
    config.required['types']['copy_editor']['scope_exclude']    carve ABSENT
    canpush._in_scope(copy_editor, '.claude/commands/copy-editor.md')   ->   True

`config.requirements()` merged the loop break into its own returned entry. `canpush._in_scope` —
the changed-path ratchet's only scope test — read `config.required` directly. So the ratchet owed
a verdict on the exact path a carve Tim signed exists to remove, `ratchet.owed` correctly listed
it, and the consumer ran a three-agent panel to clear a real obligation while I was telling them
to stop.

⚠⚠ AND THE MERGE SITE'S OWN COMMENT ALREADY WARNED ABOUT THIS — *"only the served requirement has
both"* — and records the consumer asserting three times that `adversary` has no `loop_break`,
"each time correctly scoped to the file it could read and each time concluding about the system."
I wrote that warning, built a second scope reader that bypassed the merge, and then used the
served surface as evidence that their correct report was wrong.

⭐ THE SWEEP FOUND THE CLASS, NOT JUST THE INSTANCE: five readers of `scope_exclude`. Two were raw
(`_in_scope`, `_witness`) and three were safe because they iterate `config.requirements(action)`.
Fixing only the reported one would have left `_witness` overstating coverage on carved paths.

⛔ AND THE CARVE IS DELIBERATELY NOT MERGED INTO `config.required` AT LOAD TIME, which was the
smaller diff: that dict must stay the registry AS WRITTEN, because `registry_scope_digest` and the
convergence freeze hash it against the consumer's own file. Merging a harness-side carve in would
make the freeze price a value present in no revision of their repo.
"""

import fnmatch

import pytest

from core import canpush as canpush_mod

CARVED_STEP = "adversary"
CARVED_PATH = ".claude/commands/adversary-review.md"


def test_the_resolver_unions_the_registry_and_the_carve(ledger):
    """⭐ ONE ANSWER TO "WHAT IS OUTSIDE THIS STEP'S SCOPE", and every reader goes through it."""
    got = ledger.config.scope_exclude_for(CARVED_STEP)
    raw = set((ledger.config.required["types"][CARVED_STEP].get("scope_exclude") or []))
    carve = set(ledger.config.loopbreaks["breaks"][CARVED_STEP]["exclude"])
    assert set(got) == raw | carve
    assert CARVED_PATH in got, "the carve is missing from the resolver"
    # ⚠ and the registry itself is UNCHANGED — the freeze hashes that dict
    assert CARVED_PATH not in raw, (
        "the carve leaked into config.required, so registry_scope_digest would now price a value "
        "that exists in no revision of the consumer's repo")


def test_the_ratchet_scope_test_honours_the_carve(ledger):
    """⭐⭐ THE HEADLINE, AND THE EXACT CALL THAT WAS WRONG. This returned True before the fix."""
    assert canpush_mod._in_scope(ledger.config, CARVED_STEP, CARVED_PATH) is False, (
        "the changed-path ratchet still owes verdicts on a carved path — a signed loop break is "
        "inert in the one place the deadlock it prevents actually arises")


def test_the_carve_does_not_widen_anything_else(ledger):
    """⛔ A CARVE ONLY EVER ADDS EXCLUSIONS. It must not make a step examine MORE, and it must not
    touch a step that has no carve."""
    cfg = ledger.config
    # a path the step genuinely owns stays in scope
    assert canpush_mod._in_scope(cfg, CARVED_STEP, "README.md") is True
    # an uncarved step's answer is exactly its registry's
    uncarved = next(s for s in cfg.required["types"]
                    if s not in (cfg.loopbreaks.get("breaks") or {}))
    assert cfg.scope_exclude_for(uncarved) == sorted(
        cfg.required["types"][uncarved].get("scope_exclude") or []), (
        f"{uncarved} has no carve and its excludes changed anyway")


def test_no_reader_of_scope_exclude_bypasses_the_resolver():
    """⛔⛔ THE CLASS GUARD. Fixing `_in_scope` alone would have left `_witness` overstating
    coverage, and the next reader someone adds would inherit the same bug.

    ⚠ A SOURCE SCAN, because the property is "no caller reads the raw dict", which no behavioural
    probe can establish — a call site reading raw would pass every test whose fixture happens to
    have no carve for that step.

    ⭐ THE ALLOWED FORMS ARE NARROW AND NAMED: the resolver itself, and iteration over
    `config.requirements(action)` whose entries already carry the merge.
    """
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for rel in ("core/canpush.py", "core/inventory.py"):
        for n, line in enumerate(
                (root / rel).read_text(encoding="utf-8").splitlines(), 1):
            if "scope_exclude" not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("f\"") \
                    or stripped.startswith('"'):
                continue                      # prose, not a read — see DC-51
            if "scope_exclude_for" in line:
                continue                      # through the resolver
            # ⚠ the safe form: pulling it off an entry that came from requirements()
            if re.search(r"\b(spec|_spec)\.get\(\"scope_exclude\"\)", line):
                offenders.append(f"{rel}:{n}: {stripped}")
    # ⛔ FLOOR: the three surviving `spec.get("scope_exclude")` reads iterate `reqs =
    # config.requirements(action)` and are SAFE. They are listed so that a FOURTH one fails here.
    KNOWN_SAFE_BECAUSE_THEY_ITERATE_REQUIREMENTS = 3
    assert len(offenders) == KNOWN_SAFE_BECAUSE_THEY_ITERATE_REQUIREMENTS, (
        "the set of raw `scope_exclude` reads changed. Every one must either go through "
        "`config.scope_exclude_for` or iterate `config.requirements(action)`, whose entries "
        "carry the carve. Found %d:\n  %s" % (len(offenders), "\n  ".join(offenders)))
