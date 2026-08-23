"""V1–V13, each with a probe that must turn the validator RED.

⚠ V14 (deterministic `reason`) IS RETIRED. It existed only to keep an input
to a per-record hash stable; with the key reduced to (step, basis, revision)
the hash is gone and the rule it needed goes with it.

⚠ THE CONTROLS ARE THE DELIVERABLE, NOT THE AFTERTHOUGHT. Every probe here changes
exactly ONE thing about a record that otherwise passes, so a red result can only
mean the rule fired. The neuter control at the bottom proves that: stub the
validator to return ok unconditionally and every probe must go red. Any probe that
stays green was testing a proxy rather than the rule.
"""

import json

import pytest

from conftest import good, set_policy
from core.errors import ValidationFailure
from core.ledger import Ledger


def errs(ledger, record):
    return ledger.validate(record)["errors"]


def rule(ledger, record, tag):
    """Assert the named rule fired, and report what did fire when it did not."""
    found = errs(ledger, record)
    assert any(e.startswith(tag) for e in found), f"{tag} did not fire; got {found}"
    return found


def test_a_good_record_passes(ledger):
    """The baseline. If this ever fails, every probe below is meaningless."""
    assert errs(ledger, good()) == []


# -- V1: a silent fallback to a permissive basis (FRZ-4) ----------------------

def test_v1_basis_resolution_must_be_stated(ledger):
    rule(ledger, good(basis={"kind": "tree", "value": "a" * 40,
                             "resolved_from": None}), "V1")


def test_v1_fallback_is_legal_but_recorded(ledger):
    """FALLBACK is allowed — the point is that it is VISIBLE, not forbidden."""
    assert errs(ledger, good(basis={"kind": "tree", "value": "a" * 40,
                                    "resolved_from": "FALLBACK"})) == []


# -- V2: warrant-satisfied-while-empty, five measured instances ---------------

def test_v2_pass_with_no_subjects(ledger):
    rule(ledger, good(subjects=[]), "V2")


def test_v2_a_fail_may_have_no_subjects(ledger):
    """Only a PASS is forbidden from examining nothing — a FAIL that could not
    even enumerate its inputs is a legitimate thing to report."""
    assert not any(e.startswith("V2") for e in
                   errs(ledger, good(verdict="FAIL", subjects=[], reason="could not enumerate")))


# -- V3: fake unanimity, and the threshold is CONFIG --------------------------

def test_v3_agreement_needs_unanimity(ledger):
    rule(ledger, good(decided={"how": "agreement", "passes": 3, "agreed": 2, "who": None}), "V3")


def test_v3_agreement_needs_enough_passes(ledger):
    rule(ledger, good(decided={"how": "agreement", "passes": 1, "agreed": 1, "who": None}), "V3")


def test_v3_threshold_is_data_not_a_constant(tmp_path, config_dir):
    """⭐ THE CONTROL THAT PROVES CONFIG IS CONFIG: change the number, restart
    nothing, and watch the same record change verdict."""
    rec = good(decided={"how": "agreement", "passes": 2, "agreed": 2, "who": None})

    strict = Ledger(tmp_path / "a.jsonl", policy_path=config_dir / "policy.v1.json",
                    required_path=config_dir / "required.v2.json")
    assert any(e.startswith("V3") for e in strict.validate(rec)["errors"])

    set_policy(config_dir, **{"agreement.min_passes": 2})
    relaxed = Ledger(tmp_path / "b.jsonl", policy_path=config_dir / "policy.v1.json",
                     required_path=config_dir / "required.v2.json")
    assert not any(e.startswith("V3") for e in relaxed.validate(rec)["errors"])


# -- V4: an aggregate claiming a pass over steps that never ran ---------------

def test_v4_inputs_must_already_exist(ledger):
    rule(ledger, good(inputs=["deadbeef"]), "V4")


