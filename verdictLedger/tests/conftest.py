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
    for name in ("policy.v1.json", "required.v2.json"):
        shutil.copy(ROOT / "config" / name, dst / name)
    return dst


@pytest.fixture
def ledger(tmp_path, config_dir) -> Ledger:
    return Ledger(tmp_path / "records.jsonl",
                  policy_path=config_dir / "policy.v1.json",
                  required_path=config_dir / "required.v2.json")


def set_policy(config_dir, **changes):
    """Edit the policy in place and return a Ledger reading it — the control that
    proves a threshold is config: change it, restart nothing, verdict changes."""
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

    ⚠ `check_paths` on purpose: it declares no `switches`, so a generic fixture does
    not have to carry somebody's baseline as a subject. Using a switched type here
    would make every unrelated test fail V15 and teach the next reader to weaken it.
    """
    rec = {
        "schema": "zp.record.v1",
        "step": "check_paths",
        "tier": "M",
        "verdict": "PASS",
        "reason": None,
        "basis": {"kind": "tree", "value": "a" * 40, "resolved_from": "explicit"},
        "subjects": [{"git_blob_id": "b" * 40, "path": "docs/x.md"}],
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": [],
        "revision": 0,
        "cost": {"seconds": 0.1, "usd": 0.0},
        "run": {"id": "run-1", "started": None, "policy_sha": None, "env": {}},
    }
    rec.update(over)
    return rec
