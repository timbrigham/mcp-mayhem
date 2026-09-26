"""The arc-length freeze: a pin substitution moves enforcement and changes no rule.

⭐⭐ Tim, 2026-09-26: **"I think we should be freezing at the ends of the arcs."** And the number
that produced the ruling: SIX re-freezes in one day, every one from pin churn inside a single
review arc on a guard living in a pinned checker. Canonical length held at **27254 across all
six** and moved only on the one genuine policy change that day (**+846**). The instrument was
already separating the populations; it was not charging them differently.

⛔⛔ AND "JUST STOP RE-FREEZING" WAS NOT AVAILABLE — the ZeroParadox session's correction, and it
is right and it bites this ruling exactly as hard as the option it beat. `approved_modules` IS
enforcement and IS inside the scope digest by design. So freezing only at an arc's close, against
the SAME object, leaves a moved digest uncompared for the arc's whole length — which
`_cleared_2026_09_18` calls *reporting nothing* and judges worse than no bar at all.

⭐ SO THE MECHANISM IS A SECOND OBJECT, NOT A SUPPRESSED ALARM:

    registry_scope_digest   enforcement minus rationale            moves on pins AND rules
    registry_rule_digest    enforcement minus rationale minus pins moves on RULES only

The bar compares the rule digest. The scope digest is still computed and still SERVED, so pin
churn becomes a DISCLOSURE rather than a blocked bar — and never becomes invisible.

⚠ EITHER HALF ALONE IS A DEFECT, which is what the two tests at the bottom pin: the rule digest
alone is an exemption nobody can see; the scope digest alone is the bar that cried wolf six times
before lunch.
"""

import copy
import json

import pytest

from conftest import good, set_policy
from core import inventory
from core.config import Config, PIN_FIELDS, _digest_enforcement, _digest_rules