def test_v4_leaf_steps_have_empty_inputs(ledger):
    """Checks are INDEPENDENT — `inputs` is the seam between stages, not a link
    within one. A leaf step consuming a predecessor would be a design error."""
    assert errs(ledger, good(inputs=[])) == []


# -- V5 / V6 -------------------------------------------------------------------

def test_v5_signature_needs_who(ledger):
    rule(ledger, good(decided={"how": "signature", "passes": 1, "agreed": 1, "who": None},
                      tier="H"), "V5")


@pytest.mark.parametrize("verdict", ["FAIL", "UNDECIDED"])
def test_v6_a_block_needs_a_reason(ledger, verdict):
    rule(ledger, good(verdict=verdict, reason=None), "V6")


# -- V7: a step inventing a field to smuggle state past the schema ------------

def test_v7_unknown_keys_are_rejected_not_ignored(ledger):
    rule(ledger, good(sneaky_override=True), "V7")


# -- V8: 'prose' and 'check_prose' silently becoming two steps ----------------

def test_v8_unregistered_step_cannot_record(ledger):
    """⭐ The pair that closes the hole: you cannot add a check that silently does
    not count, and you cannot register one that silently is not required."""
    rule(ledger, good(step="check_prosee"), "V8")


# -- V9 / V10 ------------------------------------------------------------------

def test_v9_run_id_is_required(ledger):
    rule(ledger, good(run={"id": "", "started": None, "policy_sha": None, "env": {}}), "V9")


def test_v10_policy_sha_must_name_a_known_policy(ledger):
    rule(ledger, good(run={"id": "r", "started": None,
                           "policy_sha": "0" * 64, "env": {}}), "V10")


def test_v10_current_policy_is_accepted(ledger):
    """The ledger stamps its own sha when the caller omits it."""
    assert ledger.append(good())["appended"] is True


# -- V11 / V13: branching and endless regrading, scoped to one basis ----------

def test_v11_branching_is_unrepresentable(ledger):
    ledger.append(good())
    ledger.append(good(revision=1, verdict="FAIL", reason="regraded"))
    # a second revision 1 for the same (step, basis) is the branch
    rule(ledger, good(revision=1, verdict="PASS", reason="different regrade"), "V11")


def test_v11_a_revision_needs_its_predecessor_at_this_basis(ledger):
    rule(ledger, good(revision=2, verdict="FAIL", reason="skipped a step"), "V11")


def test_v11_a_chain_never_crosses_bases(ledger):
    """⭐ An accepted FAIL can never be carried forward onto content it was not
    about — STALE enforced in the identity rather than checked afterwards."""
    ledger.append(good())
    ledger.append(good(revision=1, verdict="FAIL", reason="regraded"))
    other = good(basis={"kind": "tree", "value": "c" * 40, "resolved_from": "explicit"},
                 revision=1, verdict="FAIL", reason="carried forward")
    rule(ledger, other, "V11")


def test_v13_depth_cap_and_it_is_config(ledger, tmp_path, config_dir):
    deep = good(revision=6, verdict="FAIL", reason="regraded to death")
    assert any(e.startswith("V13") for e in ledger.validate(deep)["errors"])

    set_policy(config_dir, **{"supersede.max_depth": 9})
    raised = Ledger(tmp_path / "c.jsonl", policy_path=config_dir / "policy.v1.json",
                    required_path=config_dir / "required.v2.json")
    assert not any(e.startswith("V13") for e in raised.validate(deep)["errors"])


# -- V12: "sudo it away by declaring it a false positive" ---------------------

def test_v12_cannot_override_your_own_prior_decision(ledger):
    base = {"kind": "tree", "value": "a" * 40, "resolved_from": "explicit"}
    subj = [{"git_blob_id": "b" * 40, "path": "docs/x.md"}]
    ledger.sign(step="check_paths", subjects=subj, who="tim",
                reason="accepted as known debt", basis=base)
    with pytest.raises(ValidationFailure) as exc:
        ledger.override(step="check_paths", subjects=subj, who="tim",
                        reason="actually a false positive", basis=base)
    assert any(e.startswith("V12") for e in exc.value.violations)


