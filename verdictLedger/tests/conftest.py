"""Fixtures. Every test gets its own stream and its own config copy.

⚠ Tests point `ZPLEDGER_DATA` at a temp path. That is CONFIGURATION, not a bypass
— there is no bypass flag, and a test that needed one would be describing a hole.
"""

import json
import shutil
from pathlib import Path

import pytest

from core.ledger import Ledger

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir(tmp_path):
    """A writable copy of the shipped config, so a test can move a threshold and
    prove the value is data rather than a constant."""
    dst = tmp_path / "config"
    dst.mkdir()
    # ⚠ The SOURCE is `*.sample.json` and the copy is written under the CANONICAL name.
    # A real config directory holds `policy.v1.json`; the repo's own copy is suffixed so
    # nobody confuses it with the live bar in ZeroParadox (Tim, 2026-09-06). Tests therefore
    # keep referring to the canonical names inside `config_dir`, and only the source moved.
    for name in ("policy.v1.json", "required.v2.json"):
        src = name.replace(".json", ".sample.json")
        shutil.copy(ROOT / "config" / src, dst / name)
    return dst


@pytest.fixture
def ledger(tmp_path, config_dir) -> Ledger:
    return Ledger(tmp_path / "records.jsonl",
                  policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


def set_policy(config_dir, **changes):
    """Edit the policy in place. Returns NOTHING — call it for the side effect, then CONSTRUCT
    A NEW `Ledger` over the same `config_dir`.

    ⛔⛔ IT DOES NOT RETURN A LEDGER, AND THE INJECTED `ledger` FIXTURE WILL NOT SEE THE EDIT.
    This docstring has now made that same class of false claim TWICE. It first said "and
    return a Ledger reading it", which it has never done. It was then corrected to "use the
    `ledger` fixture, whose config is re-read live" — ALSO FALSE: `Ledger.__init__` calls
    `config_mod.load` once and `self.config` is a plain attribute, so a fixture built before
    this call holds the pre-edit registry forever.

    ⚠ Measured 2026-09-07: that second claim cost a debugging cycle on a NEW test, which
    asserted a scope change and got the old scope back. Every existing caller already builds
    a fresh Ledger — `test_migration_switch._led` does exactly that — so the docstring was
    describing behaviour that no caller relied on and no test would have caught.

    ⭐ Both errors are the same shape: a comment asserting a control that is not RUN. The fix
    is to say what the callers actually do."""
    path = config_dir / "policy.v1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for dotted, value in changes.items():
        node = doc
        parts = dotted.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def good(**over):
    """A record that passes every rule, so a probe changes exactly one thing.

    ⚠ `check_invariants` on purpose: it declares neither `switches` NOR `scope`, so a
    generic fixture does
    not have to carry somebody's baseline as a subject. Using a switched type here
    would make every unrelated test fail V15 and teach the next reader to weaken it.

    ⚠ This has moved twice — check_prose, then check_paths — as each gained a
    declaration. That is the fixture doing its job rather than churn: a generic record
    must be generic, and the set of types with no declarations shrinks as the bar gets
    described. If this moves again, pick from the no-switch no-scope set rather than
    deleting a declaration to keep a test green.
    """
    rec = {
        "schema": "zp.record.v1",
        "step": "check_invariants",
        "tier": "M",
        "verdict": "PASS",
        "reason": None,
        "basis": {"kind": "tree", "value": "a" * 40, "resolved_from": "explicit"},
        "subjects": [{"git_blob_id": "b" * 40, "path": "docs/x.md"}],
        # ⚠ V16 — a mechanical PASS is refused without evidence. Carried by the
        # generic fixture rather than added per-probe on purpose: a probe must change
        # exactly ONE thing, and a fixture that fails a rule it is not testing makes
        # every other probe ambiguous.
        "evidence": [{"git_blob_id": "c" * 40,
                      "path": "tools/verify/check_invariants.py"}],
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": [],
        "revision": 0,
        "cost": {"seconds": 0.1, "usd": 0.0},
        "run": {"id": "run-1", "started": None, "config_sha": None, "env": {}},
    }
    rec.update(over)
    # ⭐ V19, 2026-09-07: a blocking verdict must NAME what it indicts. A generic fixture
    # must produce a COMPLIANT record, so a probe still changes exactly one thing — the
    # whole point of this builder. Absent `failing` on a FAIL used to be legal and now
    # reads as "indicts every subject", which V19 refuses as a maximal claim by omission.
    #
    # ⚠ Only when the caller did not speak. A test probing V19 itself passes
    # `failing=[]` explicitly and must still get an empty list, not a helpful default —
    # a fixture that repairs the defect under test is a fixture that hides it.
    # ⛔ FAIL ONLY — matching V19's scope, and I got this wrong first. Auto-adding `failing`
    # to an UNDECIDED broke `test_v16b_does_not_stop_a_dying_checker_recording_that_it_died`:
    # the fixture handed the dying-checker probe a `failing` list, which triggered V16b and
    # made the test fail for a reason it was not testing. Exactly the trap the note below
    # names, committed one line above the note.
    if "failing" not in over and rec.get("verdict") == "FAIL":
        rec["failing"] = [s["path"] for s in rec.get("subjects") or []]
    return rec
