"""The TIP-GREEN bar: an intermediate's honest FAIL may publish, IF the tip fixed it.

⭐⭐ TIM'S DECISION, 2026-09-02, choosing between two stated options: *"the published tip is green
and every intermediate's defects are fixed within the same push"* — rather than *"every commit
individually green"*.

⚠⚠ THE SECOND CLAUSE IS A REAL CONDITION AND MOST OF THIS FILE EXISTS TO HOLD IT. "The tip is
green" ALONE would publish a broken intermediate whose defect was never fixed at all, which is
emphatically not what was authorised. What `tip_green` forgives is a FAIL or UNDECIDED whose
**indicted blobs are absent at the tip** — checkable only because `failing` made a FAIL say which
bytes it condemns (see `R-11` and `test_indictment_is_not_coverage.py`).

⭐ WHY THE OLD BAR HAD TO MOVE. `every_commit` cannot express the NORMAL shape of a remediation
arc: a real defect at commit N, fixed at commit M, both inside one push. ZeroParadox hit exactly
that on 2026-09-02 — two commits honestly carried an orphan checker — and under `every_commit`
that sixteen-commit range could never be pushed commit-by-commit-green. The only escape was
rewriting history, which is what `squash` does and which is remediation-only ON PRINCIPLE:
`can_push` justifies per-commit strictness on the grounds that intermediates are "fetchable,
bisectable, citable forever", so squashing satisfies the gate by DESTROYING what the gate protects.
"""

import subprocess

import pytest

from core import canpush as canpush_mod
from test_can_push import _blob, _check, _rec, _repo


STEP = "check_prose"
PATH = "doc.md"


def _fail_rec(path, blob, basis, failing=None, rid=None):
    """A FAIL over `path` at `blob`, indicting `failing` (default: everything it examined)."""
    rec = {"id": rid or f"{STEP}@{basis}#0", "step": STEP, "verdict": "FAIL", "revision": 0,
           "reason": "a real defect",
           "decided": {"how": "signature", "who": "t", "passes": 1, "agreed": 1},
           "subjects": [{"path": path, "git_blob_id": blob}],
           "basis": {"kind": "tree", "value": basis}}
    if failing is not None:
        rec["failing"] = failing
    return rec


# -- ⭐⭐ the headline: a fixed defect does not hold the range hostage ---------

def test_an_intermediate_fail_is_forgiven_when_the_tip_fixed_it(ledger, tmp_path):
    """⭐⭐ THE ARC THE OLD BAR COULD NOT EXPRESS. Commit 0 genuinely fails; commit 1 fixes it and
    passes. `doc.md` has different bytes at each, so the FAIL binds only the broken ones."""
    base, shas = _repo(tmp_path, n=2)
    broken, fixed = shas[0], shas[1]
    b0, b1 = _blob(tmp_path, broken, PATH), _blob(tmp_path, fixed, PATH)

    records = [_fail_rec(PATH, b0, broken, failing=[PATH]),
               _rec(STEP, PATH, b1, fixed)]
    result = _check(ledger, tmp_path, f"{base}..{fixed}", records=records)

    assert result["allowed"] is True, (
        f"a defect fixed inside the push still blocked it: {result.get('failed')}")
    assert result["forgiven_count"] == 1
    assert result["forgiven"][0]["commit"] == broken
    assert PATH in result["forgiven"][0]["indicted_and_fixed_by_tip"]


def test_a_defect_still_present_at_the_tip_blocks(ledger, tmp_path):
    """⛔⛔ THE CONDITION THAT MAKES THE BAR SAFE RATHER THAN A HOLE. If the indicted bytes are
    STILL THERE at the tip, nothing was fixed and the range must refuse. Without this clause
    `tip_green` would mean "the tip has a green row", which is not what was authorised."""
    base, shas = _repo(tmp_path, n=2)
    broken, tip = shas[0], shas[1]
    b_tip = _blob(tmp_path, tip, PATH)

    # ⚠ The FAIL indicts the TIP's OWN bytes — the defect was never fixed.
    records = [_fail_rec(PATH, b_tip, tip, failing=[PATH])]
    result = _check(ledger, tmp_path, f"{base}..{tip}", records=records)

    assert result["allowed"] is False, "a live defect at the tip was published"
    assert result["forgiven_count"] == 0


# -- ⚠ what the bar must NOT forgive -----------------------------------------

def test_missing_coverage_is_never_forgiven(ledger, tmp_path):
    """⚠⚠ 'WE NEVER LOOKED' IS NOT 'WE LOOKED, IT WAS BROKEN, WE FIXED IT.' Only the second is a
    defect a push can carry a fix for. Collapsing them would quietly turn this bar into "the tip
    is green" — the option Tim did NOT choose — and it is the single most likely way for this
    change to go wrong, because an uncovered commit and a fixed one both look like "not failing"."""
    base, shas = _repo(tmp_path, n=2)
    tip = shas[1]
    b_tip = _blob(tmp_path, tip, PATH)

    # only the tip is covered; the intermediate was never examined at all
    result = _check(ledger, tmp_path, f"{base}..{tip}",
                    records=[_rec(STEP, PATH, b_tip, tip)])

    assert result["allowed"] is False, "an unexamined intermediate was published"
    assert result["forgiven_count"] == 0
    assert shas[0] in [r["commit"] for r in result["commits"] if not r["complete"]]


