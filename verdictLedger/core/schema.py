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
# ⚠⚠ HOW A VERDICT WAS REACHED — and for a REVIEW-family step this field is the whole
# difference between a record that means a review happened and one that means nothing.
# Written here rather than in a thread because ZeroParadox asked (REQ-21) and correctly
# refused to determine it by experiment: emitting a probe `editorial` record to see
# whether the shape is accepted would, if accepted, SATISFY A GATE NO REVIEW RAN.
#
#   mechanical   a computation. Right for checkers. Also right for `claim_review`,
#                whose PASS ("no baseline entry was removed") genuinely is computed —
#                which is why FAMILY cannot be what decides this field.
#   agreement    an agent round that actually executed. V3: a PASS requires
#                `agreed == passes` and `passes >= policy.agreement.min_passes` (3),
#                so a single-pass LLM verdict cannot wear an agreement badge.
#   signature    a human accepting without the round being run. V5 requires a non-null
#                `who`: an anonymous human pass is the *_cleared.txt hole with extra
#                steps. This is the sanctioned cheap route while emitters are landing —
#                a human accepting a key is attributable; a key that never had to exist
#                is not.
#   override     a REGRADE: "the gate erred", the opposite signal to `signature`, which
#                is an ACCEPT of a standing FAIL as carried debt. V12 requires `who` and
#                forbids overriding your own prior decision.
#
# ⚠⚠ `min_passes` GATES ONLY `agreement`. Measured 2026-08-23: a `signature` record
# with `passes: 1` appends and reads SATISFIED, because V3 never fires on it. So a
# single-pass review CAN satisfy a gate — via `signature`, and only with a signatory.
#
# THE TRAP THAT FOLLOWS, and it is still a trap: the review gates each run ONE agent,
# so `agreement` refuses them (V3 wants 3 unanimous). The tempting fix is to record
# `signature` with the AGENT as `who`. Do not, and this is now enforced by V17 rather
# than asked for: `signature` means a HUMAN accepted a verdict the round did not
# produce, and putting an agent's name there claims an accountability that does not
# exist. Measured 2026-08-25: the server ACCEPTED `signature` with `who:
# "adversary-agent"` -- LED-6's shape one field over, and it was the only route to a
# review PASS that worked, so it was the one an agent under pressure would take.
#
# ⭐ THE ROUTE FOR A DELEGATED AGENT IS `delegated`, which is honest about being one
# round and names the brief it ran under.
#
# The honest shapes for a single agent round are: the agent produces findings and a
# PERSON signs (who = the person, which is what Tim's cheap route is for), or the gate
# genuinely runs three independent passes and records `agreement`. Adding a fifth enum
# value for "one agent judged it" would re-open precisely what V3 exists to close —
# single-pass AI verdicts wearing a consensus badge — under a new name.
#
# ⚠ `who` is enforced by HOW, never by family — signature and override require it,
# mechanical and agreement do not. For an `agreement` record the accountability is
# `passes >= 3` plus `run.id`; setting `who` to name the panel is good practice and is
# deliberately NOT a rule, because a forced field produces placeholder values and a
# placeholder attribution is worse than an honest absence.
#
# ⚠ NOTHING SIGNS A RECORD CRYPTOGRAPHICALLY. `Ledger.sign()` is a verb, not a
# signature: its authority is that the stream is append-only, validated, and binds the
# verdict to content by git blob id. §2 rules a key out — a local key is readable by
# the actor it defends against, and the value here is capability removal and
# auditability, not authentication.
#   delegated    ONE agent round, judged under a NAMED BRIEF, claiming no consensus.
#                V17 requires `who` (which gate) and, on a PASS, `evidence` naming the
#                brief's blob. Added 2026-08-25.
#
# ⚠⚠ THE COMMENT ABOVE USED TO REFUSE THIS VALUE, AND ITS ARGUMENT WAS A NON-SEQUITUR.
# It said a fifth value for "one agent judged it" would "re-open precisely what V3
# exists to close — single-pass AI verdicts wearing a consensus badge — under a new
# name." V3 closes MISLABELLING: a single pass claiming `agreed == passes >= 3`. The
# defect is the false consensus claim, not the fact that an agent judged. A value that
# says honestly "one delegated agent, under this brief" wears no badge at all. V3 is
# untouched and still closes exactly what it closed.
#
# ⚠⚠ AND THE ROUTE IT RECOMMENDED INSTEAD WAS TRANSITIONAL SCAFFOLDING READ AS DESIGN.
# "A human accepting... the sanctioned cheap route WHILE EMITTERS ARE LANDING" — its
# own expiry condition, written into it. The emitters landed 2026-08-25. Meanwhile the
# stream proved the cost: NINE agent review records, every one a FAIL. No delegated
# review had ever recorded a PASS, because there was no honest way to.
#
# ⚠ Tim, 2026-08-25: "the entire idea having these agents is so that I can delegate
# trust to them." That intent appeared in NEITHER contract, which is why a stale
# comment could quietly overrule it.
#
# ⚠ ACCOUNTABILITY WITHOUT AUTHENTICATION, WHICH IS ALL THIS SYSTEM EVER CLAIMED (§2
# rules out keys; `sign` concedes attribution is not authentication). The answer to
# "who decided this" for a delegated agent is NOT a process identity — it is the BRIEF.
# `evidence` names it, so editing the brief moves a blob the record names, the key goes
# STALE and the gate re-runs. A delegated verdict cannot outlive the instructions it
# was made under. Same machinery as V16, pointed at review instead of checkers.
DECIDED_HOW = ("mechanical", "agreement", "signature", "override", "delegated")

