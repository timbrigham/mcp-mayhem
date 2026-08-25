"""The V16 cutover: ACCEPT before REQUIRE, and the relaxation cannot go quiet.

⚠⚠ BOTH ORDERINGS BRICK, WHICH IS WHY THIS EXISTS. V16's emitter half lives in
ZeroParadox's `common.record_if_asked`; the rule half lives here. Enforce first and
every mechanical PASS is refused for missing evidence. Emit first against a server
that predates the field and V7 refuses it as an unknown top-level key — measured
against the running server 2026-08-25: `V7: unknown top-level key(s) ['evidence']`.

So: expand, migrate, contract. This build ACCEPTS `evidence` and does not REQUIRE
it; ZeroParadox flips the emitter; then the policy key flips. The config is read
live, so the third step costs NO restart — the config-is-data property (§9d) doing
the migration rather than a special-purpose flag.

⚠ THE OBJECTION THIS FILE ANSWERS is ZeroParadox's own, and it is the right one: a
migration aid is the thing nobody deletes afterwards. Three properties are pinned
below so that cannot happen quietly — ABSENT MEANS STRICT, `status()` names the
relaxation on every call, and the shipped value is asserted, so flipping it for real
turns a test red and forces this file to be revisited.
"""

import json

import pytest

from conftest import good, set_policy
from core.config import ConfigError
from core.ledger import Ledger

ROOT_POLICY = "config/policy.v1.json"


def _led(config_dir, tmp_path, required: bool):
    set_policy(config_dir, **{"migration.v16_evidence_required": required})
    return Ledger(tmp_path / "r.jsonl", policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


# -- ⭐⭐ the switch, both ways -------------------------------------------------

def test_relaxed_accepts_a_mechanical_pass_with_no_evidence(tmp_path, config_dir):
    """Step 1 of the cutover. The field is UNDERSTOOD (no V7) but not DEMANDED, so a
    pre-cutover emitter keeps working across the restart that lands the rule."""
    led = _led(config_dir, tmp_path, False)
    assert led.validate(good(evidence=[]))["errors"] == []


def test_relaxed_still_accepts_evidence_rather_than_rejecting_it(tmp_path, config_dir):
    """⚠ THE HALF THAT MAKES THE CUTOVER POSSIBLE AT ALL. Accepting the field while
    not requiring it is what lets the two repos land in either order — it is the whole
    difference between this and a coordinated cutover that is safe only because
    nothing happened to run in the gap."""
    led = _led(config_dir, tmp_path, False)
    assert led.validate(good())["errors"] == []


def test_enforcing_refuses_the_same_record(tmp_path, config_dir):
    """Step 3. Same record, same build, no restart — the verdict changes because the
    POLICY changed. That is the behavioural proof this is data, not a constant."""
    assert any(e.startswith("V16") for e in
               _led(config_dir, tmp_path, True).validate(good(evidence=[]))["errors"])


def test_the_switch_takes_effect_with_no_restart(tmp_path, config_dir):
    """⭐ Explicitly: one process, one config file, edited between two calls."""
    lax = _led(config_dir, tmp_path, False)
    assert lax.validate(good(evidence=[]))["errors"] == []
    strict = _led(config_dir, tmp_path, True)
    assert strict.validate(good(evidence=[]))["errors"] != []


# -- ⭐⭐ absent means STRICT: the deletion is the safe direction ---------------

def test_deleting_the_key_re_arms_the_rule(tmp_path, config_dir):
    """⭐⭐ THE PROPERTY THAT MAKES THE AID SAFE TO FORGET. Removing the relaxation is
    how the cutover ENDS, so removal must restore the rule, never remove it. A policy
    file written before this build is therefore strict rather than silently
    permissive, and the reason-less-narrowing convention holds: suppression costs a
    deliberate act."""
    path = config_dir / "policy.v1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.pop("migration", None)
    path.write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=path,
                 required_path=config_dir / "required.v2.json")
    assert led.config.v16_required is True
    assert any(e.startswith("V16") for e in led.validate(good(evidence=[]))["errors"])


def test_a_relaxation_written_as_a_string_refuses_the_whole_config(tmp_path, config_dir):
    """⚠ `"false"` is TRUTHY. A relaxation that reads as ON because of a quoting slip
    is the one direction this block must not be wrong in, so the config refuses to
    load at all — and an unloadable config serves UNDECIDED and gates everything."""
    path = config_dir / "policy.v1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["migration"] = {"v16_evidence_required": "false"}
    path.write_text(json.dumps(doc), encoding="utf-8")
    led = Ledger(tmp_path / "r.jsonl", policy_path=path,
                 required_path=config_dir / "required.v2.json")
    # ⚠ A config failure is a SERVED state, not a crash — the server must not die into
    # a restart loop the supervisor cannot fix. So the error is held and every gated
    # action refuses with it.
    assert led.config is None
    assert "boolean" in led.config_error
    with pytest.raises(ConfigError):
        led.validate(good())


