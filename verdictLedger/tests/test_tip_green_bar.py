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
from core.errors import ConfigError
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


# -- ⛔ a bar nobody configured is worth saying out loud -----------------------

def _config_without_push_bar(config_dir):
    """The shape that USED to be live: a policy that never names the bar. ZeroParadox's
    `tools/verify` policy had no `push` key, which is exactly why they could not find the
    mechanism. As of 2026-09-07 this shape no longer LOADS — see below."""
    import json
    path = config_dir / "policy.v1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("push", None)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def test_a_policy_that_never_names_the_bar_refuses_to_load(ledger, tmp_path, config_dir):
    """⭐⭐ WHAT THIS TEST USED TO ASSERT IS THE DEFECT IT NOW PREVENTS.

    Until 2026-09-07 it pinned the DISCLOSURE: an absent `push.bar` still ran, still returned
    `tip_green`, and merely SAID `push_bar_source == "default"`. That was the right first move —
    the bar had been invisible for three days, was "fixed" in the file only the tests load, and
    was found again a day later because the live server reads a different one. Disclosure made
    it findable.

    ⚠⚠ BUT DISCLOSURE LEFT THE LOOSE DIRECTION IN FORCE. Absent fell back to `tip_green` while a
    TYPO fell back to `every_commit` — so the more likely mistake got the more permissive
    treatment, and the only thing standing between a silent widening of what may be published
    and the world was whether somebody read a field. Tim, 2026-09-06: *"invisible defaults need
    to be visible.. and unless there's a damn good reason, they need to return an unknown
    value."*

    ⚠ A config failure is a SERVED state, not a crash — the process must not die into a restart
    loop the supervisor cannot fix. The error is held and every gated action refuses with it.
    """
    from core.ledger import Ledger

    assert ledger.config.push_bar_source == "policy", "the shipped test config names the bar"

    _config_without_push_bar(config_dir)
    led = Ledger(tmp_path / "p2.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")

    assert led.config is None, "an unnamed bar must refuse the config, not default quietly"
    assert "push.bar" in led.config_error, "the refusal must name the key"
    # ⚠ `_require_config()` fires before the record is even looked at, so an empty dict is
    # enough — the point is that the REFUSAL comes from the config, not from the record.
    with pytest.raises(ConfigError):
        led.validate({})


def test_the_refusal_names_the_value_that_restores_todays_behaviour(tmp_path, config_dir):
    """⭐⭐ `UsageError(what, satisfied_when)` — A REFUSAL NAMES THE SUCCESS CONDITION.

    The repo's test for this is: could a reader construct a passing next attempt from the
    success condition ALONE, with the complaint deleted? So the message must carry the literal
    value, not merely "set push.bar". Anyone hitting this is mid-outage on a server that is
    refusing every gated action, which is the worst moment to make them go reading source to
    learn that `tip_green` was what they were already running under.
    """
    from core.ledger import Ledger

    _config_without_push_bar(config_dir)
    led = Ledger(tmp_path / "p3.jsonl", policy_path=config_dir / "policy.v1.json",
                 required_path=config_dir / "required.v2.json")

    assert "tip_green" in led.config_error, (
        "the refusal must name the value that keeps behaviour identical — a reader must be "
        "able to write the fix from the message without knowing what the built-in was")
    assert "PERMISSIVE" in led.config_error, (
        "and must say WHY absence is a defect: the fallback bought the looser rule")


def test_a_strict_default_is_NOT_made_fatal(tmp_path, config_dir):
    """⛔⛔ THE ASYMMETRY, PINNED — the control for the two tests above.

    Three keys were disclosed as running on built-ins and only TWO were made fatal. The
    discriminator is not "was it defaulted" but WHICH DIRECTION the default errs:

        push.bar                        absent -> tip_green   PERMISSIVE   refuse
        coverage.require_complete       absent -> False       PERMISSIVE   refuse
        migration.v16_evidence_required absent -> True        STRICT       ALLOW

    Deleting the V16 key is how the cutover ENDS. `test_deleting_the_key_re_arms_the_rule` pins
    that removal RE-ARMS the rule, and `test_the_shipped_policy_relaxes_nothing` pins that the
    shipped policy carries no `migration` block at all — so requiring it would force a live
    relaxation block back into every policy file, which is the exact thing that test exists to
    prevent. Absence is a defect only where absence is the loose direction.
    """
    import json
    from core.ledger import Ledger

    path = config_dir / "policy.v1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("migration", None)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    led = Ledger(tmp_path / "p4.jsonl", policy_path=path,
                 required_path=config_dir / "required.v2.json")

    assert led.config is not None, (
        "a STRICT default must still load — making it fatal would force a `migration` block "
        "into every policy file and convert a safe terminal absence into an outage")
    assert led.config.v16_required is True, "and absent must still mean strict"


# -- ⛔ a refused claim is never forgiven, and absent refusals claim nothing ---------

