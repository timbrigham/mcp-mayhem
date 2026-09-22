"""The convergence freeze must move when RULES move, and not when COMMENTS move.

⛔⛔ MEASURED 2026-09-18 ON THE CONSUMER'S LIVE REGISTRY. `registry_sha` hashes the FILE, so 812
bytes of added rationale moved the freeze while enforcement stayed byte-identical:

    file sha      66d088e536d2 -> 9be58fb9e626     MOVED
    scope digest  d168b82b4783 -> d168b82b4783     IDENTICAL

⚠⚠ `convergence_bar` ALREADY MADE THIS ARGUMENT AND STOPPED ONE LEVEL TOO HIGH — it split the
registry FILE from the policy FILE so a threshold change would not read as a scope change,
*"or the freeze cries wolf and gets ignored — and a freeze people ignore is worse than none,
because it still reads as protection."* Inside the registry the same collapse survived, in a file
this project deliberately fills with rationale.

⭐ Tim's ruling, 2026-09-18: key the freeze on the enforcement digest.
"""

import json
import pathlib

import pytest

from core import config as config_mod
from core import inventory as inventory_mod

BASE = {
    "schema": "zp.required.v2",
    "version": 2,
    "types": {
        "check_encoding": {"family": "mechanical", "scope": ["*"], "module": "check_encoding.py"},
        "adversary": {"family": "review", "scope": ["*.md"],
                      "scope_exclude": ["CLAUDE.md"], "module": "agent_gate.py"},
    },
}


_SAMPLE_POLICY = pathlib.Path(__file__).resolve().parents[1] / "config" / "policy.v1.sample.json"