def test_v12_a_different_person_may_override(ledger):
    base = {"kind": "tree", "value": "a" * 40, "resolved_from": "explicit"}
    subj = [{"git_blob_id": "b" * 40, "path": "docs/x.md"}]
    ledger.sign(step="check_paths", subjects=subj, who="tim",
                reason="accepted as known debt", basis=base)
    out = ledger.override(step="check_paths", subjects=subj, who="reviewer-2",
                          reason="the gate was wrong", basis=base)
    assert out["appended"] is True


# -- ⭐ ONE HASH, AND IT IS GIT'S ---------------------------------------------

def test_the_key_is_readable_and_carries_no_second_hash(ledger):
    """The record key is `step@basis#revision` — a composite of things that
    already exist, not a digest over a description of them.

    ⚠ V14 (deterministic `reason`) was RETIRED with the hash it protected. Prose
    is payload now, free to say whatever is most useful to a human.
    """
    out = ledger.append(good(verdict="FAIL", reason="check took 1.4s on host xyz"))
    assert out["appended"] is True
    assert out["id"] == f"check_paths@{'a' * 40}#0"


@pytest.mark.parametrize("reason", [
    "check took 1.4s", "failed at 2026-08-22T20:58:13Z",
    "worker pid: 4821 died", "wrote /tmp/abc123def/out.txt",
])
def test_a_nondeterministic_reason_is_now_fine(ledger, reason):
    """Every one of these was refused while `reason` fed a digest. The rule was
    solving a problem the hash created."""
    assert errs(ledger, good(verdict="FAIL", reason=reason)) == []


def test_the_only_hash_in_a_record_is_gits(ledger):
    """basis.value is a git object hash and subjects carry git blob hashes. The
    ledger contributes none of its own."""
    ledger.append(good())
    rec = ledger.store.records()[0]
    assert rec["id"] == f"check_paths@{'a' * 40}#0"
    assert len(rec["id"]) < 64, "an opaque digest would have crept back in"


def test_an_ambiguous_basis_is_refused_rather_than_escaped(ledger):
    """Git permits '#' in a ref name. Refusing costs a rename; escaping would
    reintroduce the encoding contract the digest needed."""
    bad = good(basis={"kind": "ref", "value": "feature#7", "resolved_from": "explicit"})
    assert any("ambiguous" in e for e in errs(ledger, bad))


# -- ⭐ THE NEUTER CONTROL ------------------------------------------------------

def test_neuter_control_every_probe_depends_on_the_rules(ledger, monkeypatch):
    """Stub the rule engine to return nothing and assert every probe above would
    now PASS. Any record that still fails was being caught by something other than
    the rule its test names — i.e. that probe tests a proxy.

    ⚠ This is the control that distinguishes "the check fired" from "the check
    prevented", which is the gap LOCK-1 was about one project over.
    """
    from core import validate as validate_mod

    probes = [
        good(basis={"kind": "tree", "value": "a" * 40, "resolved_from": None}),
        good(subjects=[]),
        good(decided={"how": "agreement", "passes": 1, "agreed": 1, "who": None}),
        good(inputs=["deadbeef"]),
        good(decided={"how": "signature", "passes": 1, "agreed": 1, "who": None}),
        good(verdict="FAIL", reason=None),
        good(step="check_prosee"),
        good(run={"id": "", "started": None, "policy_sha": None, "env": {}}),
        good(revision=6, verdict="FAIL", reason="deep"),
    ]
    for p in probes:
        assert errs(ledger, p), "a probe was already green before neutering"

    monkeypatch.setattr(validate_mod, "rules", lambda *a, **k: [])
    for p in probes:
        remaining = [e for e in errs(ledger, p) if not e.startswith("V7")]
        # V7 is structural (an unknown key cannot be rule-checked, only rejected),
        # so it survives neutering by design; everything else must go green.
        assert remaining == [], (
            f"probe still red with the rules neutered: {remaining} — it was "
            f"testing a proxy, not the rule")


