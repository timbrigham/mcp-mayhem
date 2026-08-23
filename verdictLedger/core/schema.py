"""The record shape and its primary key.

⚠⚠ THERE IS EXACTLY ONE HASH IN THIS SYSTEM AND IT IS GIT'S (Tim, 2026-08-23).

The first draft content-addressed each record with a sha256 over its own fields.
That was inherited from the spec and kept unexamined, and it was wrong twice over:

  * **It was redundant.** `basis.value` already carries a git object hash — a tree
    sha at commit time, a commit sha at push time. Git has already content-
    addressed the thing being judged. A second hash over a description of that
    content adds no identity that the first one did not.
  * **It manufactured its own problems.** Hashing fields required pinning a
    canonical JSON encoding (key order, separators, `ensure_ascii`) because a
    reimplementation had to reproduce the digest to re-verify a deposit. And
    because free prose was in the digest, it required a rule forbidding
    nondeterministic `reason` text — a validation rule invented to protect a hash
    that need not have existed.

**The key is composite and readable:** `step@basis#revision`. It follows directly
from V11 — `(step, basis, revision)` is unique in the stream — so that triple IS
the primary key and everything else is payload determined by it. A stranger
re-verifying a deposit in ten years reads the fields; there is no encoding
contract to honour and nothing to recompute.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA_ID = "zp.record.v1"

TIERS = ("M", "A", "H")
VERDICTS = ("PASS", "FAIL", "UNDECIDED")
BASIS_KINDS = ("range", "ref", "scope", "tree")
RESOLVED_FROM = ("explicit", "upstream", "FALLBACK")
DECIDED_HOW = ("mechanical", "agreement", "signature", "override")

# The primary key. Everything else in the record is payload determined by it.
KEY_FIELDS = ("step", "basis.value", "revision")

TOP_LEVEL = ("schema", "id", "step", "tier", "verdict", "reason", "basis",
             "subjects", "decided", "inputs", "revision", "cost", "run")

# Separators chosen so the key stays greppable and unambiguous. A git ref may
# legally contain '#', so `basis.value` is checked for it rather than escaped —
# a one-line guard, not an encoding contract.
KEY_SEP_BASIS = "@"
KEY_SEP_REVISION = "#"


def serialise(obj: Any) -> str:
    """One JSONL line. Sorted keys only so diffs stay readable — nothing depends
    on this encoding for identity any more."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_key(record: dict) -> str:
    """`step@basis#revision` — the whole identity, in a form a human can read.

    `inputs` entries reference this, so a chain is legible in the raw stream:
    `preflight@b5912c5a…#0` names its predecessor plainly instead of pointing at
    a 64-character digest that has to be looked up to mean anything.
    """
    basis = (record.get("basis") or {}).get("value") or ""
    return (f"{record.get('step')}{KEY_SEP_BASIS}{basis}"
            f"{KEY_SEP_REVISION}{record.get('revision', 0)}")


def key_is_ambiguous(record: dict) -> bool:
    """True when `basis.value` contains the revision separator.

    Git permits '#' in a ref name, so a pathological ref could make the key
    parse two ways. Refusing it costs a rename; escaping it would reintroduce the
    encoding contract this design exists to avoid.
    """
    return KEY_SEP_REVISION in ((record.get("basis") or {}).get("value") or "")


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


def payload(record: dict) -> dict:
    """Everything the key does NOT determine — used to tell a duplicate append
    (same key, same payload: dedupe) from a conflict (same key, different payload:
    V11 refuses). Observational fields are excluded: how long a write waited or
    what a run was called must not make the same fact look like a different one.
    """
    return {
        "verdict": record.get("verdict"),
        "reason": record.get("reason"),
        "tier": record.get("tier"),
        "subjects": sorted(
            ((s.get("path"), s.get("blob")) for s in record.get("subjects") or []),
            key=lambda t: (t[0] or "", t[1] or "")),
        "decided": record.get("decided"),
        "inputs": sorted(record.get("inputs") or []),
        "basis_kind": (record.get("basis") or {}).get("kind"),
    }
