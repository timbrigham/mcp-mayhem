"""`coverage_gap`'s truncation contract — it now has an EXTERNAL DEPENDENT.

⭐⭐ ZeroParadox 2026-09-01 built `batch.check_prior_art_attribution(ranges)`, a BLOCKING push
leg, on top of this call. `record.owing_paths()` asks with `limit: 5000` and relies on exactly
two properties:

    1. `paths` is COMPLETE whenever `truncated` is falsy
    2. `truncated` is ACCURATE

and REFUSES the answer rather than using a capped list — because a partial answer silently
under-reports what is owed, which is the failure that leg exists to prevent.

⚠⚠ THAT TURNS AN IMPLEMENTATION DETAIL INTO A CONTRACT. Before today `paths`/`truncated` were
a rendering convenience with a cap; now a gate on the other side of the fence blocks pushes on
them. Softening either property would not fail here — it would silently weaken a blocking check
in another repository, which is the cross-layer version of every defect found this weekend.
Pinned so it cannot be softened quietly.
"""

import pytest

from conftest import good
from core import inventory as inventory_mod


def _gap(ledger, records, files, admission, limit, action="commit"):
    return inventory_mod.coverage_gap(config=ledger.config, records=records, action=action,
                                      files=files, admission=admission, limit=limit)


def _many(n):
    return {f"docs/f{i:04d}.md": ("%040x" % i) for i in range(n)}


def test_paths_is_complete_when_truncated_is_falsy(ledger):
    """⭐⭐ PROPERTY 1. If the consumer sees a falsy `truncated`, the list it got is the WHOLE
    list — that is the condition under which it is allowed to act on it."""
    files = _many(30)
    out = _gap(ledger, [], files, ["check_invariants"], limit=200)
    step = next(s for s in out["steps"] if s["step"] == "check_invariants")

    assert not step["truncated"], "fixture must not exceed the cap"
    assert len(step["paths"]) == step["missing"], "paths was short while truncated said complete"


def test_truncated_is_the_exact_overflow_count(ledger):
    """⭐⭐ PROPERTY 2. Not a boolean, not an estimate — `missing == len(paths) + truncated`,
    so a caller can always tell exactly how much it is not being shown."""
    files = _many(50)
    out = _gap(ledger, [], files, ["check_invariants"], limit=20)
    step = next(s for s in out["steps"] if s["step"] == "check_invariants")

    assert len(step["paths"]) == 20
    assert step["truncated"] == step["missing"] - 20
    assert len(step["paths"]) + step["truncated"] == step["missing"]


def test_a_capped_answer_is_never_silently_complete(ledger):
    """⚠⚠ THE ONE THAT MATTERS TO THE DEPENDENT. A truncated list must NEVER present as a full
    one — that is precisely the shape ZeroParadox refuses to act on, and refusing requires that
    the flag actually fires."""
    files = _many(500)
    out = _gap(ledger, [], files, ["check_invariants"], limit=10)
    step = next(s for s in out["steps"] if s["step"] == "check_invariants")

    assert step["truncated"] > 0, "a capped list reported itself as complete"
    assert len(step["paths"]) < step["missing"]


def test_limit_zero_reports_everything_as_omitted(ledger):
    """⚠ `limit=0` is used internally (progress, heal_plan) to get counts without paths. It must
    report the FULL count as truncated rather than an empty list with nothing omitted — an empty
    `paths` with `truncated: 0` would read as "nothing owed"."""
    files = _many(40)
    out = _gap(ledger, [], files, ["check_invariants"], limit=0)
    step = next(s for s in out["steps"] if s["step"] == "check_invariants")

    assert step["paths"] == []
    assert step["truncated"] == step["missing"] == 40