# -- ⭐ V15: a subject set is everything the verdict DEPENDS ON ---------------

def _switched(config_dir, tmp_path, switches=("tools/verify/prose_baseline.txt",)):
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"]["check_prose"] = {"family": "mechanical", "switches": list(switches)}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    return Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


def test_v15_a_record_omitting_its_switch_is_refused(tmp_path, config_dir):
    """⭐⭐ FOUND BY ZEROPARADOX 2026-08-23. `check_pov` recorded 291 subjects and NOT
    `pov_baseline.txt`. Grandfather a new violation into that baseline and the record
    still reads SATISFIED, because every file it names is unchanged. The verdict
    changed; the record could not tell.

    That is the exemption-switch fail-open arriving through the SUBJECT LIST rather
    than through the gate — and it was a hole already, with no optimisation in play.
    It becomes far worse under a skip-if-unchanged hook: the checker never re-runs, so
    the suppression lands unverified.
    """
    led = _switched(config_dir, tmp_path)
    with pytest.raises(ValidationFailure) as exc:
        led.append(good(step="check_prose",
                        subjects=[{"git_blob_id": "b" * 40, "path": "docs/x.md"}]))
    assert "V15" in str(exc.value)
    assert "prose_baseline.txt" in str(exc.value)


def test_v15_naming_the_switch_validates(tmp_path, config_dir):
    led = _switched(config_dir, tmp_path)
    out = led.append(good(
        step="check_prose",
        subjects=[{"git_blob_id": "b" * 40, "path": "docs/x.md"},
                  {"git_blob_id": "c" * 40, "path": "tools/verify/prose_baseline.txt"}]))
    assert out["id"].startswith("check_prose@")


def test_v15_makes_editing_a_baseline_go_STALE(tmp_path, config_dir):
    """⭐ THE POINT OF THE RULE, not just its refusal. With the switch as a subject,
    editing the baseline moves a blob the record NAMES — so the key goes stale and the
    checker re-runs. The dependency becomes mechanical instead of remembered."""
    from core import inventory as inventory_mod
    led = _switched(config_dir, tmp_path)
    led.append(good(
        step="check_prose",
        subjects=[{"git_blob_id": "b" * 40, "path": "docs/x.md"},
                  {"git_blob_id": "c" * 40, "path": "tools/verify/prose_baseline.txt"}]))
    recs = led.store.records()

    before = inventory_mod.build(
        config=led.config, records=recs, action="commit",
        files={"docs/x.md": "b" * 40, "tools/verify/prose_baseline.txt": "c" * 40},
        ref="t", admission=["check_prose"])
    after = inventory_mod.build(          # the baseline is edited, nothing else
        config=led.config, records=recs, action="commit",
        files={"docs/x.md": "b" * 40, "tools/verify/prose_baseline.txt": "d" * 40},
        ref="t", admission=["check_prose"])

    assert next(r for r in before["rows"]
                if r["step"] == "check_prose")["status"] == "SATISFIED"
    assert next(r for r in after["rows"]
                if r["step"] == "check_prose")["status"] == "STALE"
    assert after["complete"] is False


def test_v15_declaring_switches_needs_no_reason(tmp_path, config_dir):
    """⚠ `switches` is NOT a narrowing — it makes a type STRICTER. The
    reason-less-narrowing rule exists to stop silent WEAKENING, and pricing the safe
    direction the same as the dangerous one would just discourage the safe one."""
    led = _switched(config_dir, tmp_path)          # no `reason` anywhere
    reqs = led.config.requirements("commit")
    assert reqs["check_prose"]["required"] is True
    assert reqs["check_prose"]["switches"] == ["tools/verify/prose_baseline.txt"]


# -- ⭐ the REVIEW record shape, pinned so the answer cannot drift -------------

