"""V1–V14. Each rule makes a defect this project has already paid for UNREPRESENTABLE.

⚠ Every violation is returned, never just the first. A caller fixing one rule per
round trip is a caller who stops using the thing.

⚠ A record that fails is NOT stored and NOT silently dropped: `append` raises with
the rule named, and the caller treats that as UNDECIDED.
"""

from __future__ import annotations

from typing import Optional

from core import schema
from core.config import Config

SIGNABLE_EXEMPT_FAMILIES = ()      # reserved: classes that may never be signed away


def structural(record: dict) -> list[str]:
    """Shape before rules. A rule cannot judge a record it cannot read."""
    out: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]
    if record.get("schema") != schema.SCHEMA_ID:
        out.append(f"schema must be {schema.SCHEMA_ID!r}, got {record.get('schema')!r}")

    unknown = sorted(set(record) - set(schema.TOP_LEVEL))
    if unknown:
        # V7 lives here because it is structural: an unknown key cannot be
        # meaningfully rule-checked, only rejected.
        out.append(f"V7: unknown top-level key(s) {unknown} — rejected, not ignored")

    if not isinstance(record.get("step"), str) or not record["step"].strip():
        out.append("step must be a non-empty string")
    if record.get("tier") not in schema.TIERS:
        out.append(f"tier must be one of {schema.TIERS}, got {record.get('tier')!r}")
    if record.get("verdict") not in schema.VERDICTS:
        out.append(f"verdict must be one of {schema.VERDICTS}, got {record.get('verdict')!r}")

    basis = record.get("basis")
    if not isinstance(basis, dict):
        out.append("basis must be an object")
    else:
        if basis.get("kind") not in schema.BASIS_KINDS:
            out.append(f"basis.kind must be one of {schema.BASIS_KINDS}")
        if not basis.get("value"):
            out.append("basis.value must be set")

    subjects = record.get("subjects")
    if not isinstance(subjects, list):
        out.append("subjects must be an array")
    else:
        for i, s in enumerate(subjects):
            if not isinstance(s, dict) or not s.get("sha256") or not s.get("path"):
                out.append(f"subjects[{i}] needs both sha256 and path")

    decided = record.get("decided")
    if not isinstance(decided, dict):
        out.append("decided must be an object")
    elif decided.get("how") not in schema.DECIDED_HOW:
        out.append(f"decided.how must be one of {schema.DECIDED_HOW}")

    if not isinstance(record.get("inputs"), list):
        out.append("inputs must be an array")
    rev = record.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        out.append("revision must be a non-negative integer")
    if not isinstance(record.get("run"), dict):
        out.append("run must be an object")
    return out