def _cfg(config_dir):
    return Config(policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


def _pinned_step(required):
    """A step that actually carries pins, so the probe changes something real.

    ⛔⛔ THIS USED TO `pytest.skip` AND THAT SILENTLY DISABLED SIX OF THE TEN TESTS IN THIS FILE.
    `required.v2.sample.json` carries NO `approved_modules` — the live registry does — so the
    first green run of this file was `4 passed, 6 skipped`, and a skip reads exactly like a pass
    in the summary line. **An assertion that never ran is indistinguishable from one that
    passed**, and six of them were the ones about pins.

    ⚠ So the state is CONSTRUCTED rather than looked for: `_pin` writes pins into the fixture
    and this asserts a floor. A test that needs a precondition either builds it or is not a test.
    """
    pinned = [n for n, s in (required.get("types") or {}).items() if s.get("approved_modules")]
    assert pinned, ("no pinned step — call `_pin(config_dir)` first; this file's whole subject "
                    "is what a repin does, so an unpinned fixture makes every probe vacuous")
    return pinned[0]


def _pin(config_dir, step=None, blobs=("a" * 40,)):
    """Give a step real pins ON DISK, and return its name. The precondition every probe needs."""
    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    step = step or sorted(doc["types"])[0]
    doc["types"][step]["approved_modules"] = list(blobs)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return step


# -- ⭐⭐ the property the whole ruling rests on --------------------------------

def test_a_repin_moves_enforcement_and_not_the_rules(config_dir):
    """⭐⭐ THE HEADLINE, AND IT IS TWO ASSERTIONS THAT MUST DISAGREE. If the repin moved both,
    the arc-length freeze is impossible; if it moved neither, the scope digest has stopped
    pricing enforcement and something worse is broken."""
    _pin(config_dir)
    cfg = _cfg(config_dir)
    victim = _pinned_step(cfg.required)
    scope_before, rule_before = cfg.registry_scope_digest, cfg.registry_rule_digest

    repinned = copy.deepcopy(cfg.required)
    repinned["types"][victim]["approved_modules"] = ["f" * 40]

    assert _digest_enforcement(repinned) != scope_before, (
        "a repin left the SCOPE digest unmoved — `approved_modules` is enforcement and the "
        "scope digest must still price it, or the disclosure has nothing to disclose")
    assert _digest_rules(repinned) == rule_before, (
        "a repin moved the RULE digest, so the arc-length freeze would break on pin churn — "
        "which is the six-re-freezes-in-a-day state the ruling exists to end")


def test_a_real_rule_change_moves_both(config_dir):
    """⛔⛔ THE CONTROL, AND WITHOUT IT THE TEST ABOVE IS SATISFIED BY A DIGEST OF NOTHING. A
    rule digest that never moves is not an exemption, it is a bar switched off."""
    _pin(config_dir)
    cfg = _cfg(config_dir)
    victim = _pinned_step(cfg.required)
    scope_before, rule_before = cfg.registry_scope_digest, cfg.registry_rule_digest

    widened = copy.deepcopy(cfg.required)
    widened["types"][victim]["scope"] = ["*.everything"]

    assert _digest_enforcement(widened) != scope_before
    assert _digest_rules(widened) != rule_before, (
        "a WIDENED SCOPE did not move the rule digest — the bar is now blind to the exact "
        "change a freeze exists to catch")


@pytest.mark.parametrize("field", PIN_FIELDS)
def test_every_pin_field_is_stripped_from_the_rule_digest(config_dir, field):
    """⚠ Parameterised over the constant rather than over a literal, so adding a pin field
    without teaching the stripper about it fails here instead of silently leaving it inside the
    arc-length object."""
    _pin(config_dir)
    cfg = _cfg(config_dir)
    victim = _pinned_step(cfg.required)
    mutated = copy.deepcopy(cfg.required)
    mutated["types"][victim][field] = ["deadbeef" * 5]
    assert _digest_rules(mutated) == cfg.registry_rule_digest, (
        f"{field!r} is in PIN_FIELDS but still moves the rule digest")


def test_a_pin_nested_in_a_list_is_stripped_too(config_dir):
    """⚠ `_strip_rationale` was unguarded through LISTS until 2026-09-25 and a pin nested in one
    would be the same hole reopened. Asserted rather than assumed, because the shape is
    identical and the earlier one shipped."""
    cfg = _cfg(config_dir)
    a = _digest_rules({"types": {"x": {"variants": [{"approved_modules": ["a" * 40]}]}}})
    b = _digest_rules({"types": {"x": {"variants": [{"approved_modules": ["b" * 40]}]}}})
    assert a == b, "a pin inside a list survived into the rule digest"


# -- ⛔ rationale stripping must not have regressed ----------------------------

def test_rationale_is_still_stripped_from_both(config_dir):
    """⚠ The new stripper composes with the old one; this pins that it did not replace it."""
    _pin(config_dir)
    cfg = _cfg(config_dir)
    documented = copy.deepcopy(cfg.required)
    documented["types"][_pinned_step(cfg.required)]["_why"] = "x" * 2000
    assert _digest_enforcement(documented) == cfg.registry_scope_digest
    assert _digest_rules(documented) == cfg.registry_rule_digest


# -- ⚠ the bar prefers the arc-length object and DISCLOSES the exemption -------

def test_the_bar_compares_the_rule_digest_when_one_is_frozen(config_dir):
    cfg = _cfg(config_dir)
    set_policy(config_dir, **{"convergence.frozen_rule_digest": cfg.registry_rule_digest})
    bar = inventory.convergence_bar(_cfg(config_dir))
    assert bar["basis"] == "rule_digest"
    assert bar["held"] is True
    # ⚠ both objects are served, always — the reader must never have to ask which moved
    assert bar["scope_digest"] and bar["rule_digest"]


def test_a_repin_holds_the_bar_and_says_the_exemption_is_active(config_dir):
    """⭐⭐ THE WHOLE POINT, END TO END: pins move, the bar stays GREEN, and the payload says
    out loud that it is excusing something."""
    _pin(config_dir)
    cfg = _cfg(config_dir)
    set_policy(config_dir, **{"convergence.frozen_rule_digest": cfg.registry_rule_digest,
                              "convergence.frozen_scope_digest": cfg.registry_scope_digest})
    # now repin, on disk, the way an in-arc review round does
    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["types"][_pinned_step(doc)]["approved_modules"] = ["e" * 40]
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    bar = inventory.convergence_bar(_cfg(config_dir))
    assert bar["held"] is True, "pin churn broke the arc-length bar"
    ex = bar["pin_exemption"]
    assert ex["active"] is True, "the exemption fired and the payload does not say so"
    assert ex["scope_digest_frozen_at"] != ex["scope_digest_now"], (
        "the disclosure claims an exemption while both scope digests agree")
    assert "approved_modules" in ex["what_it_excuses"]
    # ⛔ THE BOUND IS NAMED AS A HUMAN ACT, NOT ASSERTED AS ENFORCED. This server cannot observe
    # an arc boundary — the round counter is worktree-local and dies with the worktree — so a
    # days- or count-based cap here would be a control testing a proxy for the property.
    assert "CANNOT OBSERVE" in ex["bounded_by"]


def test_the_exemption_reads_inactive_when_nothing_moved(config_dir):
    """⛔⛔ THE MISSING HALF, AND MUTATION TESTING IS THE ONLY REASON IT EXISTS. Hardcoding
    `"active": True` passed all ten tests in this file — every probe asserted the field when it
    should be TRUE and none when it should be FALSE, so a flag that always said "I am excusing
    something" was indistinguishable from one that derived it.

    ⚠ AND THE DIRECTION IS WHY IT MATTERS RATHER THAN BEING TIDINESS: a permanently-active
    exemption reads as "pins are drifting" on a registry where nothing has moved, which trains
    its reader to ignore the one field whose whole job is to be noticed. The cry-wolf failure,
    one layer in from the bar it was built to keep quiet.
    """
    _pin(config_dir)
    cfg = _cfg(config_dir)
    set_policy(config_dir, **{"convergence.frozen_rule_digest": cfg.registry_rule_digest,
                              "convergence.frozen_scope_digest": cfg.registry_scope_digest})
    bar = inventory.convergence_bar(_cfg(config_dir))
    assert bar["held"] is True
    assert bar["pin_exemption"]["active"] is False, (
        "the exemption claims to be excusing a repin on a registry where NOTHING has moved")
    assert (bar["pin_exemption"]["scope_digest_frozen_at"]
            == bar["pin_exemption"]["scope_digest_now"]), (
        "the two scope digests disagree, so this probe is not testing the quiet state it claims")


def test_a_rule_change_still_breaks_the_bar(config_dir):
    """⛔ The exemption must not have widened into a general amnesty."""
    _pin(config_dir)
    cfg = _cfg(config_dir)
    set_policy(config_dir, **{"convergence.frozen_rule_digest": cfg.registry_rule_digest,
                              "convergence.frozen_scope_digest": cfg.registry_scope_digest})
    path = config_dir / "required.v2.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["types"][_pinned_step(doc)]["scope"] = ["*.everything"]
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    bar = inventory.convergence_bar(_cfg(config_dir))
    assert bar["held"] is False, "a widened scope did not break the arc-length bar"
    assert "THE BAR MOVED MID-RUN" in bar["note"]


def test_the_exemption_is_not_claimed_when_it_cannot_be_derived(config_dir):
    """⛔⛔ ABSENCE IS NEVER SUCCESS, APPLIED TO THE DISCLOSURE ITSELF. With only the rule digest
    frozen, a moved scope digest cannot be ATTRIBUTED to pins — it could be a rule change whose
    frozen baseline nobody stored. So the block must not render at all rather than assert an
    exemption it cannot establish."""
    cfg = _cfg(config_dir)
    set_policy(config_dir, **{"convergence.frozen_rule_digest": cfg.registry_rule_digest})
    bar = inventory.convergence_bar(_cfg(config_dir))
    assert "pin_exemption" not in bar, (
        "an exemption was claimed without a frozen scope digest to derive it from")


def test_the_legacy_and_scope_bases_still_work(config_dir):
    """⚠ Three stored objects now, and an older freeze must keep its own meaning rather than be
    reinterpreted as the new one — the `push_bar`/`registry_freeze` collision that hid a broken
    freeze for eleven days is the reason this is asserted and not assumed."""
    cfg = _cfg(config_dir)
    set_policy(config_dir, **{"convergence.frozen_scope_digest": cfg.registry_scope_digest})
    assert inventory.convergence_bar(_cfg(config_dir))["basis"] == "scope_digest"
