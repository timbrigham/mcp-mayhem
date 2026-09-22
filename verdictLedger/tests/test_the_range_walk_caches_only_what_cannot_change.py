"""A range walk must not recompute what a commit cannot change — and must not share what it can.

⛔⛔ THIS IS A REACHABILITY FIX WEARING A PERFORMANCE FIX'S CLOTHES, AND THAT IS WHY IT HAS
TESTS RATHER THAN A BENCHMARK. `gitRobot.push` calls `can_push` over the whole range
SYNCHRONOUSLY, before it emits the `run_id` a caller polls with. So this walk's cost is paid
inside the client's 300s window. Measured 2026-09-21 on a real 43-commit push: 339s here, and
the client abandoned the call 39 seconds short. **The handle that exists so a long push
survives a short window was itself gated behind the most expensive call in the flow** — the
bigger the arc, the more certainly the caller lost it.

⭐ PROFILED RATHER THAN GUESSED, 2026-09-22, after a first diagnosis that was confidently wrong
(the ledger inventory for the head — measured at 6s, not the cause at all):

    inventory.build     43 calls   672s     once per commit
    _subject_index      43 calls   349s     REBUILT over the same 5,375 records every commit
    fnmatch             44.6M      228s
    ntpath.normcase     89.2M      146s     Windows LCMapStringEx, 37s inside the Win32 call

Two values, neither of which a commit can change, recomputed once per commit. Hoisting both:
**199.9s → 9.0s over 43 commits, byte-identical output, 22.3x.** Per-commit 4.65s → 0.21s, so
the 300s client ceiling moves from ~64 commits to ~1437.

⚠⚠ TIM'S RULING 2026-09-22 WAS "MAKE IT FASTER FIRST", and the reason is the part worth keeping:
the alternatives — moving the gate check into the worker, or splitting tip-sync from range-async
— both fix reachability by BREAKING A CONTRACT STATED ON THE TOOL: *"Every REFUSAL is still
immediate and synchronous… 'not allowed' always comes back from the call you made."* A speedup
keeps the promise. **When a contract and a performance problem collide, price the performance
problem first; it is the only one of the two that can be fixed without telling every caller.**
"""

import json
import pathlib
import subprocess

import pytest

from core import canpush as canpush_mod
from core import inventory as inventory_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_encoding"
PATH = "doc.md"


def _walk(ledger, tmp_path, rng, records, admission, commit_admission=None, naive=False,
          monkeypatch=None):
    """One `can_push`, optionally with the caches disabled so the two can be compared."""
    if naive:
        orig = inventory_mod.build

        def build_naive(**kw):
            # ⚠ Strip the caches and nothing else, so the ONLY variable is whether the
            # commit-invariant values were reused or recomputed.
            kw.pop("subject_index", None)
            kw.pop("scope_audit", None)
            return orig(**kw)
        monkeypatch.setattr(canpush_mod.inventory_mod, "build", build_naive)
    return canpush_mod.check(
        records=list(records), config=ledger.config, repo=str(tmp_path), rev_range=rng,
        admission=list(admission),
        commit_admission=list(admission if commit_admission is None else commit_admission),
        limit=200)


def _fixture(tmp_path):
    """A multi-commit range where each commit moves a shared file, plus a second file."""
    base, shas = _repo(tmp_path, n=3)
    return base, shas


def test_the_cached_walk_answers_exactly_what_the_uncached_walk_answers(ledger, tmp_path,
                                                                        monkeypatch):
    """⛔⛔ THE ONLY GUARD THAT MATTERS, AND IT IS AN EQUIVALENCE, NOT A SPOT CHECK.

    A cache in a GATE is not a performance question, it is a correctness question: a wrong
    reuse here serves one commit's coverage as another's, which is a true value read against
    the wrong object — the defect class this module exists to remove. Asserting a few fields
    matched would leave every field nobody thought to assert unprotected, so this compares the
    WHOLE serialised answer.

    ⭐ It is also the check that was run against the live 43-commit range before the change
    shipped: identical output, 22.3x faster. This is that check, pinned.
    """
    base, shas = _fixture(tmp_path)
    old, tip = shas[0], shas[-1]
    records = [_rec(STEP, PATH, _blob(tmp_path, s, PATH), s) for s in shas]

    cached = _walk(ledger, tmp_path, f"{old}..{tip}", records, [STEP])
    naive = _walk(ledger, tmp_path, f"{old}..{tip}", records, [STEP],
                  naive=True, monkeypatch=monkeypatch)

    assert cached["commits_in_range"] >= 2, (
        "fixture floor: a single-commit range cannot exercise reuse ACROSS commits, which is "
        "the entire thing under test")
    assert json.dumps(cached, sort_keys=True, default=str) == \
           json.dumps(naive, sort_keys=True, default=str)