def test_a_single_pass_agent_verdict_cannot_wear_an_agreement_badge(ledger):
    """⭐ THE RULE THAT MAKES `agreement` MEAN SOMETHING. ZeroParadox is building the
    emitter that lets review gates write records instead of `*_cleared.txt`, and asked
    for this shape rather than probing it — because a probe record for `editorial`
    would, if accepted, SATISFY A GATE NO REVIEW RAN."""
    with pytest.raises(ValidationFailure, match="V3"):
        ledger.append(good(step="check_paths", verdict="PASS",
                           decided={"how": "agreement", "passes": 1, "agreed": 1,
                                    "who": None}))


def test_agreement_requires_unanimity_not_just_a_quorum(ledger):
    with pytest.raises(ValidationFailure, match="agreed == passes"):
        ledger.append(good(step="check_paths", verdict="PASS",
                           decided={"how": "agreement", "passes": 3, "agreed": 2,
                                    "who": None}))


def test_a_genuine_agreement_round_validates_without_who(ledger):
    """⚠ `who` is enforced by HOW, never by family. For an agreement record the
    accountability is `passes >= 3` plus `run.id`; forcing `who` would produce
    placeholder attribution, which is worse than an honest absence."""
    out = ledger.append(good(step="check_paths", verdict="PASS",
                             decided={"how": "agreement", "passes": 3, "agreed": 3,
                                      "who": None}))
    assert out["id"]


def test_a_review_family_step_may_legitimately_record_mechanically(ledger):
    """⭐ WHY FAMILY CANNOT BE THE TRIGGER FOR REQUIRING `who`. `claim_review` is
    review-family, and its PASS — "no baseline entry was removed" — genuinely IS a
    computation. A rule keyed on family would refuse the one review-family record that
    already works, and would have been added on the way to answering a question about
    the four that do not exist yet."""
    assert ledger.config.requirements("push")["claim_review"]["family"] == "review"
    out = ledger.append(good(step="claim_review", tier="H", verdict="PASS",
                             decided={"how": "mechanical", "passes": 1, "agreed": 1,
                                      "who": None}))
    assert out["id"].startswith("claim_review@")


def test_min_passes_gates_only_agreement_so_a_signature_can_satisfy(ledger):
    """⭐ THE ANSWER TO REQ-22(b), pinned because it decides how four gate briefs get
    written and could not be determined by trying it — the experiment IS a forged
    review on a registered step.

    `min_passes` is 3 and V3 requires `agreed == passes >= min_passes`, but V3 only
    fires on `how: "agreement"`. A `signature` record never reaches it, so a
    single-pass review CAN satisfy a gate — with a signatory, and only that way.
    """
    from core import inventory as inventory_mod
    rec = {"schema": "zp.record.v1", "step": "editorial", "tier": "H",
           "verdict": "PASS", "revision": 0, "inputs": [], "run": {"id": "r"},
           "basis": {"kind": "tree", "value": "a" * 40, "resolved_from": "explicit"},
           "subjects": [{"path": "docs/x.md", "git_blob_id": "b" * 40}],
           "decided": {"how": "signature", "passes": 1, "agreed": 1, "who": "tim"}}
    ledger.append(rec)
    inv = inventory_mod.build(config=ledger.config, records=ledger.store.records(),
                              action="push", files={"docs/x.md": "b" * 40},
                              ref="a" * 40, admission=["editorial"])
    assert next(r for r in inv["rows"]
                if r["step"] == "editorial")["status"] == "SATISFIED"
    assert inv["complete"] is True


def test_a_signature_still_cannot_be_anonymous(ledger):
    """⚠ THE HALF THAT KEEPS THE ABOVE FROM BEING A HOLE. If a single-pass review may
    satisfy a gate through `signature`, then `who` is the entire accountability — and
    V5 is what stops it becoming a `*_cleared.txt` with extra steps."""
    with pytest.raises(ValidationFailure, match="V5"):
        ledger.append(good(step="check_paths", verdict="PASS",
                           decided={"how": "signature", "passes": 1, "agreed": 1,
                                    "who": None}))
