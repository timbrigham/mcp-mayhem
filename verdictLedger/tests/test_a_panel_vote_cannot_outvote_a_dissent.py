"""V23 — a voted panel, and the reason a majority cannot silence the minority.

⭐⭐ Tim's question, 2026-09-27, and it is the right one: *"what the hell do you do with the
failure? We talked about re-ruling until there was agreement… and how that would possibly be used
to silence a dissentant statement… how the hell are you supposed to represent that without me
involved in the loop as the human?"*

⛔⛔ THE ANSWER IS NOT IN V23. IT IS IN V18, AND IT ALREADY WORKED. `SEVERITY_ON_A_PASS` is
`("ordinary",)`, so:

    dissent graded ordinary   ->  rides on the PASS in `outstanding`, counted and attributed
    dissent graded bedrock    ->  V18 REFUSES THE PASS. The record cannot be written.
    dissent graded blocking   ->  same refusal
    dissent graded anything    ->  same refusal, because an unrecognised severity must not sail
    the rule has not heard of      through on the assumption that it is minor

**So the threshold only ever decides ORDINARY matters. A serious dissent is not outvoted — it
makes a passing record unrepresentable, whatever the tally says.** The human is in the loop exactly
when there is a real dispute and not otherwise, which is what was being asked for.

⚠⚠ AND THAT IS SAFE ONLY WHILE FINDINGS UNION ACROSS READERS AND ONLY THE VERDICT IS VOTED. The
consumer's brief states it — *"Findings UNION across all three so a lone reader who catches a
meaning shift is never outvoted; only the VERDICT is voted, 2-of-3"* — and **this server cannot
enforce it**: it sees what a record carries, never how many readers found what. A panel that voted
on FINDINGS would drop the third reader's bedrock finding and so produce a record V18 would have
refused, by discarding the thing that would have refused it. An emitter obligation, said out loud
rather than implied to be checked.

⚠ THE ONE HOLE, IN V18's OWN WORDS: *"Nothing here can detect a DEFLATED finding."* A bedrock
dissent relabelled `ordinary` passes. What the system gives instead is attribution — `who`, and
`evidence` naming the brief — so a later reader sees who called it ordinary and under which
instructions. Forensic, not preventive.

⭐ AND THE GAP V23 FILLS HAD BEEN NAMED AND DEFERRED SINCE 2026-09-08:
`copy_editor._module_why` recorded the tension between a 2-of-3 brief and V3's unanimity
"unresolved on purpose", on the stated condition that `copy_editor` was "admitted by nothing so
nothing is gated on the answer". Admitting it at push expired that condition, and the first real
panel run split 2-of-3 with no honest shape to record.
"""

import pytest

from conftest import good

STEP = "check_invariants"
BRIEF = [{"path": ".claude/commands/copy-editor.md", "git_blob_id": "c" * 40}]


def _panel(ledger, *, verdict="PASS", passes=3, agreed=2, threshold=2,
           who="copy_editor panel (3 readers)", evidence=None, **over):
    rec = good(verdict=verdict,
               evidence=BRIEF if evidence is None else evidence,
               decided={"how": "panel", "passes": passes, "agreed": agreed,
                        "threshold": threshold, "who": who},
               **over)
    return ledger.validate(rec)["errors"]


def _v23(errs):
    return [e for e in errs if e.startswith("V23")]


# -- ⭐⭐ the safety property the whole design rests on -------------------------

@pytest.mark.parametrize("severity,accepted", [
    ("ordinary", True),
    ("bedrock", False),
    ("blocking", False),
    ("severe", False),          # a word the rule has never heard of must NOT sail through
])
def test_a_majority_cannot_pass_over_a_serious_dissent(ledger, severity, accepted):
    """⭐⭐ THE HEADLINE, AND IT IS THE ANSWER TO THE QUESTION THAT PROMPTED V23. A 2-of-3 panel
    carrying the third reader's finding: ordinary rides along, anything worse refuses the PASS."""
    errs = _panel(ledger, outstanding=[{"severity": severity,
                                        "note": "the third reader's dissent",
                                        "path": "docs/x.md"}])
    if accepted:
        assert errs == [], (
            f"an ORDINARY dissent must ride on the PASS — that is how a finding survives a vote "
            f"without a human: {errs}")
    else:
        assert any(e.startswith("V18") for e in errs), (
            f"a {severity!r} dissent did NOT refuse the PASS, so a 2-of-3 majority just voted "
            f"away a serious finding. This is the silencing mechanism the whole design exists to "
            f"prevent. errors={errs}")


