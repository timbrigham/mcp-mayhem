"""V16 — an agent may not certify that a checker ran when it did not.

⚠⚠ THIS FILE EXISTS BECAUSE OF A MEASURED FORGERY (ZeroParadox, 2026-08-24). Called
against the live server, `validate` — pure, no write — accepted a record claiming
`tier: "M"`, `decided.how: "mechanical"`, `verdict: "PASS"` over real blob IDs at a
real basis and returned `ok: true, errors: []`. A spawned agent already reaches
`append`, so nothing but a brief's instruction stood in front of it.

The rule forbidding it DID exist, in the one place it must not: `record.py`'s CLI
mirror, whose `--tier` accepts only A/H and whose `--how` refuses `mechanical` —
while that same file's docstring says the rules live in the server "in exactly one
place… what makes the mirror defect unrepresentable rather than avoided by
discipline". It was the exception to its own rule, and the only enforcing copy sat
on the path §12j was about to remove.

⚠ THE BAR IS *CHECKABLE*, NEVER UNFORGEABLE. §2 rules out keys and tokens, and
`sign` already concedes that a signature is an ATTRIBUTION. Anyone willing to copy
a blob id can still forge a record. What they cannot forge is its expiry: the
record now NAMES a blob, so editing the checker moves it and the key goes STALE.
`test_editing_the_checker_makes_the_key_stale` is that half, and it is the half
worth more.
"""

import json

import pytest

from conftest import good
from core import inventory as inventory_mod
from core.errors import ValidationFailure
from core.ledger import Ledger

MODULE = "tools/verify/check_invariants.py"


def errs(ledger, record):
    return ledger.validate(record)["errors"]


def _with_module(config_dir, tmp_path, module=MODULE, step="check_invariants"):
    """A registry that declares which file implements a step — the STRICT form of
    V16, where evidence must name that module rather than merely some file."""
    doc = json.loads((config_dir / "required.v2.json").read_text(encoding="utf-8"))
    doc["types"][step] = {"family": "mechanical", "module": module}
    (config_dir / "required.v2.json").write_text(json.dumps(doc), encoding="utf-8")
    return Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


# -- ⭐⭐ the refusal, SEEN to fire --------------------------------------------

def test_the_measured_forgery_is_now_refused(ledger):
    """⭐⭐ THE HEADLINE. This is the exact record ZeroParadox validated clean on
    2026-08-24 — mechanical, PASS, real-shaped blob IDs, no evidence of a run."""
    with pytest.raises(ValidationFailure, match="V16"):
        ledger.append(good(evidence=[]))


def test_the_refusal_names_the_field_and_the_emitter(ledger):
    """⚠ A refusal that does not say what discharges it is how workarounds get
    invented — the same reason §3 of the gitRobot contract requires a refusal to
    name the alternative."""
    found = [e for e in errs(ledger, good(evidence=[])) if e.startswith("V16")]
    assert found, "V16 did not fire"
    assert "evidence" in found[0] and "module_evidence" in found[0]


def test_carrying_the_evidence_validates(ledger):
    """The control on the control: the rule must be SATISFIABLE, or it is just an
    outage with a rule number."""
    assert errs(ledger, good()) == []


# -- ⚠ where V16 must NOT fire, or it becomes an outage -----------------------

def test_a_mechanical_fail_needs_no_evidence(ledger):
    """⚠ PASS ONLY, exactly like V2. A forged mechanical FAIL blocks, and blocking
    wrongly is not the failure this system defends against. Requiring evidence here
    would also stop a checker that died before it could hash itself from recording
    the fact that it died — turning a crash into silence."""
    assert not any(e.startswith("V16") for e in
                   errs(ledger, good(verdict="FAIL", reason="checker crashed",
                                     evidence=[])))


def test_a_signature_needs_no_evidence(ledger):
    """⚠ V16 keys on `decided.how`, never on `tier`. A HUMAN accepting a mechanical
    step is the sanctioned cheap route (§4a) and produces no run to evidence; V5's
    `who` is that record's accountability."""
    assert not any(e.startswith("V16") for e in
                   errs(ledger, good(tier="M", evidence=[],
                                     decided={"how": "signature", "passes": 1,
                                              "agreed": 1, "who": "tim"})))


def test_an_agreement_round_needs_no_evidence(ledger):
    assert not any(e.startswith("V16") for e in
                   errs(ledger, good(evidence=[], tier="A",
                                     decided={"how": "agreement", "passes": 3,
                                              "agreed": 3, "who": None})))


# -- ⭐ evidence is NOT `inputs`, and V4 is why --------------------------------

def test_a_blob_id_in_inputs_is_refused_by_v4(ledger):
    """⭐⭐ WHY THE FIELD IS `evidence` AND NOT `inputs`, PINNED SO IT IS NOT
    RE-LITIGATED. V16 was specified as "the checker module's blob ID in `inputs`".
    It cannot go there: V4 requires every `inputs` entry to name a record ALREADY IN
    THE STREAM (§9b — aggregates name the verdicts they rest on), so the blob id is
    refused by V4 before V16 ever reads it. Collapsing the two fields would leave V4
    unable to tell an aggregate's predecessor from a checker's own source."""
    found = errs(ledger, good(evidence=[], inputs=["c" * 40]))
    assert any(e.startswith("V4") for e in found), found
    assert any(e.startswith("V16") for e in found), found