OTHER = "check_encoding"          # scope `*`, so it covers doc.md at every commit
_REFUSED = {OTHER: {"rule": "V11", "count": 1, "first_seen": "2026-09-13T00:00:00+00:00",
                    "last_seen": "2026-09-13T00:00:00+00:00"}}


def _fixed_fail_plus_refused(tmp_path):
    """Commit 0 honestly FAILs `check_prose`, and the tip fixes it. OTHER is in the COMMIT set
    only, so it binds commit 0 and not the tip, and it has NO accepted record anywhere.

    ⚠ Not in the tip's set, on purpose. A PASS for OTHER at the tip covers doc.md at a
    different blob, which makes commit 0 read STALE, and REFUSED only renders over a row with
    nothing covered and nothing stale. The first draft of this fixture did that and the
    controls failed for a reason unrelated to what they name."""
    base, shas = _repo(tmp_path, n=2)
    broken, fixed = shas[0], shas[1]
    b0, b1 = _blob(tmp_path, broken, PATH), _blob(tmp_path, fixed, PATH)
    records = [_fail_rec(PATH, b0, broken, failing=[PATH]),
               _rec(STEP, PATH, b1, fixed)]
    return base, broken, fixed, records


def test_a_refused_step_is_never_forgiven_under_tip_green(ledger, tmp_path):
    """⛔⛔ A FIXED FAIL MUST NOT CARRY A REFUSED CLAIM OUT WITH IT.

    Until 2026-09-13 a refused step read MISSING in `can_push` and blocked for that reason.
    Once `refusals` reached this function the step got its own status, and the forgiveness
    clause checked only missing/stale/legacy. So commit 0 here, with a fixed FAIL plus a claim
    the ledger never accepted, would have been forgiven. "We never looked" is not "we looked,
    it was broken, we fixed it", whatever it is called."""
    base, broken, fixed, records = _fixed_fail_plus_refused(tmp_path)
    result = _check(ledger, tmp_path, f"{base}..{fixed}", records=records,
                    admission=(STEP,), commit_admission=(STEP, OTHER), refusals=_REFUSED)

    row = next(r for r in result["commits"] if r["commit"] == broken)
    assert row["refused"] == [OTHER] and row["missing"] == []
    assert row["failed"] == [STEP]
    assert result["allowed"] is False, "a refused claim was forgiven with a fixed FAIL"
    assert result["forgiven_count"] == 0
    assert result["refused"] == [OTHER]


def test_the_refused_remedy_on_the_push_path_is_not_run_the_step(ledger, tmp_path):
    """MISSING says run it. REFUSED says running it again reproduces the refusal. The union
    line has to give the second remedy, or the refusal renders as a claim never made."""
    base, broken, fixed, records = _fixed_fail_plus_refused(tmp_path)
    text = canpush_mod.render(_check(ledger, tmp_path, f"{base}..{fixed}", records=records,
                                     admission=(STEP,), commit_admission=(STEP, OTHER), refusals=_REFUSED))
    refused_line = next(ln for ln in text.splitlines() if ln.strip().startswith("REFUSED CLAIM"))
    assert OTHER in refused_line and "re-running reproduces" in refused_line
    assert not any(ln.strip().startswith("MISSING") and OTHER in ln
                   for ln in text.splitlines())


def test_without_refusals_no_refused_key_is_emitted(ledger, tmp_path):
    """⚠ ABSENT, NOT EMPTY. The MCP server does not pass the sidecar (see `_sync_can_push`),
    so a `refused: []` there would claim "nothing was refused" about a file nobody read. The
    same range still blocks, reading MISSING as it always has."""
    base, broken, fixed, records = _fixed_fail_plus_refused(tmp_path)
    result = _check(ledger, tmp_path, f"{base}..{fixed}", records=records,
                    admission=(STEP,), commit_admission=(STEP, OTHER))

    assert "refused" not in result
    assert all("refused" not in r for r in result["commits"])
    row = next(r for r in result["commits"] if r["commit"] == broken)
    assert row["missing"] == [OTHER]
    assert result["allowed"] is False


def test_the_can_push_cli_runs(tmp_path):
    """⛔ `zpledger can-push` RAISED TypeError ON EVERY CALL FROM 2026-09-07 TO 2026-09-13.
    5ebd805 passed `refusals=` to `canpush.check`, whose signature did not take it, and no
    test ever ran the CLI. Reproduced before the fix:
    `TypeError: check() got an unexpected keyword argument 'refusals'`."""
    import sys
    from pathlib import Path
    base, shas = _repo(tmp_path / "r", n=1)
    data = tmp_path / "records.jsonl"
    data.write_text("", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "core.cli", "--data", str(data), "--repo", str(tmp_path / "r"),
         "can-push", f"{base}..{shas[0]}", "--admit", STEP],
        cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    assert "Traceback" not in proc.stderr, proc.stderr[-800:]
    assert "push" in proc.stdout