def test_the_split_itself_is_recordable_and_blocks(ledger):
    """⭐ A SPLIT BELOW THRESHOLD IS NOT A DEAD END. It records honestly as UNDECIDED, blocks, and
    carries `failing` naming the disputed subset — and a human may then accept it with `sign`.
    That is the route, and V23's refusal text names it so nobody reaches for a re-run."""
    # ⭐ AND V6 MAKES THE SPLIT EXPLAIN ITSELF, which is the other half of not silencing a dissent:
    # an UNDECIDED requires a non-empty `reason`, so a panel cannot record "we disagreed" without
    # saying about what. The first version of this test omitted it and V6 correctly refused.
    assert _panel(ledger, verdict="UNDECIDED", agreed=1, failing=["docs/x.md"],
                  reason="2 of 3 read the rewrite as meaning-preserving; the third held that "
                         "the modal claim weakened. Disputed line named in failing.") == []
    errs = _panel(ledger, verdict="PASS", agreed=1)
    assert _v23(errs), "a PASS below its own threshold was accepted"
    assert "UNDECIDED" in _v23(errs)[0], (
        "the refusal does not name the representable alternative, so a caller is left with "
        "re-running until uniform — which re-rolls until the dissenter is gone")


# -- ⛔ a panel of one is a single agent wearing a badge ------------------------

def test_a_threshold_of_one_is_refused(ledger):
    """⛔⛔ THE V3 LESSON, CARRIED FORWARD. A threshold of 1 is a single-pass verdict wearing a
    consensus badge — exactly what V3 refuses for `agreement` — and a panel whose divergence
    signal cannot exist is not a panel. The floor is policy's, defaulting to 2."""
    errs = _v23(_panel(ledger, passes=1, agreed=1, threshold=1))
    assert errs and "SINGLE AGENT" in errs[0]


def test_the_floor_defaults_safe_when_policy_is_silent(ledger):
    """⭐ AN ABSENT `policy.panel` BLOCK MUST NOT MEAN A FLOOR OF 1. The unconfigured case trips
    rather than passes — the same choice `_strip_rationale` makes with a denylist."""
    assert "panel" not in (ledger.config.policy or {}), (
        "this fixture now configures a panel block, so it no longer tests the default")
    assert ledger.config.panel_min_threshold == 2


def test_policy_may_tighten_the_floor_and_may_not_open_it(ledger, config_dir):
    """⛔ POLICY MAY RAISE THE BAR AND MAY NOT LOWER IT BELOW THE VALUE'S PURPOSE. A configured 1
    is refused as firmly as an absent block: the key exists to close that hole, so it must not be
    the way to open it."""
    from conftest import set_policy
    from core.config import Config
    set_policy(config_dir, **{"panel.min_threshold": 3})
    tighter = Config(policy_path=config_dir / "policy.v1.json",
                     required_path=config_dir / "required.v2.json")
    assert tighter.panel_min_threshold == 3
    set_policy(config_dir, **{"panel.min_threshold": 1})
    opened = Config(policy_path=config_dir / "policy.v1.json",
                    required_path=config_dir / "required.v2.json")
    assert opened.panel_min_threshold == 2, "policy opened the hole the floor exists to close"


# -- ⚠ the tally must be internally honest -------------------------------------

def test_more_agreed_than_ran_is_refused(ledger):
    assert _v23(_panel(ledger, passes=2, agreed=3, threshold=2))


def test_a_threshold_above_the_readers_who_ran_is_refused(ledger):
    """⚠ A verdict cannot claim more agreement than there were readers to give it."""
    assert _v23(_panel(ledger, passes=2, agreed=2, threshold=3))


def test_a_panel_must_name_itself(ledger):
    """⚠ A tally with nobody attached is a number without a claimant — `delegated`'s argument."""
    assert _v23(_panel(ledger, who="   "))


def test_a_panel_pass_must_name_the_brief(ledger):
    """⭐ SAME REQUIREMENT AS V17's DELEGATED PASS, FOR THE SAME REASON AND NOT BY ANALOGY: naming
    the brief's blob is what makes the verdict EXPIRE when the brief is edited — the key goes stale
    and the panel re-runs. A verdict that outlives its instructions is what this buys."""
    errs = _v23(_panel(ledger, evidence=[]))
    assert errs and "expire when the brief changes" in errs[0]


# -- ⛔⛔ agreement is untouched, which was the whole point ---------------------

def test_agreement_still_means_unanimous(ledger):
    """⛔⛔ THE REASON THIS IS A NEW VALUE RATHER THAN A RELAXED V3. 291 stored `agreement` records
    assert unanimity; relaxing V3 to price a threshold would retroactively change what every one of
    them MEANS, with no way for a reader to tell which kind they were looking at. That is the
    two-meanings-one-value defect the exit-code section forbids."""
    errs = ledger.validate(good(verdict="PASS",
                                decided={"how": "agreement", "passes": 3, "agreed": 2,
                                         "who": "panel"}))["errors"]
    assert any(e.startswith("V3") for e in errs), (
        "a non-unanimous `agreement` PASS was accepted — V3 was relaxed, and every historical "
        "agreement record just changed meaning")