def test_a_real_aggregate_still_uses_inputs(ledger):
    """⚠ THE HALF THAT KEEPS THE ABOVE FROM READING AS "inputs IS DEPRECATED"."""
    first = ledger.append(good())
    out = ledger.append(good(step="decls", inputs=[first["id"]],
                             evidence=[{"path": "tools/verify/decls.py",
                                        "git_blob_id": "e" * 40}]))
    assert out["appended"] is True


# -- ⭐ the declared module: config makes the rule stricter, never code --------

def test_evidence_naming_some_other_file_is_refused_when_a_module_is_declared(
        tmp_path, config_dir):
    """⭐ Without a declared `module`, V16 asks only that SOME evidence is carried —
    which closes the measured forgery. Declaring the module pins WHICH file, and that
    is a registry edit, not a code change (§9d)."""
    led = _with_module(config_dir, tmp_path)
    found = [e for e in led.validate(good(
        evidence=[{"path": "README.md", "git_blob_id": "c" * 40}]))["errors"]
        if e.startswith("V16")]
    assert found, "V16 did not fire on the wrong module"
    assert MODULE in found[0]


def test_naming_the_declared_module_validates(tmp_path, config_dir):
    led = _with_module(config_dir, tmp_path)
    assert led.validate(good())["errors"] == []


def test_declaring_a_module_is_optional_and_costs_no_reason(tmp_path, config_dir):
    """⚠ `module` makes a type STRICTER, so it is priced like `switches` and not like
    a narrowing. And it stays OPTIONAL on purpose: making it mandatory would refuse
    every mechanical record until every type in a registry this server does not own
    had been annotated — the correct implementation bricking the system."""
    led = _with_module(config_dir, tmp_path)
    reqs = led.config.requirements("commit")
    assert reqs["check_invariants"]["required"] is True
    assert reqs["check_invariants"]["module"] == MODULE
    assert reqs["check_prose"]["module"] is None


# -- ⭐⭐ the half that is not forgeable: the record EXPIRES --------------------

def _inv(led, files, admission=("check_invariants",)):
    return inventory_mod.build(config=led.config, records=led.store.records(),
                               action="commit", files=files, ref="t",
                               admission=list(admission))


def test_editing_the_checker_makes_the_key_stale(ledger):
    """⭐⭐ THE PROPERTY WORTH MORE THAN THE REFUSAL, and the reason evidence is
    indexed rather than merely stored. The record NAMES the checker's blob, so
    editing the checker moves a blob it names: SATISFIED becomes STALE and the step
    re-runs. A forged verdict expires the next time the code it lied about changes.

    This is V15's mechanism applied to the implementing code instead of to an
    exemption list — the same argument, one layer down."""
    ledger.append(good())
    same = {"docs/x.md": "b" * 40, MODULE: "c" * 40}
    edited = {"docs/x.md": "b" * 40, MODULE: "d" * 40}     # the checker changed

    before = _inv(ledger, same)
    after = _inv(ledger, edited)

    assert next(r for r in before["rows"]
                if r["step"] == "check_invariants")["status"] == "SATISFIED"
    assert next(r for r in after["rows"]
                if r["step"] == "check_invariants")["status"] == "STALE"
    assert after["complete"] is False


def test_evidence_is_not_coverage(ledger):
    """⚠⚠ AND IT MUST NEVER BECOME IT. Folding evidence into `subjects` would have
    every checker certifying its own source as reviewed corpus — a step passing
    itself. `coverage()` reads `subjects` alone, and this pins that."""
    ledger.append(good())
    cov = inventory_mod.coverage(records=ledger.store.records(),
                                 paths=["docs/x.md", MODULE])
    assert cov["paths"] == [MODULE]
    assert cov["uncovered"] == 1


def test_the_checker_is_not_reported_as_examined_but_unscoped(ledger):
    """⚠ `subjects_unscoped` exists to catch a scope NARROWER than what a checker
    read. A step's own source is supposed to sit outside its scanned scope, so
    reporting it would make the signal fire on every mechanical record ever written
    — and a signal that fires on everything is one people scroll past."""
    ledger.append(good())
    inv = _inv(ledger, {"docs/x.md": "b" * 40, MODULE: "c" * 40})
    assert MODULE not in inv["unscoped"]
    assert next(r for r in inv["rows"]
                if r["step"] == "check_invariants")["subjects_unscoped"] == []


# -- ⚠ the shape of the field itself ------------------------------------------

def test_evidence_carries_a_git_blob_id_not_a_content_digest(ledger):
    """⚠ The same door the 2026-08-23 sha256 defect came through, on a new field.
    Refused here rather than appended, because such a record reads STALE forever and
    looks exactly like a staleness bug."""
    found = errs(ledger, good(evidence=[{"path": MODULE, "git_blob_id": "c" * 64}]))
    assert any("evidence[0]" in e for e in found), found


def test_evidence_needs_both_a_path_and_a_blob(ledger):
    assert any("evidence[0]" in e for e in
               errs(ledger, good(evidence=[{"git_blob_id": "c" * 40}])))


def test_a_different_checker_is_a_different_fact_not_a_duplicate(ledger):
    """⚠ Evidence is in `payload()`, so two records at one key claiming DIFFERENT
    checkers are a V11 conflict rather than a silent dedupe. Otherwise the second
    append would return "identical record already present" while naming other code."""
    ledger.append(good())
    with pytest.raises(ValidationFailure, match="V11"):
        ledger.append(good(evidence=[{"path": "tools/verify/other.py",
                                      "git_blob_id": "c" * 40}]))