# The primary key. Everything else in the record is payload determined by it.
KEY_FIELDS = ("step", "basis.value", "revision")

TOP_LEVEL = ("schema", "id", "step", "tier", "verdict", "reason", "basis",
             "subjects", "evidence", "decided", "inputs", "revision", "cost", "run")

# ⚠⚠ `evidence` IS NOT `inputs`, AND THE DISTINCTION IS WHY THIS FIELD EXISTS.
# V16 was specified as "the checker module's blob ID in `inputs`". It cannot go
# there: V4 requires every `inputs` entry to name a RECORD ALREADY IN THE STREAM
# (§9b: "aggregate steps must name every record they aggregated"), so a blob id in
# `inputs` is refused by V4 before V16 ever reads it. The two fields answer
# different questions and collapsing them would make V4 unable to tell an
# aggregate's predecessor from a checker's own source:
#
#   inputs     WHICH VERDICTS this one rests on   -> record keys, step@basis#revision
#   evidence   WHICH CODE reached this verdict    -> {path, git_blob_id}, same shape
#              as `subjects`, because it is the same kind of claim about content
#
# ⚠ It is NOT `subjects` either. `subjects` is what the verdict is ABOUT, and it
# feeds `coverage()` — putting the checker module there would have the checker
# certifying its own source as reviewed corpus. `inventory` does treat evidence
# like a switch for STALENESS (edit the checker, the key goes stale), which is the
# whole point of recording it; it just never counts as coverage.

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
        "evidence": [],
        "decided": {"how": "mechanical", "passes": 1, "agreed": 1, "who": None},
        "inputs": [],
        "revision": 0,
        "cost": {"seconds": None, "usd": 0.0, "lock_wait_seconds": None},
        "run": {"id": None, "started": None, "config_sha": None, "env": {}},
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
            ((s.get("path"), s.get("git_blob_id")) for s in record.get("subjects") or []),
            key=lambda t: (t[0] or "", t[1] or "")),
        "evidence": sorted(
            ((e.get("path"), e.get("git_blob_id")) for e in record.get("evidence") or []),
            key=lambda t: (t[0] or "", t[1] or "")),
        "decided": record.get("decided"),
        "inputs": sorted(record.get("inputs") or []),
        "basis_kind": (record.get("basis") or {}).get("kind"),
    }