def rules(record: dict, *, config: Config, existing_ids: set,
          tips: Optional[dict] = None, known_policy_shas: Optional[set] = None) -> list[str]:
    """V1–V14. ``tips`` maps ``(step, basis_value)`` -> the highest-revision record."""
    out: list[str] = []
    basis = record.get("basis") or {}
    decided = record.get("decided") or {}
    run = record.get("run") or {}
    verdict = record.get("verdict")
    how = decided.get("how")

    # V1 — a silent fallback to a permissive basis is FRZ-4. Recording it as
    # FALLBACK is what makes basis drift visible without probing for it.
    if basis.get("resolved_from") not in schema.RESOLVED_FROM:
        out.append(f"V1: basis.resolved_from must be one of {schema.RESOLVED_FROM}")

    # V2 — warrant-satisfied-while-empty. Five measured instances.
    if verdict == "PASS" and not (record.get("subjects") or []):
        out.append("V2: verdict PASS with an empty subjects array — a step cannot "
                   "pass having examined nothing")

    # V3 — fake unanimity, and single-pass AI verdicts wearing an agreement badge.
    if verdict == "PASS" and how == "agreement":
        passes, agreed = decided.get("passes"), decided.get("agreed")
        if not isinstance(passes, int) or not isinstance(agreed, int):
            out.append("V3: agreement requires integer passes and agreed")
        else:
            if agreed != passes:
                out.append(f"V3: agreement requires agreed == passes ({agreed} != {passes})")
            if passes < config.min_passes:
                out.append(f"V3: agreement requires passes >= {config.min_passes} "
                           f"(policy.agreement.min_passes), got {passes}")

    # V4 — an aggregate claiming a pass over steps that never ran.
    for rid in record.get("inputs") or []:
        if rid not in existing_ids:
            out.append(f"V4: inputs references {rid!r}, which is not in the stream")

    # V5 — an anonymous human pass.
    if how == "signature" and not (decided.get("who") or "").strip():
        out.append("V5: how 'signature' requires a non-null who")

    # V6 — a block nobody can act on.
    if verdict in ("FAIL", "UNDECIDED"):
        reason = record.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            out.append(f"V6: verdict {verdict} requires a non-empty reason")

    # V8 — 'prose' and 'check_prose' silently becoming two steps, each looking
    # satisfied while the other looks missing. An unregistered type cannot record
    # AT ALL, so the pipeline blocks the moment someone wires in an unregistered
    # check — loudly, at the desk of the person who can fix it.
    step = record.get("step")
    if isinstance(step, str) and not config.is_registered(step):
        out.append(f"V8: step {step!r} is not registered in required.v2.json — "
                   f"an unregistered check cannot record, so it cannot silently not count")

    # V9 — a hand-written record indistinguishable from a pipeline one.
    if not (run.get("id") or "").strip():
        out.append("V9: run.id is required and comes from the pipeline (ZPLEDGER_RUN), "
                   "not the caller's imagination")

    # V10 — policy changes silently re-qualifying every past record.
    ps = run.get("policy_sha")
    if not (ps or "").strip():
        out.append("V10: run.policy_sha is required — a verdict must be interpretable "
                   "against the bar that was in force")
    elif known_policy_shas is not None and ps not in known_policy_shas:
        out.append(f"V10: run.policy_sha {ps[:12]}… names a policy the ledger has "
                   f"never seen; the field would otherwise be decorative")

    # V11 / V13 — branching and endless regrading, both scoped to one basis.
    key = (step, basis.get("value"))
    rev = record.get("revision")
    if isinstance(rev, int) and not isinstance(rev, bool):
        if rev > config.max_depth:
            out.append(f"V13: revision {rev} exceeds policy.supersede.max_depth "
                       f"({config.max_depth}) — regraded to the cap; the step or the "
                       f"subject needs fixing, not another regrade")
        if tips is not None:
            seen = tips.get(key)
            occupant = (seen or {}).get("revisions", {}).get(rev)
            # ⚠ Only a DIFFERENT record in this slot is branching. The same record
            # appended twice is the same fact, and dedupes — checking the slot
            # without comparing ids would make idempotency unreachable.
            if occupant is not None and occupant.get("id") != record.get("id"):
                out.append(f"V11: revision {rev} already exists for step {step!r} at this "
                           f"basis — (step, basis, revision) is unique, so branching is "
                           f"unrepresentable rather than merely detected")
            if rev > 0 and seen is not None and (rev - 1) not in seen.get("revisions", {}):
                out.append(f"V11: revision {rev} has no revision {rev - 1} to supersede "
                           f"at this basis — a chain never crosses bases")
            if rev > 0 and seen is None:
                out.append(f"V11: revision {rev} with no prior revision at this basis")

    # V12 — "sudo it away by declaring it a false positive", the one move that
    # could otherwise unmake every rule above.
    if how == "override" and tips is not None:
        prior = (tips.get(key) or {}).get("latest")
        if prior is not None:
            prior_who = ((prior.get("decided") or {}).get("who") or "").strip()
            who = (decided.get("who") or "").strip()
            if not who:
                out.append("V12: how 'override' requires who")
            elif prior_who and who == prior_who:
                unanimous = (isinstance(decided.get("passes"), int)
                             and decided.get("passes") == decided.get("agreed")
                             and decided.get("passes", 0) >= config.min_passes)
                if not unanimous:
                    out.append(f"V12: {who!r} cannot override their own prior decision on "
                               f"this key without unanimity — otherwise a finding is "
                               f"sudo-ed away by the person it was raised against")

    # V14 — reason is in the identity, so a nondeterministic reason means two
    # identical failures hash differently and dedupe never fires.
    reason = record.get("reason")
    if isinstance(reason, str):
        out.extend(_nondeterministic(reason))
    return out


_CLOCK_HINTS = (
    (r"\b\d+\.\d+\s*s(ec|econds)?\b", "an elapsed time"),
    (r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", "a timestamp"),
    (r"\bpid[ =:]\s*\d+", "a pid"),
    (r"[A-Za-z]:\\\\?Users\\\\?[^\\\\ ]+\\\\?AppData", "an absolute temp path"),
    (r"/tmp/[A-Za-z0-9._-]{6,}", "an absolute temp path"),
)


def _nondeterministic(reason: str) -> list[str]:
    """V14. Heuristic BY NECESSITY — determinism is not decidable from one sample —
    so it flags the shapes that actually occur: a checker helpfully reporting its
    own duration, a timestamp, a pid, a per-run temp path. A miss here costs
    dedupe; a false positive costs a reworded reason. The asymmetry is deliberate.
    """
    import re

    out = []
    for pattern, what in _CLOCK_HINTS:
        if re.search(pattern, reason):
            out.append(f"V14: reason contains {what} and reason is part of the record "
                       f"identity — two identical failures would hash differently and "
                       f"never dedupe. Remove it from the reason.")
    return out


def validate(record: dict, *, config: Config, existing_ids=None, tips=None,
             known_policy_shas=None) -> list[str]:
    """Everything, structural first. Returns [] when the record is acceptable."""
    out = structural(record)
    if any(v.startswith(("record must", "schema must", "step must", "verdict must",
                         "basis must", "decided must")) for v in out):
        # Rules would produce noise on a record this malformed; the shape errors
        # are the actionable ones.
        return out
    return out + rules(record, config=config,
                       existing_ids=existing_ids if existing_ids is not None else set(),
                       tips=tips, known_policy_shas=known_policy_shas)