# -- ⭐ it cannot go quiet -----------------------------------------------------

def test_status_names_the_relaxation_on_every_call(tmp_path, config_dir):
    """⭐ ZeroParadox's objection, answered mechanically: a migration aid nobody
    deletes. `status()` reports the relaxation and its CONSEQUENCE — not merely that a
    flag is set — on every call, the same reason `signals` prints counts of zero."""
    led = _led(config_dir, tmp_path, False)
    rel = led.status()["relaxations"]
    assert len(rel) == 1
    assert "V16 RELAXED" in rel[0]
    assert "an agent said it did" in rel[0]


def test_status_is_silent_when_nothing_is_relaxed(tmp_path, config_dir):
    """⚠ The control. A field that always says something says nothing."""
    assert _led(config_dir, tmp_path, True).status()["relaxations"] == []


# -- ⭐⭐ what ships is what enforces --------------------------------------------

def test_the_shipped_policy_relaxes_nothing():
    """⭐⭐ THE CUTOVER'S DELETE-ME TEST, GRADUATED INTO A PERMANENT ONE.

    While V16 was landing this asserted the opposite — that the shipped policy was
    still mid-cutover — so that flipping it for real would turn a test RED and force
    the scaffolding out. It did: the `migration` block is gone from
    `config/policy.v1.json`, `conftest.config_dir` no longer overrides it, and
    ABSENT MEANS STRICT does the rest.

    ⚠ IT IS KEPT, INVERTED, RATHER THAN DELETED. The next relaxation will be added by
    someone under the same pressure that produced this one, and the failure mode is
    not adding it — it is leaving it. This test makes shipping a live relaxation a
    deliberate act that turns the suite red, which is the only version of "we will
    remember to remove it" that has ever worked.
    """
    from pathlib import Path
    doc = json.loads((Path(__file__).resolve().parents[1] / ROOT_POLICY)
                     .read_text(encoding="utf-8-sig"))
    assert "migration" not in doc, (
        f"the shipped policy carries a live relaxation: {doc.get('migration')!r}. If "
        f"that is a deliberate cutover, invert this assertion for its duration and "
        f"say what removes it — the machinery below is built for exactly that, and "
        f"`status().relaxations` will announce it on every call meanwhile.")


# -- ⭐⭐ WHERE the bar was read from, not just WHAT it says --------------------

def test_status_reports_the_resolved_config_paths(tmp_path, config_dir):
    """⭐⭐ THE THREE-DAY DRIFT, CLOSED AT ITS ROOT. The deployment served the registry
    from the ledger's own repo while §7, `config.py`'s docstring and §0's build table
    all said it came from ZeroParadox's `tools/verify`. Every reader of all three came
    away believing the correct thing, and nothing in the system could contradict them:
    `policy()` returned the CONTENT and the sha, never the PATH.

    ⚠ A `policy_sha` proves two readers see the same BYTES. It cannot say which FILE
    those bytes came from — which was the unanswerable question, and the reason this
    surfaced only when a sibling session went looking for a file and could not find it.
    """
    led = _led(config_dir, tmp_path, True)
    st = led.status()
    assert st["policy_path"] == str(config_dir / "policy.v1.json")
    assert st["required_path"] == str(config_dir / "required.v2.json")


def test_the_last_resort_location_says_it_is_the_last_resort(tmp_path, config_dir,
                                                             monkeypatch):
    """⚠ NAMING THE PATH IS NOT ENOUGH — a path only reads as wrong to someone who
    already knows where it should be. When the bar is being served from the ledger's
    own `config/`, the field must SAY that is not where §7 puts it. That sentence is
    what would have ended the drift on day one instead of day three."""
    for var in ("ZPLEDGER_CONFIG", "ZPLEDGER_POLICY", "ZPLEDGER_REQUIRED"):
        monkeypatch.delenv(var, raising=False)
    led = _led(config_dir, tmp_path, True)
    assert "NOT where §7 says the bar belongs" in led.config.paths()["config_source"]


def test_an_explicit_config_directory_is_named_as_the_source(tmp_path, config_dir,
                                                             monkeypatch):
    """⚠ The control: when the operator HAS pointed the server somewhere, the field
    reports that rather than the warning above — or the warning becomes noise that
    fires on every healthy deployment."""
    monkeypatch.setenv("ZPLEDGER_CONFIG", str(config_dir))
    led = _led(config_dir, tmp_path, True)
    src = led.config.paths()["config_source"]
    assert src.startswith("ZPLEDGER_CONFIG=")
    assert "last-resort" not in src