def _write(tmp_path, required, policy=None, indent=2, sort_keys=False):
    """⚠ The POLICY is the shipped sample, edited — never hand-built. A hand-built policy drifts
    from the real schema and the test then proves something about a shape nobody runs."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    rp = tmp_path / "required.v2.json"
    rp.write_text(json.dumps(required, indent=indent, sort_keys=sort_keys),
                  encoding="utf-8", newline="\n")
    pol = json.loads(_SAMPLE_POLICY.read_text(encoding="utf-8"))
    pol.update(policy or {})
    pp = tmp_path / "policy.v1.json"
    pp.write_text(json.dumps(pol, indent=2), encoding="utf-8", newline="\n")
    return config_mod.load(pp, rp)


def test_rationale_moves_the_file_hash_and_not_the_enforcement_digest(tmp_path):
    """⭐⭐ THE HEADLINE, and the live measurement in miniature: prose moves one and not the other."""
    before = _write(tmp_path / "a", BASE)
    (tmp_path / "a").mkdir(exist_ok=True)
    with_prose = json.loads(json.dumps(BASE))
    with_prose["types"]["adversary"]["_ridealongs_struck_2026_09_18"] = "⚠ " + ("why " * 200)
    after = _write(tmp_path / "b", with_prose)

    assert before.registry_sha != after.registry_sha, "fixture: the file bytes must differ"
    assert before.registry_scope_digest == after.registry_scope_digest, (
        "rationale moved the enforcement digest — the freeze would cry wolf on a comment")


@pytest.mark.parametrize("field,value", [
    ("scope", ["*.md", "*.lean"]),
    ("scope_exclude", ["CLAUDE.md", "ZeroParadox/*.md"]),
    ("when", "*.md"),
    ("min_coverage", 1.0),
    ("family", "mechanical"),
    ("module", "other_gate.py"),
    # ⛔⛔ `reason` WAS MISSING FROM THIS LIST AND A SHIPPED REFUSAL LINE DEPENDS ON IT.
    # Added 2026-09-22. The re-freeze remedy now prints "⛔ ORDER MATTERS: `reason` is a
    # SERVED key and is INSIDE this digest… EDIT FIRST, then freeze" — a claim I took from
    # the consumer's message and shipped into a user-facing line before verifying it.
    # ⚠⚠ IT IS TRUE, measured: a `reason` edit moves the scope digest, an `_`-prefixed edit
    # does not. But it was TRUE AND UNGUARDED, which is the same exposure as any other
    # unenforced convention — `_strip_rationale` is a denylist, so `reason` is inside the
    # digest by NOT being excluded, and nothing failed if someone later added it to the
    # strip list. A refusal that instructs a reader is a contract; it needs a test.
    ("reason", "a corrected reason string"),
])
def test_every_enforcement_field_moves_the_digest(tmp_path, field, value):
    """⛔ THE OTHER DIRECTION, AND THE ONE THAT MATTERS MORE. A digest that ignores a real rule
    change is worse than the file hash it replaces: the freeze would read HELD while the rules
    moved underneath it, which is the failure nobody checks for."""
    before = _write(tmp_path / "a", BASE)
    changed = json.loads(json.dumps(BASE))
    changed["types"]["adversary"][field] = value
    after = _write(tmp_path / "b", changed)

    assert before.registry_scope_digest != after.registry_scope_digest, (
        f"changing {field!r} did not move the digest — the freeze would hold while rules moved")


def test_an_unknown_new_field_is_counted_not_ignored(tmp_path):
    """⭐⭐ WHY IT IS A DENYLIST AND NOT AN ALLOWLIST, which is the whole design decision.

    An allowlist of known enforcement fields silently ignores a field added LATER — so a genuine
    new rule moves nothing and the freeze holds while the rules change. The denylist's failure
    mode is the opposite and recoverable: a new non-`_` documentation field trips the bar, which
    is visible. **Fail toward noticing.**
    """
    before = _write(tmp_path / "a", BASE)
    changed = json.loads(json.dumps(BASE))
    changed["types"]["adversary"]["some_future_rule"] = {"threshold": 3}
    after = _write(tmp_path / "b", changed)

    assert before.registry_scope_digest != after.registry_scope_digest, (
        "a field this code has never heard of was ignored; an allowlist would hide a new rule")


def test_formatting_alone_moves_nothing(tmp_path):
    """⚠ Same argument as `_sha`'s newline normalisation, one level up: re-indenting or reordering
    keys is transport, not policy."""
    reindented = _write(tmp_path / "a", BASE, indent=4, sort_keys=True)
    compact = _write(tmp_path / "b", BASE)

    assert reindented.registry_sha != compact.registry_sha, "fixture: the bytes must differ"

    assert reindented.registry_scope_digest == compact.registry_scope_digest


def test_a_matching_scope_digest_holds_the_bar(tmp_path):
    cfg = _write(tmp_path / "a", BASE)
    cfg.policy["convergence"] = {"frozen_scope_digest": cfg.registry_scope_digest}

    bar = inventory_mod.convergence_bar(cfg)

    assert bar["frozen"] is True and bar["held"] is True
    assert bar["basis"] == "scope_digest"


def test_the_legacy_file_basis_is_honoured_and_names_itself(tmp_path):
    """⛔ A STORED `frozen_registry_sha` IS A FILE HASH AND MUST NOT BE REINTERPRETED AS A DIGEST.

    Comparing it against the new digest would read `held: false` forever, for a reason no reader
    could see — a true value against the wrong object, which is the defect this fleet exists to
    remove. It keeps its own meaning, and the answer names the basis rather than leaving it to be
    inferred.
    """
    cfg = _write(tmp_path / "a", BASE)
    cfg.policy["convergence"] = {"frozen_registry_sha": cfg.registry_sha}

    bar = inventory_mod.convergence_bar(cfg)

    assert bar["basis"] == "registry_file_sha"
    assert bar["held"] is True, "the legacy value still describes an unchanged file"
    assert bar["scope_digest"] == cfg.registry_scope_digest, "both identities are always reported"


def test_a_broken_legacy_bar_says_the_basis_moves_on_comments(tmp_path):
    """⚠ Otherwise the reader is told THE SCOPE MOVED about a documentation edit — the false alarm
    this change exists to remove, delivered by the very field being migrated away from."""
    cfg = _write(tmp_path / "a", BASE)
    cfg.policy["convergence"] = {"frozen_registry_sha": "0" * 64}

    bar = inventory_mod.convergence_bar(cfg)

    assert bar["held"] is False
    assert "BASIS IS THE REGISTRY FILE HASH" in bar["note"]
    assert "frozen_scope_digest" in bar["note"], "a refusal must name the success condition"


def test_no_freeze_at_all_points_at_the_new_field(tmp_path):
    cfg = _write(tmp_path / "a", BASE)

    bar = inventory_mod.convergence_bar(cfg)

    assert bar["frozen"] is False
    assert "frozen_scope_digest" in bar["note"]