def test_a_failing_tip_is_never_forgiven(ledger, tmp_path):
    """⛔ THE TIP IS THE PUBLISHED STATE AND CARRIES THE FULL BAR. Forgiveness applies to
    intermediates only — a tip excused by its own later fix is a contradiction, there being no
    later."""
    base, shas = _repo(tmp_path, n=1)
    tip = shas[0]
    b_tip = _blob(tmp_path, tip, PATH)

    result = _check(ledger, tmp_path, f"{base}..{tip}",
                    records=[_fail_rec(PATH, b_tip, tip, failing=[PATH])])

    assert result["allowed"] is False
    assert result["forgiven_count"] == 0


def test_a_wide_legacy_fail_is_not_forgiven_on_bytes_it_never_indicted(ledger, tmp_path):
    """⚠⚠ THE BACK-COMPAT CORNER, AND IT MUST FAIL CLOSED. A pre-`failing` FAIL indicts every
    subject it names. Here it names the TIP's bytes among them, so the defect is NOT fixed by the
    tip and the range must refuse — the forgiveness must be computed from what is actually
    indicted, never from the mere existence of a later PASS."""
    base, shas = _repo(tmp_path, n=2)
    broken, tip = shas[0], shas[1]
    b0, b1 = _blob(tmp_path, broken, PATH), _blob(tmp_path, tip, PATH)

    wide = _fail_rec(PATH, b0, broken)              # no `failing` -> all subjects indicted
    wide["subjects"].append({"path": PATH, "git_blob_id": b1})   # …including the tip's bytes
    result = _check(ledger, tmp_path, f"{base}..{tip}", records=[wide])

    assert result["allowed"] is False, "a FAIL indicting the tip's own bytes was forgiven"


# -- ⚠ the switch is data, and the strict direction is the safe one ----------

def test_the_bar_is_config_and_every_commit_still_refuses(ledger, tmp_path, config_dir):
    """⭐ THE BEHAVIOURAL PROOF THAT THE BAR IS DATA. Flip it to `every_commit` and the SAME
    records, the SAME range and the SAME fixed defect refuse again — no restart, no code edit."""
    from conftest import set_policy

    base, shas = _repo(tmp_path, n=2)
    broken, fixed = shas[0], shas[1]
    b0, b1 = _blob(tmp_path, broken, PATH), _blob(tmp_path, fixed, PATH)
    records = [_fail_rec(PATH, b0, broken, failing=[PATH]), _rec(STEP, PATH, b1, fixed)]

    # ⚠ A FRESH `Ledger`, because `config` is loaded in __init__ rather than per access. The
    # live re-read that means "no restart" happens at the SERVER, which builds a Ledger per call.
    from core.ledger import Ledger
    set_policy(config_dir, **{"push.bar": "every_commit"})
    led = Ledger(tmp_path / "p.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")
    result = canpush_mod.check(records=records, config=led.config, repo=str(tmp_path),
                               rev_range=f"{base}..{fixed}", admission=[STEP],
                               commit_admission=[STEP])
    assert result["allowed"] is False
    assert result["push_bar"] == "every_commit"


def test_an_unknown_bar_value_falls_back_to_the_stricter_one(ledger, tmp_path, config_dir):
    """⚠⚠ A TYPO MUST NOT WIDEN WHAT MAY BE PUBLISHED. `tip-green` with a hyphen, `TIPGREEN`,
    an empty string — every unrecognised value resolves to `every_commit`, because that is the
    safe direction to be wrong in. The opposite default would make a misspelling silently relax
    the gate, which is the reason-less-narrowing convention pointed at a policy key."""
    from conftest import set_policy

    for bad in ("tip-green", "TIPGREEN", "", "true"):
        from core.ledger import Ledger
        set_policy(config_dir, **{"push.bar": bad})
        led = Ledger(tmp_path / f"p{abs(hash(bad))}.jsonl",
                     policy_path=config_dir / "policy.v1.json",
                     required_path=config_dir / "required.v2.json")
        assert led.config.push_bar == "every_commit", f"{bad!r} widened the bar"


# -- ⚠ a forgiveness is never silent ------------------------------------------

def test_render_names_every_forgiven_commit(ledger, tmp_path):
    """⚠⚠ ALLOWED MUST NOT RENDER IDENTICALLY WHETHER THE RANGE WAS CLEAN OR MERELY FORGIVEN.
    That is the collapse-of-distinct-states this entire gate exists to prevent, and a weakening
    nobody can see in the output is one nobody will remember is in force."""
    base, shas = _repo(tmp_path, n=2)
    broken, fixed = shas[0], shas[1]
    b0, b1 = _blob(tmp_path, broken, PATH), _blob(tmp_path, fixed, PATH)
    records = [_fail_rec(PATH, b0, broken, failing=[PATH]), _rec(STEP, PATH, b1, fixed)]

    text = canpush_mod.render(_check(ledger, tmp_path, f"{base}..{fixed}", records=records))

    assert "FORGIVEN" in text
    assert broken[:12] in text
    assert STEP in text
