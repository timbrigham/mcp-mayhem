"""`complete: true` beside a non-empty `stale` must say which row was forgiven and why.

⛔⛔ THE MEASUREMENT IS TWO PEOPLE, NOT A PROBE, WHICH IS WHY IT COUNTS. On 2026-09-26 a tip row
rendered:

    required: 21   satisfied: 20   stale: ["copy_editor"]   complete: true   allowed: true

Every one of those five values was CORRECT. **Two readers who had each spent the day inside this
system independently concluded it was a fail-open on the push path, within an hour of each other.**
The ZeroParadox session filed it as a defect; this session CONFIRMED it to Tim before re-deriving,
while the comment explaining the divergence — `canpush.py`'s note that `inventory()` and
`can_push` answer `complete` differently, *"both correct under their own scoping"* — was open in
front of it.

⭐ THE BEHAVIOUR WAS RIGHT. Tim's 2026-09-18 ruling: a STALE row whose stale paths are untouched by
the range does not refuse it. In the case measured, `copy_editor` was stale while the range
published two `.json` files that match none of its scope globs AND sit under its `tools/*`
exclusion — zero in-scope paths by two independent routes.

⛔ THE RENDERING WAS INDEFENSIBLE, and that is this repository's founding rule broken by its own
output: **never report a number without naming what it prices.** `satisfied: 20` of `required: 21`
beside `complete: true`, with nothing saying which of the 21 was unsatisfied or why that was
allowed. Tim ruled: name the forgiveness on the row.

⚠ THE ROW STAYS STALE. `n_blocking_stale`'s own comment says a row that vanished from the stale
list would hide the backlog rather than grandfather it. This explains why it does not block; it
never says the step is fine.
"""

import json
import subprocess

import pytest

from core import canpush as canpush_mod
from test_can_push import _blob, _rec, _repo

STEP = "check_encoding"


def _check(ledger, tmp_path, rng, records, admission=(STEP,)):
    return canpush_mod.check(records=list(records), config=ledger.config, repo=str(tmp_path),
                             rev_range=rng, admission=list(admission),
                             commit_admission=list(admission))


def _repo_with_an_untouched_file(tmp_path):
    """A repo where `other.md` exists from the base and the RANGE touches only `doc.md`.

    ⛔⛔ THE SHARED `_repo` HELPER CANNOT PRODUCE THIS AND MY FIRST ATTEMPT SKIPPED BECAUSE OF IT.
    It rewrites `doc.md` at every commit, so every range publishes `doc.md` and nothing is ever
    out of range — the headline test reported `1 skipped`, which in a summary line is
    indistinguishable from a pass. That is the same defect caught in
    `test_a_repin_is_not_a_rule_change` hours earlier: **a precondition a test needs, it builds.**
    """
    import subprocess as sp
    sp.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    for a in (["config","user.email","t@t"], ["config","user.name","t"],
              ["config","commit.gpgsign","false"]):
        sp.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    def commit(name, body):
        (tmp_path / name).write_text(body, encoding="utf-8")
        sp.run(["git","add","-A"], cwd=tmp_path, check=True, capture_output=True)
        sp.run(["git","commit","-qm",name], cwd=tmp_path, check=True, capture_output=True)
        return sp.run(["git","rev-parse","HEAD"], cwd=tmp_path,
                      capture_output=True, text=True).stdout.strip()

    commit("other.md", "untouched by the range")      # exists, never touched again
    base = commit("doc.md", "base")
    tip = commit("doc.md", "tip")                     # the range touches ONLY doc.md
    return base, tip


def _scope(ledger, step, scope, exclude=()):
    """Point a step at paths, so a stale subject can be in or out of the published set."""
    types = ledger.config.required["types"]
    types[step] = dict(types.get(step) or {})
    types[step]["scope"] = list(scope)
    types[step]["scope_exclude"] = list(exclude)