def test_the_subject_index_is_built_once_for_the_whole_walk(ledger, tmp_path, monkeypatch):
    """⭐ THE CLAIM IS "ONCE", SO COUNT IT. Asserting the answer is right would pass just as
    happily if the hoist had silently stopped applying — which is how a performance fix rots:
    nothing fails, it just gets slow again, and the next person profiles it from scratch."""
    base, shas = _fixture(tmp_path)
    old, tip = shas[0], shas[-1]
    records = [_rec(STEP, PATH, _blob(tmp_path, s, PATH), s) for s in shas]

    calls = []
    real = inventory_mod._subject_index
    monkeypatch.setattr(inventory_mod, "_subject_index",
                        lambda r: (calls.append(1), real(r))[1])
    monkeypatch.setattr(canpush_mod.inventory_mod, "_subject_index",
                        inventory_mod._subject_index)

    result = _walk(ledger, tmp_path, f"{old}..{tip}", records, [STEP])

    assert result["commits_in_range"] >= 2, "fixture floor: more than one commit must be walked"
    assert len(calls) == 1, (
        f"the subject index was built {len(calls)} time(s) for a "
        f"{result['commits_in_range']}-commit walk; it is a pure function of `records`, which "
        f"does not change across a walk, so it must be built exactly once")


def test_a_caller_that_passes_no_cache_still_gets_an_answer(ledger, tmp_path):
    """⚠ ABSENCE MUST MEAN COMPUTE, NEVER "ASSUME NOTHING FOUND". `ledger.py` and every direct
    caller of `build` pass neither cache. A new optional parameter must not change what a
    caller who does not pass it receives — least of all by defaulting to an empty index, which
    would read as "no step has examined anything" and render as MISSING across the board."""
    base, shas = _fixture(tmp_path)
    tip = shas[-1]
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]
    files = {PATH: _blob(tmp_path, tip, PATH)}

    inv = inventory_mod.build(config=ledger.config, records=records, action="push",
                              files=files, ref=tip, admission=[STEP])

    assert inv["required"] == 1
    assert inv["satisfied"] == 1, (
        "a caller passing no subject_index got an empty one rather than a computed one")
    assert inv["complete"] is True


def test_the_scope_audit_is_not_shared_across_different_admission_sets(ledger, tmp_path):
    """⛔⛔ THE CACHE KEY CARRIES BOTH VARIABLES, AND GETTING THIS WRONG WOULD BE THE EXACT
    DEFECT THE CACHE SPEEDS UP THE DETECTION OF.

    `subjects_outside_scope` rows stamp `admitted`, which is read from the ADMISSION SET, while
    the scope globs come from the ACTION. Two calls sharing an action but differing in
    admission are therefore NOT interchangeable. Keying on action alone would serve one call's
    rows to another — a true value computed against the wrong object, inside the module written
    to remove that class.

    ⚠ This is the case a range walk hits every single time: the tip is judged as `push` and the
    intermediates as `commit`, with different admission sets, in ONE call sharing ONE cache.
    """
    base, shas = _fixture(tmp_path)
    tip = shas[-1]
    files = {PATH: _blob(tmp_path, tip, PATH)}
    records = [_rec(STEP, PATH, _blob(tmp_path, tip, PATH), tip)]
    shared: dict = {}

    admitted = inventory_mod.build(config=ledger.config, records=records, action="push",
                                   files=files, ref=tip, admission=[STEP],
                                   scope_audit=shared)
    unadmitted = inventory_mod.build(config=ledger.config, records=records, action="push",
                                     files=files, ref=tip, admission=[],
                                     scope_audit=shared)

    assert len(shared) == 2, (
        f"one cache entry served two different admission sets (keys: {sorted(shared)}). The "
        f"key must carry the admission set as well as the action.")
    # and the answers must differ in the way the admission set makes them differ
    assert admitted["admission_state"] == "SET"
    assert unadmitted["admission_state"] == "EMPTY"
