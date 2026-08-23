"""The record shape, the canonical encoding, and the content-addressed id.

⚠⚠ THE ENCODING IS PINNED HERE AND MUST NEVER BE INHERITED FROM DEFAULTS.
§2a promises the stream/audit join is runnable against the Zenodo deposit in ten
years. That promises a REIMPLEMENTATION can reproduce `id` — which is only true if
key order, separators and unicode handling are specified rather than being
whatever `json.dumps` happened to do that day. `ensure_ascii` is not cosmetic: the
corpus is full of ⊥, σ, c₀, and escaping them changes every hash.

⚠ NO WALL CLOCK IN THE HASH (§4b). `cost`, `run.started`, `run.id` and
`run.policy_sha` are all FIELDS — needed to interpret a verdict and to compute
cost-per-run — but none of them identifies one. Hashing them made idempotency
vacuous: two runs over identical content already differed, so nothing ever
deduped and "appending the identical record twice is idempotent" could not fire.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_ID = "zp.record.v1"

TIERS = ("M", "A", "H")
VERDICTS = ("PASS", "FAIL", "UNDECIDED")
BASIS_KINDS = ("range", "ref", "scope", "tree")
RESOLVED_FROM = ("explicit", "upstream", "FALLBACK")
DECIDED_HOW = ("mechanical", "agreement", "signature", "override")

# The fields that IDENTIFY a record. Everything else is provenance.
IDENTITY_FIELDS = ("step", "basis", "verdict", "reason", "subjects", "revision")

TOP_LEVEL = ("schema", "id", "step", "tier", "verdict", "reason", "basis",
             "subjects", "decided", "inputs", "revision", "cost", "run")


def canonical(obj: Any) -> str:
    """The pinned encoding. Changing any argument here breaks every stored id."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _identity_payload(record: dict) -> dict:
    """Only the identity fields, with subjects normalised.

    Subjects are sorted by (path, sha256) so that a checker reporting the same
    files in a different order does not mint a second identity for one fact.
    """
    subjects = sorted(
        ({"path": s.get("path"), "sha256": s.get("sha256")}
         for s in (record.get("subjects") or [])),
        key=lambda s: (s.get("path") or "", s.get("sha256") or ""),
    )
    basis = record.get("basis") or {}
    return {
        "step": record.get("step"),
        "basis": {"kind": basis.get("kind"), "value": basis.get("value")},
        "verdict": record.get("verdict"),
        "reason": record.get("reason"),
        "subjects": subjects,
        "revision": record.get("revision", 0),
    }


def compute_id(record: dict) -> str:
    """`id = sha256(canonical({step, basis, verdict, reason, subjects, revision}))`

    ⚠ `basis.resolved_from` is deliberately NOT hashed. Whether the basis was
    stated or fell back is a fact about HOW the check was pointed at the content,
    not about WHICH content — and V1 already surfaces a FALLBACK in the record and
    in the rendered line. Hashing it would make the same verdict over the same
    tree hash differently depending on how the range was derived.
    """
    return hashlib.sha256(canonical(_identity_payload(record)).encode("utf-8")).hexdigest()


def empty_record(**over: Any) -> dict:
    """A structurally complete record with every key present.

    Only-leaf-nulls, as the sibling registry does it: a key that can be absent is
    a key whose absence someone will read as a value.
    """
    rec = {
        "schema": SCHEMA_ID,
        "id": None,
        "step": None,
        "tier": "M",
        "verdict": None,
        "reason": None,
        "basis": {"kind": None, "value": None, "resolved_from": None},
        "subjects": [],
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": [],
        "revision": 0,
        "cost": {"seconds": None, "usd": 0.0, "lock_wait_seconds": None},
        "run": {"id": None, "started": None, "policy_sha": None, "env": {}},
    }
    rec.update(over)
    return rec