def test_a_forgiven_row_names_itself_and_says_why(ledger, tmp_path):
    """⭐⭐ THE HEADLINE. A STALE row that does not block must appear in `stale_forgiven` with the
    reason attached, so `complete: true` beside `satisfied < required` is self-explaining at the
    point a reader meets it."""
    base, tip = _repo_with_an_untouched_file(tmp_path)
    # ⭐ STALE over `other.md` — a path that EXISTS but which this range does not publish.
    # The wrong blob makes the row STALE; `other.md` being untouched makes it out-of-range.
    records = [_rec(STEP, "other.md", "f" * 40, tip)]
    _scope(ledger, STEP, ["*.md"])

    result = _check(ledger, tmp_path, base + ".." + tip, records)
    tip_row = [r for r in result["commits"] if r["is_tip"]][0]

    assert tip_row.get("stale_forgiven"), (
        "the fixture produced no out-of-range stale row, so this probe proves nothing — "
        "a skip here would read like a pass. row=%r" % {k: tip_row.get(k) for k in
        ("stale", "complete", "required", "satisfied")})
    e = tip_row["stale_forgiven"][0]
    assert e["step"] == STEP
    # ⚠ the reason must explain the ARITHMETIC, since that is what was misread
    assert "not counted in `satisfied`" in e["why"] or "satisfied" in e["why"]
    assert "does not refuse THIS push" in e["why"]
    # ⛔ and it must NOT read as an all-clear — the step has still not judged those bytes
    assert "still stale" in e["why"].lower()
    # ⭐ the union is at the TOP of the payload, because that is where both readers looked
    assert STEP in result["stale_forgiven"]
    # ⚠ and the row is STILL listed as stale — forgiveness is not erasure
    assert STEP in tip_row["stale"]


def test_a_blocking_stale_row_is_not_listed_as_forgiven(ledger, tmp_path):
    """⛔⛔ THE CONTROL. Without it, `stale_forgiven` listing every stale row would satisfy the
    test above — and that is strictly worse than silence, because it would explain away a row
    that genuinely refuses the push."""
    base, shas = _repo(tmp_path, n=2)
    tip = shas[-1]
    # stale over a path the range DOES publish
    records = [_rec(STEP, "doc.md", "f" * 40, tip)]
    _scope(ledger, STEP, ["*"])          # everything in scope, so nothing is out of range

    result = _check(ledger, tmp_path, base + ".." + tip, records)
    tip_row = [r for r in result["commits"] if r["is_tip"]][0]
    forgiven = {e["step"] for e in (tip_row.get("stale_forgiven") or [])}
    if STEP in tip_row["stale"]:
        assert STEP not in forgiven, (
            "a STALE row that blocks this range was reported as forgiven — that is an "
            "explanation attached to the wrong fact, which is worse than none")
        assert tip_row["complete"] is False, (
            "a blocking stale row did not make the row incomplete")


def test_nothing_is_forgiven_when_nothing_is_stale(ledger, tmp_path):
    """⚠ ABSENCE IS NOT AN EXPLANATION. On a clean range the field must be empty rather than
    carrying a reassuring note about a condition that did not arise."""
    base, shas = _repo(tmp_path, n=2)
    tip = shas[-1]
    records = [_rec(STEP, "doc.md", _blob(tmp_path, tip, "doc.md"), tip)]
    result = _check(ledger, tmp_path, base + ".." + tip, records)
    assert result["stale_forgiven"] == []
    for r in result["commits"]:
        assert (r.get("stale_forgiven") or []) == []


def test_the_reason_does_not_claim_the_step_is_satisfied(ledger, tmp_path):
    """⛔ THE WORDING IS THE GUARD. A forgiveness that reads as a pass would convert a disclosure
    into the fail-open both readers thought they had found. The text must never say satisfied,
    passed, or fine about the step itself."""
    import re
    src = open("core/canpush.py", encoding="utf-8").read()
    i = src.find('"stale_forgiven": [')
    body = src[i:i + 1600]
    assert "still stale" in body, "the reason does not say the step remains stale"
    for bad in ("is satisfied", "has passed", "is fine", "no longer stale"):
        assert bad not in body, f"the forgiveness text claims {bad!r} about the step"
